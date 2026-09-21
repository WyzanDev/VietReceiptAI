"""Temporary image transforms; stored coordinates always refer to the original."""

import math
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


def rotate(image, clockwise):
    return image.rotate(-clockwise, expand=True)


def forward(point, width, height, clockwise):
    x, y = point
    return {
        0: (x, y),
        90: (height - y, x),
        180: (width - x, height - y),
        270: (y, width - x),
    }[clockwise]


def crop_png(image_path, polygon, clockwise=0):
    with Image.open(image_path) as source:
        width, height = source.size
        image = np.array(rotate(source.convert("RGB"), clockwise))
    points = np.array(
        [forward(p, width, height, clockwise) for p in polygon], dtype=np.float32
    )
    if len(points) != 4:
        points = cv2.boxPoints(cv2.minAreaRect(points))
    # Angle order is stable for rectangles and slanted OCR quadrilaterals.
    center = points.mean(axis=0)
    points = np.array(
        sorted(points, key=lambda p: math.atan2(p[1] - center[1], p[0] - center[0]))
    )
    points = np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0).astype(
        np.float32
    )
    tl, tr, br, bl = points
    out_width = max(2, round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    out_height = max(2, round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    target = np.float32(
        [
            [0, 0],
            [out_width - 1, 0],
            [out_width - 1, out_height - 1],
            [0, out_height - 1],
        ]
    )
    crop = cv2.warpPerspective(
        image,
        cv2.getPerspectiveTransform(points, target),
        (out_width, out_height),
        borderMode=cv2.BORDER_REPLICATE,
    )
    stream = BytesIO()
    Image.fromarray(crop).save(stream, format="PNG")
    return stream.getvalue()
