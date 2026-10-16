<script setup>
import {printDocument} from "./printing.js";
import { ref, reactive, computed, onBeforeUnmount } from "vue";
import { flatten, layout, routeFor } from "./layout.js";
const api = "mat_reco.material_reconfiguration.services.workshop_service.";
const roots = ref([]),
	errors = ref([]),
	counters = ref({}),
	primaryItems = ref([]),
	companies = ref([]);
const chantiers = ref([]), sections = ref([]);
const expanded = ref(new Set()),
	selectedId = ref(null),
	busy = ref(false),
	acting = ref(false),
	stale = ref(false),
	error = ref("");
const dimensionFields = ref([]),
	dimensions = reactive({});
const filters = reactive({
 chantier: "", section: "", state: "", sales_order: "",
	search: "",
	primary_item: "",
	company: "",
	from_date: "",
	to_date: "",
});
const mode = ref("tree"),
	zoom = ref(0.85),
	quantity = ref(1),
	preview = ref(null),
	result = ref(null),
	asOf = ref("");
const active = ref(false),
	viewport = ref(null),
	dialog = ref(null);
let timer = null,
	debounce = null,
	requestId = 0,
	key = null,
	drag = null,
	lastFocus = null;
const loadedOrders = new Set();
const index = computed(() => flatten(roots.value));
const selected = computed(() => index.value.get(selectedId.value));
const scene = computed(() => layout(roots.value, expanded.value));
const actionLabel = computed(() => {
	const node = selected.value;
	if (!node) return "Fabriquer";
	const requested = node.item_type === "ORDER" ? node.manufacture_qty : quantity.value;
	return node.fabricable_qty >= requested
		? "Fabriquer"
		: node.requires_mcp
		? "Préparer MCP"
		: "Vérifier la fabrication";
});
const cards = computed(() => [
	{ label: "Commandes en cours", value: counters.value.orders || 0, icon: "▤", tone: "cyan" },
	{ label: "Ouvrages à fabriquer", value: counters.value.works || 0, icon: "◇", tone: "blue" },
	{
		label: "Réalisables maintenant",
		value: counters.value.fabricable || 0,
		icon: "⬡",
		tone: "green",
	},
	{
		label: "Découpes manquantes",
		value: counters.value.missing_cuts || 0,
		icon: "▱",
		tone: "red",
	},
	{ label: "Commandes bloquées", value: counters.value.blocked || 0, icon: "!", tone: "orange" },
]);
async function call(method, args = {}) {
	const response = await frappe.call({
		method: api + method,
		args,
		type: method === "execute_action" ? "POST" : "GET",
	});
	return response.message;
}
function message(e) {
	return (
		e?.message ||
		"Impossible de terminer l’opération. Consultez le message ERPNext puis actualisez."
	);
}
async function refresh() {
	if (acting.value) {
		stale.value = true;
		return;
	}
	const current = ++requestId;
	busy.value = true;
	error.value = "";
	try {
		const data = await call("get_dashboard", {
			filters: JSON.stringify(filters),
			expanded_orders: JSON.stringify([...loadedOrders]),
		});
		if (current !== requestId) return;
		roots.value = data.roots;
		errors.value = data.errors;
		counters.value = data.counters;
		primaryItems.value = data.primary_items;
		companies.value = data.companies;
        chantiers.value = data.chantiers || []; sections.value = data.sections || [];
		dimensionFields.value = data.dimension_fields || [];
		asOf.value = data.as_of;
		if (selectedId.value && !index.value.has(selectedId.value)) selectedId.value = null;
		expanded.value = new Set([...expanded.value].filter((id) => index.value.has(id)));
		stale.value = false;
	} catch (e) {
		if (current === requestId) {
			error.value = message(e);
			stale.value = true;
		}
	} finally {
		if (current === requestId) busy.value = false;
	}
}
function search() {
	clearTimeout(debounce);
	debounce = setTimeout(refresh, 350);
}
async function toggle(node) {
	if (node.has_children && !node.children?.length) {
		loadedOrders.add(node.id);
		await refresh();
	}
	const next = new Set(expanded.value);
	next.has(node.id) ? next.delete(node.id) : next.add(node.id);
	expanded.value = next;
}
function select(node) {
	selectedId.value = node.id;
	quantity.value = Math.max(
		1,
		Math.min(node.manufacture_qty ?? node.remaining_qty ?? 1, node.fabricable_qty || 1)
	);
}
async function expandAll() {
	roots.value.forEach((r) => loadedOrders.add(r.id));
	await refresh();
	expanded.value = new Set(
		[...index.value.values()].filter((n) => n.children?.length).map((n) => n.id)
	);
}
async function setMode(value) {
	mode.value = value;
	if (value === "list") {
		roots.value.forEach((r) => loadedOrders.add(r.id));
		await refresh();
	}
}
function progress(n) {
	return Math.min(100, (100 * (n.produced_qty || 0)) / (n.required_qty || n.remaining_qty || 1));
}
function dimensionLabel(n) {
	return n.length_mm ? `${n.length_mm} × ${n.width_mm} × ${n.thickness_mm} mm` : "";
}
function close() {
	if (acting.value) return;
	preview.value = null;
	result.value = null;
	dialog.value?.close();
	lastFocus?.focus();
}
async function prepare() {
 if(selected.value?.partial_view){error.value="Sélectionnez une ligne d’ouvrage pour agir dans cette vue filtrée.";return;}
	if (!selected.value || busy.value || stale.value) return;
	acting.value = true;
	error.value = "";
	try {
		preview.value = await call("preview_action", {
			sales_order: selected.value.sales_order,
			node_id: selected.value.id,
			qty:
				selected.value.item_type === "ORDER"
					? selected.value.manufacture_qty
					: quantity.value,
			dimensions: JSON.stringify(dimensions),
		});
		key =
			crypto.randomUUID?.() ||
			Array.from(crypto.getRandomValues(new Uint32Array(4)), (n) => n.toString(16)).join(
				"-"
			);
		lastFocus = document.activeElement;
		dialog.value.showModal();
	} catch (e) {
		error.value = message(e);
		stale.value = true;
	} finally {
		acting.value = false;
	}
}
async function execute() {
	if (acting.value || !preview.value) return;
	acting.value = true;
	try {
		const p = preview.value;
		result.value = await call("execute_action", {
			sales_order: p.sales_order,
			node_id: p.node_id,
			qty: p.qty,
			version: p.version,
			request_key: key,
			dimensions: JSON.stringify(dimensions),
		});
		const route = routeFor(result.value);
		acting.value = false;
		await refresh();
		if (route) {
			close();
			frappe.set_route(...route);
		}
	} catch (e) {
		const failure = message(e);
		acting.value = false;
		close();
		await refresh();
		error.value = failure;
	} finally {
		acting.value = false;
	}
}
function onUpdate() {
	stale.value = true;
	clearTimeout(debounce);
	debounce = setTimeout(refresh, 500);
}
function openChantiers() { frappe.set_route("chantiers"); }
function show() {
 const chantier = sessionStorage.getItem("univers-workshop-chantier");
 if (chantier) { filters.chantier=chantier;filters.section="";sessionStorage.removeItem("univers-workshop-chantier"); }
	if (active.value) {
		refresh();
		return;
	}
	active.value = true;
	refresh();
	frappe.realtime.on("workshop_updated", onUpdate);
	timer = setInterval(refresh, 45000);
}
function hide() {
	active.value = false;
	clearInterval(timer);
	clearTimeout(debounce);
	frappe.realtime.off("workshop_updated", onUpdate);
}
onBeforeUnmount(hide);
defineExpose({ show, hide });
function panStart(e) {
	if (e.target.closest("button") || e.button !== 0) return;
	drag = {
		x: e.clientX,
		y: e.clientY,
		left: viewport.value.scrollLeft,
		top: viewport.value.scrollTop,
	};
	viewport.value.setPointerCapture(e.pointerId);
}
function panMove(e) {
	if (drag) {
		viewport.value.scrollLeft = drag.left - e.clientX + drag.x;
		viewport.value.scrollTop = drag.top - e.clientY + drag.y;
	}
}
function panEnd() {
	drag = null;
}
function wheel(e) {
	if (!e.ctrlKey && !e.metaKey) return;
	e.preventDefault();
	zoom.value = Math.min(1.5, Math.max(0.4, zoom.value - e.deltaY * 0.001));
}
</script>

