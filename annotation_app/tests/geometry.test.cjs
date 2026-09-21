const {test} = require("node:test");
const assert = require("node:assert/strict");
require("../static/geometry.js");
const {bounds, valid} = globalThis.receiptGeometry;

test("decimal vertices retain tilted geometry and derive enclosing bounds", () => {
  const polygon = [[1.2, 4.5], [40.7, 2.1], [42.1, 12.3], [2.6, 14.7]];
  assert.equal(valid(polygon), true);
  assert.deepEqual(bounds(polygon), [1, 2, 43, 15]);
  assert.deepEqual(polygon[0], [1.2, 4.5]);
});

test("reject crossing, touching, duplicate and non-finite vertices", () => {
  for (const p of [
    [[0, 0], [20, 20], [0, 20], [20, 0]],
    [[0, 0], [20, 0], [20, 20], [10, 0], [0, 20]],
    [[0, 0], [20, 0], [20, 0], [0, 20]],
    [[0, 0], [20, 0], [Infinity, 20]],
    [[0, 0], [10, 10], [20, 20]],
  ]) assert.equal(valid(p), false);
});

test("valid concave polygons and either vertex order are supported", () => {
  const polygon = [[0, 0], [20, 0], [10, 10], [20, 20], [0, 20]];
  assert.equal(valid(polygon), true);
  assert.equal(valid([...polygon].reverse()), true);
});
