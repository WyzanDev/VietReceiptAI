"use strict";

globalThis.receiptGeometry = (() => {
  const cross = (a, b, c) =>
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const epsilon = 1e-8;
  const onSegment = (a, b, p) =>
    Math.abs(cross(a, b, p)) < epsilon &&
    p[0] >= Math.min(a[0], b[0]) - epsilon &&
    p[0] <= Math.max(a[0], b[0]) + epsilon &&
    p[1] >= Math.min(a[1], b[1]) - epsilon &&
    p[1] <= Math.max(a[1], b[1]) + epsilon;
  const intersects = (a, b, c, d) =>
    (cross(a, b, c) * cross(a, b, d) < 0 &&
      cross(c, d, a) * cross(c, d, b) < 0) ||
    onSegment(a, b, c) || onSegment(a, b, d) ||
    onSegment(c, d, a) || onSegment(c, d, b);

  function bounds(points) {
    return [
      Math.floor(Math.min(...points.map(p => p[0]))),
      Math.floor(Math.min(...points.map(p => p[1]))),
      Math.ceil(Math.max(...points.map(p => p[0]))),
      Math.ceil(Math.max(...points.map(p => p[1]))),
    ];
  }

  function valid(points) {
    if (points.length < 3 || points.some(p => p.length !== 2 || p.some(v => !Number.isFinite(v)))) return false;
    if (new Set(points.map(p => p.join(","))).size !== points.length) return false;
    let area = 0;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      area += a[0] * b[1] - b[0] * a[1];
      for (let j = i + 1; j < points.length; j++) {
        if (j === i + 1 || (i === 0 && j === points.length - 1)) continue;
        if (intersects(a, b, points[j], points[(j + 1) % points.length])) return false;
      }
    }
    return Math.abs(area) >= 0.01;
  }
  return {bounds, valid};
})();
