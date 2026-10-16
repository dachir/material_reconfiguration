export function defaultQuantity(node) {
  const remaining = node.manufacture_qty ?? node.remaining_qty ?? 1;
  return Math.max(1, node.requires_mcp ? remaining : Math.min(remaining, node.fabricable_qty || 1));
}
