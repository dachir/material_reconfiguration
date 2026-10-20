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

test('quotation defaults to all five units for a new chantier line', async () => {
  const { quotationSelection } = await import('../src/quantity.js');
  assert.deepEqual(quotationSelection([{ line_id: 'L1', qty: 5 }]), {
    L1: { selected: true, qty: 5 },
  });
});
test('quotation proposes only the three units not already quoted', async () => {
  const { quotationSelection } = await import('../src/quantity.js');
  assert.deepEqual(quotationSelection([{ line_id: 'L1', qty: 5 }], { L1: 2 }), {
    L1: { selected: true, qty: 3 },
  });
});
test('fully quoted lines stay at zero and are deselected', async () => {
  const { quotationSelection } = await import('../src/quantity.js');
  assert.deepEqual(quotationSelection([{ line_id: 'L1', qty: 5 }], { L1: 5 }), {
    L1: { selected: false, qty: 0 },
  });
});
