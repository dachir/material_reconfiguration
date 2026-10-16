import { test } from 'node:test';
import assert from 'node:assert/strict';
import { defaultQuantity } from '../src/quantity.js';

test('cutting defaults to all ten required panes even when none can be assembled', () => {
  assert.equal(defaultQuantity({ remaining_qty: 10, fabricable_qty: 0, requires_mcp: true }), 10);
});
test('partially available cutting still defaults to the entire remaining request', () => {
  assert.equal(defaultQuantity({ manufacture_qty: 5, fabricable_qty: 2, requires_mcp: true }), 5);
});
test('assembly keeps the available capacity and excludes pending manufacture', () => {
  assert.equal(defaultQuantity({ manufacture_qty: 3, remaining_qty: 5, fabricable_qty: 2 }), 2);
});
