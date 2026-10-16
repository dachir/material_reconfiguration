// Stable node identities preserve selection and expansion across refreshes.
export function flatten(roots) {
	const result = new Map();
	function visit(node) {
		result.set(node.id, node);
		(node.children || []).forEach(visit);
	}
	roots.forEach(visit);
	return result;
}
export function layout(roots, expanded, compact = false) {
	const nodes = [],
		edges = [];
	let nextRow = 0;
	function visit(node, depth) {
		const children = expanded.has(node.id) ? node.children || [] : [];
		const start = nextRow;
		const descendants = children.map((child) => visit(child, depth + 1));
		const y = descendants.length
			? (descendants[0].y + descendants.at(-1).y) / 2
			: nextRow++ * 100 + 35;
		const point = {
			...node,
			x: depth * 285 + 20,
			y,
			depth,
			hiddenChildren: !expanded.has(node.id) && (node.children?.length || 0),
		};
		nodes.push(point);
		descendants.forEach((child) =>
			edges.push({
				id: `${node.id}/${child.id}`,
				from: point,
				to: child,
				ready: child.allocatable_qty >= child.remaining_qty && child.remaining_qty > 0,
				label: `${child.allocatable_qty || 0} / ${child.remaining_qty || 0} prêts`,
			})
		);
		if (nextRow === start) nextRow++;
		return point;
	}
	roots.forEach((root) => {
		visit(root, 0);
		nextRow += compact ? 0 : 0.35;
	});
	return {
		nodes,
		edges,
		width: Math.max(700, ...nodes.map((n) => n.x + 245)),
		height: Math.max(450, nextRow * 100 + 40),
	};
}
export function routeFor(result) {
	if (result.action === "mcp" && result.mcps?.length === 1)
		return ["Form", "Material Cutting Plan", result.mcps[0]];
	return null;
}