<template>
	<div class="ug-workshop">
		<main class="ug-main">
			<div class="ug-topbar">
				<label class="ug-search"
					><span>⌕</span
					><input
						v-model="filters.search"
						aria-label="Rechercher une commande ou un article"
						placeholder="Rechercher une commande, un article…"
						@input="search" /></label
				><span class="ug-top-note">ERPNext <i></i> Atelier connecté</span>
			</div>
			<header class="ug-header">
				<div class="ug-factory">▥</div>
				<div>
					<h1>Tableau de bord interactif de l’atelier</h1>
					<p>Commandes en cours de fabrication</p>
				</div>
				<div class="ug-live">
					<i :class="{ warning: stale }"></i
					>{{ stale ? "Actualisation nécessaire" : "Atelier en production" }}
				</div>
			</header>
			<section class="ug-filters" aria-label="Filtres de fabrication">
                <button @click="openChantiers">Chantiers</button>
                <label>Chantier<select v-model="filters.chantier" @change="filters.section=''; refresh()"><option value="">Tous les chantiers</option><option v-for="c in chantiers" :key="c.name" :value="c.name">{{c.name}} — {{c.designation}}</option></select></label>
                <label>Section<select v-model="filters.section" @change="refresh"><option value="">Toutes les sections</option><option v-for="s in sections" :key="s.name" :value="s.name">{{s.section_name}}</option></select></label>
                <label>Commande<input v-model="filters.sales_order" placeholder="Référence exacte" @input="search" /></label>
                <label>Fabrication<select v-model="filters.state" @change="refresh"><option value="">Tous les états</option><option value="ok">Besoin satisfait</option><option value="ready">Réalisable</option><option value="partial">Partielle</option><option value="blocked">Bloquée</option></select></label>
				<label
					>Société<select v-model="filters.company" @change="refresh">
						<option value="">Toutes les sociétés</option>
						<option v-for="c in companies" :key="c">{{ c }}</option>
					</select></label
				>
				<label
					>Item PRIMAIRE<select v-model="filters.primary_item" @change="refresh">
						<option value="">Toutes les matières</option>
						<option v-for="p in primaryItems" :key="p.name" :value="p.name">
							{{ p.item_name }}
						</option>
					</select></label
				>
				<label v-for="d in dimensionFields" :key="d.fieldname"
					>{{ d.label
					}}<select v-model="dimensions[d.fieldname]">
						<option value="">Selon commande / société</option>
						<option v-for="value in d.options" :key="value">{{ value }}</option>
					</select></label
				>
				<label>Du<input v-model="filters.from_date" type="date" @change="refresh" /></label
				><label>Au<input v-model="filters.to_date" type="date" @change="refresh" /></label>
				<button :disabled="busy || acting" @click="refresh">
					↻ {{ busy ? "Actualisation…" : "Actualiser" }}
				</button>
				<div class="ug-switch">
					<button :class="{ primary: mode === 'tree' }" @click="setMode('tree')">
						♧ Vue arbre</button
					><button :class="{ primary: mode === 'list' }" @click="setMode('list')">
						☷ Vue liste
					</button>
				</div>
			</section>
			<div v-if="error" class="ug-alert" role="alert">{{ error }}</div>
			<div v-if="errors.length" class="ug-alert" role="alert">
				<strong>{{ errors.length }} ligne(s) nécessitent une correction :</strong>
				<div v-for="(e, i) in errors" :key="i">{{ e.sales_order }} — {{ e.message }}</div>
			</div>
			<div class="ug-cards">
				<article v-for="card in cards" :key="card.label" :class="card.tone">
					<span class="ug-card-icon">{{ card.icon }}</span>
					<div>
						<strong>{{ card.value }}</strong
						><span>{{ card.label }}</span>
					</div>
				</article>
			</div>
			<div class="ug-content" :class="{ 'with-detail': selected }">
				<section class="ug-graph-panel" :aria-busy="busy">
					<div class="ug-panel-heading">
						<h2>
							<span>♧</span> Arbre de fabrication
							<small>(commandes non terminées)</small>
						</h2>
						<div class="ug-graph-tools">
							<button
								title="Réduire le zoom"
								aria-label="Réduire le zoom"
								@click="zoom = Math.max(0.4, zoom - 0.1)"
							>
								−</button
							><span>{{ Math.round(zoom * 100) }} %</span
							><button
								aria-label="Augmenter le zoom"
								@click="zoom = Math.min(1.5, zoom + 0.1)"
							>
								+</button
							><button @click="expandAll">Tout développer</button
							><button @click="expanded = new Set()">Réduire</button>
						</div>
					</div>
					<div v-if="!roots.length && !busy" class="ug-empty">
						<span>◇</span>
						<h3>Aucune fabrication en attente</h3>
						<p>Aucune commande incomplète ne correspond aux filtres.</p>
					</div>
					<div
						v-if="mode === 'tree'"
						ref="viewport"
						class="ug-viewport"
						tabindex="0"
						aria-label="Graphe de fabrication, glisser pour déplacer"
						@pointerdown="panStart"
						@pointermove="panMove"
						@pointerup="panEnd"
						@pointercancel="panEnd"
						@wheel="wheel"
					>
						<div
							class="ug-scene-space"
							:style="{
								width: scene.width * zoom + 'px',
								height: scene.height * zoom + 'px',
							}"
						>
							<div
								class="ug-scene"
								:style="{
									width: scene.width + 'px',
									height: scene.height + 'px',
									transform: `scale(${zoom})`,
								}"
							>
								<svg
									class="ug-links"
									:width="scene.width"
									:height="scene.height"
									aria-hidden="true"
								>
									<g
										v-for="edge in scene.edges"
										:key="edge.id"
										:class="{ satisfied: edge.ready }"
									>
										<path
											:d="`M ${edge.from.x + 218} ${edge.from.y + 35} H ${
												edge.from.x + 234
											} V ${edge.to.y + 35} H ${edge.to.x}`"
										/>
										<circle :cx="edge.to.x" :cy="edge.to.y + 35" r="4" />
										<text
											:x="edge.to.x - 5"
											:y="edge.to.y + 24"
											text-anchor="end"
										>
											{{ edge.label }}
										</text>
									</g>
								</svg>
								<div
									v-for="node in scene.nodes"
									:key="node.id"
									class="ug-node"
									:class="[
										node.state,
										{
											selected: selectedId === node.id,
											order: node.item_type === 'ORDER',
										},
									]"
									:style="{ left: node.x + 'px', top: node.y + 'px' }"
								>
									<button
										v-if="node.children?.length || node.has_children"
										class="ug-expand"
										:aria-label="
											expanded.has(node.id)
												? 'Replier ' + node.label
												: 'Développer ' + node.label
										"
										:aria-expanded="expanded.has(node.id)"
										@click="toggle(node)"
									>
										{{ expanded.has(node.id) ? "⌄" : "›" }}
									</button>
									<button
										class="ug-node-body"
										:title="node.label"
										@click="select(node)"
									>
										<span class="ug-node-icon">{{
											node.item_type === "ORDER"
												? "▤"
												: node.item_type === "OUVRAGE"
												? "◈"
												: node.item_type === "DECOUPE"
												? "▱"
												: "⬡"
										}}</span
										><span class="ug-node-text"
											><strong>{{ node.label }}</strong
											><small v-if="node.item_type === 'ORDER'"
												>{{ node.produced_qty }} /
												{{ node.required_qty }} fabriqués</small
											><small v-else
												>{{
													node.is_final
														? `${node.produced_qty} fabriqués · `
														: ""
												}}{{ node.remaining_qty }} à réaliser</small
											><span
												v-if="dimensionLabel(node)"
												class="ug-dimensions"
												>{{ dimensionLabel(node) }}</span
											><span
												v-if="node.item_type !== 'ORDER'"
												class="ug-state-text"
												>{{ node.state_label
												}}<template v-if="node.fabricable_qty">
													· {{ node.fabricable_qty }} prêts</template
												></span
											><span v-else class="ug-progress"
												><i
													:style="{ width: progress(node) + '%' }"
												></i></span
										></span>
									</button>
								</div>
							</div>
						</div>
					</div>
					<div v-else class="ug-list-wrap">
						<table class="ug-table">
							<thead>
								<tr>
									<th>Commande / ouvrage</th>
									<th>Dimensions</th>
									<th>Conforme</th>
									<th>Restant</th>
									<th>Fabricable</th>
									<th>État</th>
								</tr>
							</thead>
							<tbody>
								<template v-for="root in roots" :key="root.id"
									><tr class="ug-order-row">
										<th colspan="6">
											{{ root.label }} <small>{{ root.customer }}</small>
										</th>
									</tr>
									<tr v-for="n in root.children" :key="n.id">
										<td>
											<button class="ug-text-button" @click="select(n)">
												{{ n.label }}
											</button>
										</td>
										<td>{{ dimensionLabel(n) }}</td>
										<td>{{ n.produced_qty }} / {{ n.required_qty }}</td>
										<td>{{ n.remaining_qty }}</td>
										<td>{{ n.fabricable_qty }}</td>
										<td>{{ n.state_label }}</td>
									</tr></template
								>
							</tbody>
						</table>
					</div>
					<footer class="ug-graph-footer">
						Une racine par Sales Order
						<span>Glisser pour déplacer · Ctrl + molette pour zoomer</span>
					</footer>
				</section>
				<aside v-if="selected" class="ug-details" aria-label="Détails du nœud sélectionné">
					<div class="ug-detail-heading">
						<h2>Nœud sélectionné</h2>
						<button aria-label="Fermer les détails" @click="selectedId = null">
							×
						</button>
					</div>
					<div class="ug-detail-title">
						<span>◈</span>
						<div>
							<h3>{{ selected.label }}</h3>
							<small>{{
								selected.item_type === "ORDER" ? "Sales Order" : selected.item_type
							}}</small>
							<p>{{ dimensionLabel(selected) }}</p>
						</div>
					</div>
					<p class="ug-detail-reference">{{ selected.sales_order }}</p>
					<p class="ug-state-badge" :class="selected.state">
						{{ selected.state_label }}
					</p>
					<div class="ug-metrics">
						<div>
							<small>Besoin restant</small
							><strong>{{ selected.remaining_qty }}</strong>
						</div>
						<div>
							<small>Stock physique</small
							><strong>{{ selected.physical_qty ?? "—" }}</strong>
						</div>
						<div>
							<small>Fabricable</small
							><strong class="ug-green">{{ selected.fabricable_qty || 0 }}</strong>
						</div>
					</div>
					<dl class="ug-quantities">
						<div>
							<dt>Besoin total</dt>
							<dd>{{ selected.required_qty ?? "—" }}</dd>
						</div>
						<div>
							<dt>Fabriqué conforme attribué</dt>
							<dd>{{ selected.produced_qty || 0 }}</dd>
						</div>
						<div>
							<dt>Stock allouable affecté</dt>
							<dd>{{ selected.allocatable_qty ?? "—" }}</dd>
						</div>
					</dl>
					<template v-if="selected.item_type !== 'STOCK' && !selected.invalid_message"
						><label v-if="selected.item_type !== 'ORDER'" class="ug-quantity"
							>Quantité à traiter<input
								v-model.number="quantity"
								type="number"
								min="1"
								:max="selected.manufacture_qty ?? selected.remaining_qty"
								step="1" /></label
						><button
							class="primary ug-action"
							:disabled="
								acting ||
								busy ||
								stale ||
								(selected.item_type === 'ORDER'
									? selected.manufacture_qty < 1
									: quantity < 1 ||
									  quantity >
											(selected.manufacture_qty ?? selected.remaining_qty))
							"
							@click="prepare"
						>
							{{ acting ? "Préparation…" : actionLabel }}
						</button>
						<p v-if="selected.item_type === 'ORDER'" class="ug-hint">
							Traiter tous les besoins de cette commande. Pour une quantité
							partielle, sélectionnez un ouvrage.
						</p>
						<p class="ug-hint">
							L’action est déterminée par le serveur pour la quantité choisie.
						</p></template
					>
					<p v-if="selected.stock_note" class="ug-hint">{{ selected.stock_note }}</p>
					<h4>
						{{ selected.children?.length ? "Composants principaux" : "Disponibilité" }}
					</h4>
					<div v-for="child in selected.children" :key="child.id" class="ug-component">
						<button @click="select(child)">
							<span :class="child.state">◇</span>{{ child.label }}</button
						><strong :class="child.state"
							>{{ child.allocatable_qty || 0 }} /
							{{ child.remaining_qty || 0 }}</strong
						>
					</div>
					<p v-if="!selected.children?.length" class="ug-hint">
						{{
							selected.requires_mcp
								? "Une découpe est nécessaire. Le MCP sera ouvert en simulation."
								: "Les disponibilités sont partagées entre les commandes et tiennent compte des réservations."
						}}
					</p>
				</aside>
			</div>
			<footer class="ug-legend">
				<strong>Légende :</strong><span><i class="ok"></i>Besoin satisfait</span
				><span><i class="ready"></i>Fabrication disponible</span
				><span><i class="partial"></i>Partiellement réalisable</span
				><span><i class="blocked"></i>Manquant / bloqué</span
				><small>{{ asOf ? "Actualisé : " + asOf.slice(11, 19) : "" }}</small>
			</footer>
		</main>
		<dialog
			ref="dialog"
			class="ug-dialog"
			@cancel.prevent="close"
			@click="
				(e) => {
					if (e.target === dialog) close();
				}
			"
		>
			<template v-if="preview"
				><div class="ug-detail-heading">
					<h2>
						{{
							result
								? "Opération terminée"
								: preview.action === "mcp"
								? "Préparer le MCP"
								: "Confirmer la fabrication"
						}}
					</h2>
					<button :disabled="acting" aria-label="Fermer" @click="close">×</button>
				</div>
				<p>{{ result?.message || preview.message }}</p>
				<p>
					<strong>{{ preview.qty }} unité(s)</strong> · {{ preview.sales_order }}
				</p>
				<template v-if="!result"
					><h4 v-if="preview.tasks.length">
						{{
							preview.action === "mcp"
								? "Assemblages à débloquer"
								: "Assemblages prévus"
						}}
					</h4>
					<ol>
						<li v-for="task in preview.tasks" :key="task.node_id">
							{{ task.label }} — {{ task.qty }} unité(s) →
							{{ task.warehouse || "Entrepôt à configurer" }}
						</li>
					</ol>
					<h4 v-if="preview.shortages.length">Composants manquants</h4>
					<ul>
						<li v-for="(s, i) in preview.shortages" :key="i">
							{{ s.item_code }} : {{ s.qty }}
							{{ s.kind === "cutting" ? "à découper" : "indisponibles" }}
						</li>
					</ul>
					<details v-if="preview.movements.length" open>
						<summary>
							{{
								preview.action === "mcp"
									? "Composants disponibles (aucune consommation)"
									: "Mouvements prévus"
							}}
						</summary>
						<table class="ug-table">
							<thead>
								<tr>
									<th>Composant</th>
									<th>Qté</th>
									<th>Entrepôt / série</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(m, i) in preview.movements" :key="i">
									<td>{{ m.item_code }}</td>
									<td>{{ m.qty }}</td>
									<td>
										{{ m.warehouse
										}}<small>{{ m.serial_no || m.batch_no }}</small>
									</td>
								</tr>
							</tbody>
						</table>
					</details>
					<p v-if="preview.action === 'mcp'" class="ug-hint">
						Aucun assemblage ne sera lancé. Les découpes restent à traiter dans
						l’interface habituelle du MCP.
					</p></template
				>
				<div v-else class="ug-result-links">
 <button v-for="name in result.mcps" :key="'print-mcp-'+name" @click="printDocument('Material Cutting Plan',name)">Imprimer A4 · {{name}}</button>
 <button v-for="name in result.stock_entries" :key="'print-stock-'+name" @click="printDocument('Stock Entry',name)">Imprimer A4 · {{name}}</button>
					<a
						v-for="name in result.mcps"
						:key="name"
						:href="'/app/material-cutting-plan/' + encodeURIComponent(name)"
						>{{ name }} → Ouvrir le MCP</a
					><a
						v-for="name in result.stock_entries"
						:key="name"
						:href="'/app/stock-entry/' + encodeURIComponent(name)"
						>{{ name }} → Stock Entry validée</a
					>
				</div>
				<div class="ug-dialog-actions">
					<button :disabled="acting" @click="close">
						{{ result ? "Fermer" : "Annuler" }}</button
					><button
						v-if="!result"
						class="primary"
						:disabled="acting || preview.action === 'blocked'"
						@click="execute"
					>
						{{
							acting
								? "Exécution…"
								: preview.action === "mcp"
								? "Créer et ouvrir la simulation"
								: "Confirmer les Repack"
						}}
					</button>
				</div>
			</template>
		</dialog>
	</div>
</template>
