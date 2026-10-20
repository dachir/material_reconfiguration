export function defaultQuantity(node) {
  const remaining = node.manufacture_qty ?? node.remaining_qty ?? 1;
  return Math.max(1, node.requires_mcp ? remaining : Math.min(remaining, node.fabricable_qty || 1));
}

export function quotationSelection(lines, usage = {}) {
  return Object.fromEntries(lines.map(row => {
    const remaining = Math.max(0, Number(row.qty) - Number(usage[row.line_id] || 0));
    return [row.line_id, { selected: remaining > 0, qty: remaining }];
  }));
}
