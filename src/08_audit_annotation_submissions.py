#!/usr/bin/env python3
"""Read-only validation of assignments against the frozen registry; no automatic merging."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from jsonschema import Draft202012Validator


def read_jsonl(path):
    records=[]
    for index,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{index}: {error}") from error
    return records


def audit(root, require_completed=False):
    registry=read_jsonl(root / "assignment_registry.jsonl")
    validator=Draft202012Validator(json.loads((root / "common/annotation_schema.json").read_text()))
    errors=[]
    groups=defaultdict(list)
    seen_keys=set(); seen_ids=set(); seen_hashes=set()
    for row in registry:
        key=(row['dataset'],row['source_split'],row['image_id'])
        if key in seen_keys or row['task_id'] in seen_ids or row['sha256'] in seen_hashes:
            errors.append(f"Duplicate identity/task/image in registry: {key}")
        seen_keys.add(key); seen_ids.add(row['task_id']); seen_hashes.add(row['sha256'])
        groups[row['package']].append(row)
    counts=Counter(); completed=0
    actual_packages={p.parent.relative_to(root).as_posix() for p in root.rglob('annotations.jsonl')}
    if actual_packages != set(groups):
        errors.append("Missing or unregistered annotation packages")
    for package,rows in groups.items():
        folder=(root / package).resolve()
        if not folder.is_relative_to(root.resolve()):
            errors.append(f"Package outside task root: {package}"); continue
        expected={r['task_id']:r for r in rows}
        try:
            with (folder / 'manifest.csv').open(encoding='utf-8', newline='') as stream:
                manifest=list(csv.DictReader(stream))
            ids=[r.get('task_id') for r in manifest]
            if len(ids)!=len(set(ids)) or set(ids)!=set(expected):
                errors.append(f"Missing/extra/duplicate manifest IDs: {package}")
            for item in manifest:
                reference=expected.get(item.get('task_id'))
                if reference is None:
                    continue
                for key in ('dataset','source_split','image_file','width','height','sha256'):
                    if item.get(key)!=str(reference[key]):
                        errors.append(f"{package}: manifest mismatch for {key}")
                for key in ('member','package','image_id','round'):
                    if key in item and item[key]!=str(reference.get(key,'')):
                        errors.append(f"{package}: manifest mismatch for {key}")
        except OSError as error:
            errors.append(str(error))
        try:
            records=read_jsonl(folder / 'annotations.jsonl')
        except (OSError,ValueError) as error:
            errors.append(str(error)); continue
        actual=Counter(r.get('task_id') for r in records)
        if set(actual)!=set(expected) or any(n!=1 for n in actual.values()):
            errors.append(f"Missing/extra/duplicate task IDs: {package}")
        image_files={r['image_file'] for r in rows}
        actual_files={p.relative_to(folder).as_posix() for p in (folder/'images').rglob('*') if p.is_file()}
        if actual_files!=image_files:
            errors.append(f"Missing or extra images in {package}")
        for record in records:
            task_id=record.get('task_id')
            row=expected.get(task_id)
            if not row:
                continue
            problems=list(validator.iter_errors(record))
            if problems:
                errors.append(f"{task_id}: schema: {problems[0].message}"); continue
            for key in ('dataset','source_split','image_id','image_file','width','height'):
                if record[key]!=row[key]:
                    errors.append(f"{task_id}: changed frozen {key}")
            if record['assignment']['member']!=row['member']:
                errors.append(f"{task_id}: changed member")
            # Use the trusted registry path even when the submitted path was changed.
            image_path=(folder/row['image_file']).resolve()
            if not image_path.is_relative_to(folder):
                errors.append(f"{task_id}: unsafe registry image path"); continue
            try:
                digest=hashlib.sha256(image_path.read_bytes()).hexdigest()
                if digest!=row['sha256']:
                    errors.append(f"{task_id}: image SHA-256 changed")
                with Image.open(image_path) as im:
                    if im.size!=(row['width'],row['height']):
                        errors.append(f"{task_id}: image dimensions changed")
            except OSError as error:
                errors.append(f"{task_id}: {error}")
            counts[(row['dataset'],row['source_split'])]+=1
            is_completed=record['assignment']['status']=='completed'
            completed+=is_completed
            if require_completed and not is_completed:
                errors.append(f"{task_id}: document not completed")
            for name,field in record['fields'].items():
                for region in field['regions']:
                    if region.get('normalized_value')!='':
                        errors.append(f"{task_id}/{name}: normalized_value must be empty")
            if not (require_completed or is_completed):
                continue
            if record['ocr']['status']!='verified' or not record['ocr']['tokens']:
                errors.append(f"{task_id}: OCR tokens missing or not verified")
            token_ids=[t['token_id'] for t in record['ocr']['tokens']]
            if len(token_ids)!=len(set(token_ids)):
                errors.append(f"{task_id}: duplicate token IDs")
            for name,field in record['fields'].items():
                if field['present'] is None or not field['verified']:
                    errors.append(f"{task_id}/{name}: field not verified")
                if field['present'] is not None and bool(field['regions'])!=field['present']:
                    errors.append(f"{task_id}/{name}: inconsistent presence/regions")
                regions=field['regions']
                if len({r['region_id'] for r in regions})!=len(regions):
                    errors.append(f"{task_id}/{name}: duplicate region IDs")
                for region in regions:
                    if region['legibility']=='unreviewed':
                        errors.append(f"{task_id}/{name}: region not reviewed")
                    if region['legibility']=='clear' and not region['raw_text'].strip():
                        errors.append(f"{task_id}/{name}: clear region has empty text")
            regions=[r for f in record['fields'].values() for r in f['regions']]
            for obj in [*record['ocr']['tokens'],*regions]:
                x1,y1,x2,y2=obj['bbox']
                if not 0<=x1<x2<=record['width'] or not 0<=y1<y2<=record['height']:
                    errors.append(f"{task_id}: invalid bbox {obj['bbox']}")
                if any(not (0<=x<=record['width'] and 0<=y<=record['height']) for x,y in obj['polygon']):
                    errors.append(f"{task_id}: polygon outside image")
    return {'registered_images':len(registry),'packages':len(groups),'completed':completed,
            'counts':{f'{d}/{s}':n for (d,s),n in sorted(counts.items())},
            'errors':errors,'note':'Structural checks only; text accuracy and alignment require review.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-root',type=Path,default=Path(__file__).resolve().parents[1]/'task')
    parser.add_argument('--require-completed',action='store_true')
    args=parser.parse_args()
    result=audit(args.task_root.resolve(),args.require_completed)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(2 if result['errors'] else 0)


if __name__=='__main__':
    main()
