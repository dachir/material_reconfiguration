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
export function layout(roots, expanded, compact = false, plans = [], showStudies = true) {
	const nodes = [],
		edges = [], studies = [];
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
		const order = visit(root, 0);
		const known = new Set();
		for (const study of (showStudies ? root.technical_studies || [] : [])) {
			if (!study.name || study.docstatus !== 1 || known.has(study.name)) continue;
			known.add(study.name);
			const point = {...study, id:`${root.id}/study/${study.name}`, sales_order:root.id,
				x:order.x + 20, y:order.y + 100 + (known.size - 1) * 90};
			studies.push(point);
			edges.push({id:`${root.id}/${point.id}`, from:order, to:point, study:true, ready:true, label:''});
			nextRow = Math.max(nextRow, Math.ceil((point.y + 90 - 35) / 100));
		}
		nextRow += compact ? 0 : 0.35;
	});
	const visible = new Map(nodes.map(n => [n.id, n]));
	const paths = new Map();
	function rememberPath(node, ancestors) {
		const path = [...ancestors, node.id];
		paths.set(node.id, path);
		(node.children || []).forEach(child => rememberPath(child, path));
	}
	roots.forEach(root => rememberPath(root, []));
	// Reserve the far-right column independently of branch expansion depth.
	let maxDepth = 0;
	function measure(node, depth) {
		maxDepth = Math.max(maxDepth, depth);
		(node.children || []).forEach(child => measure(child, depth + 1));
	}
	roots.forEach(root => measure(root, 0));
	const planX = (maxDepth + 1) * 285 + 20;
	const mcps = [...plans].sort((a,b) => a.creation.localeCompare(b.creation) || a.name.localeCompare(b.name))
		.map((plan, index) => ({...plan, x:planX, y:index * 100 + 35}));
	for (const plan of mcps) {
		const sources = new Set();
		for (const id of new Set(plan.stock_ids)) {
			const path = plan.stock_paths?.[id] || paths.get(id) || [id];
			const sourceId = [...path].reverse().find(key => visible.has(key));
			const source = visible.get(sourceId);
			// Hidden stocks share a single connection from their visible ancestor.
			if (source && !sources.has(sourceId)) {
				sources.add(sourceId);
				edges.push({id:`${sourceId}/${plan.id}`, from:source, to:plan, mcp:true,
					ready:plan.docstatus === 1, label:''});
			}
		}
	}
	return {
		nodes,
		studies,
		mcps,
		edges,
		width: Math.max(700, ...[...nodes, ...studies, ...mcps].map((n) => n.x + 245)),
		height: Math.max(450, nextRow * 100 + 40, mcps.length * 100 + 70),
	};
}
export function studyRouteFor(study) {
	return study?.name && study.docstatus === 1 ? ['technical-study', study.name] : null;
}
export function routeFor(result) {
	if (result.action === "mcp" && result.mcps?.length === 1)
		return ["Form", "Material Cutting Plan", result.mcps[0]];
	return null;
}
