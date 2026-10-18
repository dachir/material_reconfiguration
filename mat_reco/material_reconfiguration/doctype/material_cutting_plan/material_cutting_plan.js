// Copyright (c) 2026, Richard Amouzou and contributors
// For license information, please see license.txt

// Client-side script for Material Cutting Plan

//const MCP_UI_BUNDLE = '/assets/mat_reco/js/material_cutting_plan_ui.bundle.js';
//frappe.require(MCP_UI_BUNDLE);

const MCP_INCIDENT_TABLE = 'material_plan_incidents';
const MCP_INCIDENT_ACTIONS = ['Resize', 'Destroy', 'Move', 'Merge', 'Single'];
const MCP_MIN_LEFTOVER_DIMENSION_MM = 500;
const MCP_MODE_PLANIFICATION = 'Planification';
const MCP_MODE_RETOUR_TERRAIN = 'Retour Terrain';

const MCP_VARIANT_TABLE = 'item_variant_detail';
const MCP_STOCK_CANDIDATE_TABLE = 'mcp_stock_candidate';
const MCP_SELECTED_SO_TABLE = 'selected_sales_orders';
const MCP_VARIANT_ITEM_FIELD = 'variant_item_code';

let mcp_ux20_bundle_promise=null;
function load_mcp_ux20_bundle() {
    if(window.MatRecoMCPUX20?.version==='20261014_terrain_rotation_1')return Promise.resolve(window.MatRecoMCPUX20);
    if(mcp_ux20_bundle_promise)return mcp_ux20_bundle_promise;
    mcp_ux20_bundle_promise=new Promise((resolve,reject)=>{
        const script=document.createElement('script');
        script.src='/assets/mat_reco/js/mcp_ux20.bundle.js?ux20_editor=20261014_terrain_rotation_1';
        script.onload=()=>window.MatRecoMCPUX20?.openUX20Modal?resolve(window.MatRecoMCPUX20):reject(new Error('Module UX 2.0 indisponible.'));
        script.onerror=()=>reject(new Error('Bundle UX 2.0 inaccessible.'));
        document.head.appendChild(script);
    }).catch(error=>{mcp_ux20_bundle_promise=null;throw error;});
    return mcp_ux20_bundle_promise;
}

function build_mcp_ui_config() {
    return {
        MCP_INCIDENT_TABLE,
        MCP_INCIDENT_ACTIONS,
        MCP_MIN_LEFTOVER_DIMENSION_MM,
        MCP_MODE_PLANIFICATION,
        MCP_MODE_RETOUR_TERRAIN,
        MCP_STOCK_CANDIDATE_TABLE
    };
}

function get_mcp_ui(callback) {
    const configure = function(ui) {
        if (!ui || typeof ui.configure !== 'function') return null;
        globalThis.MAT_RECO_MCP_UI_CONFIG = Object.assign({}, globalThis.MAT_RECO_MCP_UI_CONFIG || {}, build_mcp_ui_config());
        return ui.configure(build_mcp_ui_config());
    };

    const readyUi = configure(window.MatRecoMCPUI);
    if (readyUi) {
        if (typeof callback === 'function') {
            callback(readyUi);
        }
        return readyUi;
    }

    /*frappe.require(MCP_UI_BUNDLE, function() {
        const loadedUi = configure(window.MatRecoMCPUI);
        if (loadedUi && typeof callback === 'function') {
            callback(loadedUi);
        }
    });
    */

    return null;
}

function with_mcp_ui(methodName, args, errorMessage) {
    const callArgs = Array.isArray(args) ? args : [args];
    return get_mcp_ui(function(ui) {
        if (!ui || typeof ui[methodName] !== 'function') return;
        try {
            ui[methodName].apply(ui, callArgs);
        } catch (e) {
            console.error(errorMessage || '[MCP] UI action failed:', e);
        }
    });
}

function get_mcp_mode(frm) {
    const ui = get_mcp_ui();
    if (ui && typeof ui.get_mcp_mode === 'function') {
        return ui.get_mcp_mode(frm);
    }

    const mode = (frm.doc.mcp_mode || MCP_MODE_PLANIFICATION).trim();
    return [MCP_MODE_PLANIFICATION, MCP_MODE_RETOUR_TERRAIN].includes(mode)
        ? mode
        : MCP_MODE_PLANIFICATION;
}

function get_preview_result_json(frm) {
    if (get_mcp_mode(frm) === MCP_MODE_RETOUR_TERRAIN) {
        return frm.doc.effective_result_json || frm.doc.result_json || frm.doc.result_tree_json || '';
    }
    return frm.doc.result_json || frm.doc.result_tree_json || frm.doc.effective_result_json || '';
}

frappe.ui.form.on('Material Cutting Plan', {
    on_submit(frm) {
        window.MatRecoMCPUX20?.lockUX20Editors?.(frm);
    },

    refresh(frm) {
        window.MatRecoMCPUX20?.lockUX20Editors?.(frm);
        frm.clear_custom_buttons();

        try {
            const variantField = frm.fields_dict[MCP_VARIANT_TABLE];
            const variantGrid = variantField && variantField.grid;
            // Table MultiSelect can exist without an initialized grid.
            // Frappe's set_query(child_field, table_field, ...) assumes get_field is available.
            if (variantGrid && typeof variantGrid.get_field === 'function'
                && variantGrid.get_field(MCP_VARIANT_ITEM_FIELD)) {
                frm.set_query(MCP_VARIANT_ITEM_FIELD, MCP_VARIANT_TABLE, function() {
                    return {
                        filters: {
                            custom_item_types: 'PRIMAIRE'
                        }
                    };
                });
            } else if (!variantField) {
                console.warn('[MCP] Variant table not found on form:', MCP_VARIANT_TABLE);
            }
            // If the Table MultiSelect has no grid yet, leave it untouched;
            // do not break refresh or the MCP cutting-plan UI.
        } catch (e) {
            console.error('[MCP] Failed to set query for variants:', e);
        }

        with_mcp_ui('apply_mcp_mode_ui', [frm], '[MCP] Failed to apply MCP mode UI:');

        if (get_mcp_mode(frm) === MCP_MODE_PLANIFICATION) {
            frm.add_custom_button(__('Select Orders for Source Item'), function() {
                if (!frm.doc.source_item) {
                    frappe.msgprint(__('Please select a Source Item first.'));
                    return;
                }

                frappe.call({
                    method: 'mat_reco.material_reconfiguration.api.get_orders_by_source_item',
                    args: {
                        source_item: frm.doc.source_item,
                        company: frm.doc.company,
                        plan_name: frm.is_new() ? null : frm.doc.name
                    },
                    callback(r) {
                        if (!r.message) return;

                        if (!frm.fields_dict[MCP_SELECTED_SO_TABLE]) {
                            console.warn('[MCP] Sales order table not found on form:', MCP_SELECTED_SO_TABLE);
                            return;
                        }

                        frm.clear_table(MCP_SELECTED_SO_TABLE);

                        $.each(r.message, function(i, so) {
                            const row = frm.add_child(MCP_SELECTED_SO_TABLE);
                            row.sales_order = so.name;
                            if (so.customer) {
                                row.customer = so.customer;
                            }
                        });

                        frm.refresh_field(MCP_SELECTED_SO_TABLE);
                    }
                });
            }, __('Outils'));

            frm.add_custom_button(__('Get Stock'), function() {
                if (!frm.doc.source_item) {
                    frappe.msgprint(__('Please select a Source Item first.'));
                    return;
                }

                if (!frm.fields_dict[MCP_STOCK_CANDIDATE_TABLE]) {
                    frappe.msgprint(__('Stock candidate table field not found on the Material Cutting Plan.'));
                    return;
                }

                const variantRows = frm.doc[MCP_VARIANT_TABLE] || [];

                frappe.call({
                    method: 'mat_reco.material_reconfiguration.api.get_stock_for_mcp',
                    args: {
                        source_item: frm.doc.source_item,
                        source_warehouse: frm.doc.source_warehouse,
                        item_variants: variantRows.map(d => ({
                            variant_item_code: d[MCP_VARIANT_ITEM_FIELD]
                        }))
                    },
                    freeze: true,
                    freeze_message: __('Loading stock candidates...'),
                    callback(r) {
                        frm.__mcp_initial_candidates = r.message || [];
                        frm.clear_table(MCP_STOCK_CANDIDATE_TABLE);

                        (r.message || []).forEach(function(d) {
                            const row = frm.add_child(MCP_STOCK_CANDIDATE_TABLE);
                            row.serial_no = d.serial_no;
                            row.item_code = d.item_code;
                            row.warehouse = d.warehouse;
                            row.material_status = d.material_status;
                            row.length_mm = d.length_mm;
                            row.width_mm = d.width_mm;
                            row.thickness_mm = d.thickness_mm;
                            row.is_qualified = 1;
                        });

                        frm.refresh_field(MCP_STOCK_CANDIDATE_TABLE);
                        with_mcp_ui('select_all_grid_rows', [frm, MCP_STOCK_CANDIDATE_TABLE], '[MCP] Failed to select grid rows:');
                        with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
                        with_mcp_ui('render_cutting_plan_preview', [frm], '[MCP] Preview rendering failed:');
                    }
                });
            }, __('Outils'));
        }

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Repack lié'), () => {
                frappe.set_route('List', 'Stock Entry', {custom_material_cutting_plan: frm.doc.name});
            });
        }
        if (frm.doc.docstatus === 0) frm.add_custom_button(__('Create Draft Repack'), async function() {
            if (!frm.doc.name) {
                frappe.msgprint(__('Please save the Material Cutting Plan first.'));
                return;
            }

            // The preview includes uncommitted incidents; the server does not.
            // Persist Single (and other pending edits) before reading the
            // Material Cutting Plan to create a Stock Entry.
            if (frm.is_dirty()) {
                try {
                    await frm.save();
                } catch (error) {
                    frappe.msgprint(__('The Material Cutting Plan was not saved. No Repack was created.'));
                    return;
                }
                if (frm.is_dirty()) {
                    frappe.msgprint(__('Please save the Material Cutting Plan before generating the Repack.'));
                    return;
                }
            }

            frappe.call({
                method: 'mat_reco.material_reconfiguration.services.repack_draft_service.make_repack_draft',
                args: {
                    material_cutting_plan_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __('Preparing draft Repack Stock Entry...'),
                callback(r) {
                    if (!r.message) return;
                    const doc = frappe.model.sync(r.message)[0];
                    frappe.set_route('Form', doc.doctype, doc.name);
                }
            });
        });

        with_mcp_ui('render_cutting_plan_preview', [frm], '[MCP] Preview rendering failed:');
        with_mcp_ui('apply_variant_colors', [frm], '[MCP] Variant color rendering failed:');
        frm.add_custom_button(__('UX 2.0'), async function() {
            try {
                await load_mcp_ux20_bundle();
                const ns = window.MatRecoMCPUX20;
                if (!ns || typeof ns.openUX20Modal !== 'function') {
                    throw new Error('Module modal UX 2.0 indisponible. Rebuild des assets requis.');
                }
                ns.openUX20Modal(frm);
            } catch (error) {
                console.error('[MCP UX 2.0 Modal]', error);
                frappe.msgprint(String(error.message || error));
            }
        }, __('Interface'));
        // Use the same SVG palette before the first application and afterwards.
        load_mcp_ux20_bundle()
            .then(ns=>ns.initializeUX20Preview(frm))
            .catch(error=>console.warn('[MCP UX 2.0] Preview fallback:',error));
    },

    source_item(frm) {
        if (frm.fields_dict[MCP_VARIANT_TABLE]) {
            frm.clear_table(MCP_VARIANT_TABLE);
            frm.refresh_field(MCP_VARIANT_TABLE);
        }

        if (frm.fields_dict[MCP_STOCK_CANDIDATE_TABLE]) {
            frm.clear_table(MCP_STOCK_CANDIDATE_TABLE);
            frm.refresh_field(MCP_STOCK_CANDIDATE_TABLE);
        }
        frm.__mcp_initial_candidates = [];

        if (!frm.doc.source_item) {
            with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
            return;
        }

        frappe.call({
            method: 'mat_reco.material_reconfiguration.api.get_item_variants_for_mcp',
            args: {
                source_item: frm.doc.source_item
            },
            freeze: true,
            freeze_message: __('Loading item variants...'),
            callback(r) {
                if (!frm.fields_dict[MCP_VARIANT_TABLE]) {
                    console.warn('[MCP] Variant table not found on form:', MCP_VARIANT_TABLE);
                    return;
                }

                frm.clear_table(MCP_VARIANT_TABLE);

                (r.message || []).forEach(function(d) {
                    const row = frm.add_child(MCP_VARIANT_TABLE);
                    row[MCP_VARIANT_ITEM_FIELD] = d.variant_item_code;
                });

                frm.refresh_field(MCP_VARIANT_TABLE);
                with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
            }
        });
    },

    clear_all_variants(frm) {
        if (!frm.fields_dict[MCP_VARIANT_TABLE]) {
            console.warn('[MCP] Variant table not found on form:', MCP_VARIANT_TABLE);
            return;
        }

        frm.clear_table(MCP_VARIANT_TABLE);
        frm.refresh_field(MCP_VARIANT_TABLE);
        with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
    },

    [MCP_VARIANT_TABLE](frm) {
        with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
    },

    [MCP_STOCK_CANDIDATE_TABLE](frm) {
        with_mcp_ui('apply_variant_colors', [frm], '[MCP] Failed to apply variant colors:');
    },

    result_json(frm) {
        with_mcp_ui('render_cutting_plan_preview', [frm], '[MCP] Preview rendering failed:');
    },

    result_tree_json(frm) {
        with_mcp_ui('render_cutting_plan_preview', [frm], '[MCP] Preview rendering failed:');
    },

    material_plan_incidents(frm) {
        with_mcp_ui('render_cutting_plan_preview', [frm], '[MCP] Preview rendering failed:');
    },

    mcp_mode(frm) {
        with_mcp_ui('apply_mcp_mode_ui', [frm], '[MCP] Failed to apply MCP mode UI:');
        frm.refresh();
    }
});

// Copyright (c) 2026, Richard Amouzou and contributors
// For license information, please see license.txt

// Material Cutting Plan UX module
// This file centralizes preview / canvas / incidents / move mode behavior.

(function(global) {
    const DEFAULT_CONFIG = {
        MCP_INCIDENT_TABLE: 'material_plan_incidents',
        MCP_INCIDENT_ACTIONS: ['Resize', 'Destroy', 'Move', 'Merge'],
        MCP_MIN_LEFTOVER_DIMENSION_MM: 500,
        MCP_MODE_PLANIFICATION: 'Planification',
        MCP_MODE_RETOUR_TERRAIN: 'Retour Terrain',
        MCP_STOCK_CANDIDATE_TABLE: 'mcp_stock_candidate'
    };

    const state = {
        config: Object.assign({}, DEFAULT_CONFIG)
    };

    function cfg() {
        const runtimeConfig = global.MAT_RECO_MCP_UI_CONFIG || {};
        return Object.assign({}, DEFAULT_CONFIG, state.config || {}, runtimeConfig);
    }

    function configure(options) {
        state.config = Object.assign({}, state.config || {}, options || {});
        return api;
    }

function get_mcp_mode(frm) {
    // Normalize the MCP mode to handle case and whitespace variations.
    const raw = String(frm.doc.mcp_mode || '').trim().toLowerCase();
    const plan = String(cfg().MCP_MODE_PLANIFICATION || '').trim().toLowerCase();
    const retour = String(cfg().MCP_MODE_RETOUR_TERRAIN || '').trim().toLowerCase();
    if (raw === retour) {
        return cfg().MCP_MODE_RETOUR_TERRAIN;
    }
    // Default to planification when not explicitly retour terrain
    return cfg().MCP_MODE_PLANIFICATION;
}

function set_grid_column_read_only(frm, tableFieldname, columnFieldname, isReadOnly) {
    try {
        const field = frm.fields_dict[tableFieldname];
        const grid = field && field.grid;
        if (!grid || !grid.update_docfield_property) return;
        grid.update_docfield_property(columnFieldname, 'read_only', isReadOnly ? 1 : 0);
    } catch (e) {
        console.error('[MCP] Failed to update grid column property:', tableFieldname, columnFieldname, e);
    }
}

function apply_mcp_mode_ui(frm) {
    const mode = get_mcp_mode(frm);
    const isPlanification = mode === cfg().MCP_MODE_PLANIFICATION;
    const isRetourTerrain = mode === cfg().MCP_MODE_RETOUR_TERRAIN;

    frm.toggle_display(cfg().MCP_INCIDENT_TABLE, isRetourTerrain);

    if (!isRetourTerrain && frm.__mcp_move_state) {
        frm.__mcp_move_state = null;
    }

    set_grid_column_read_only(frm, cfg().MCP_STOCK_CANDIDATE_TABLE, 'is_qualified', !isPlanification);
    set_grid_column_read_only(frm, cfg().MCP_STOCK_CANDIDATE_TABLE, 'is_active_input', !isRetourTerrain);

    frm.refresh_field(cfg().MCP_STOCK_CANDIDATE_TABLE);
    frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
}

function getSalesOrderPalette() {
    return [
        { fill: '#dbeafe', border: '#2563eb', text: '#1e3a8a' },
        { fill: '#dcfce7', border: '#16a34a', text: '#166534' },
        { fill: '#fef3c7', border: '#d97706', text: '#92400e' },
        { fill: '#fce7f3', border: '#db2777', text: '#9d174d' },
        { fill: '#ede9fe', border: '#7c3aed', text: '#5b21b6' },
        { fill: '#fee2e2', border: '#dc2626', text: '#991b1b' },
        { fill: '#cffafe', border: '#0891b2', text: '#164e63' },
        { fill: '#ecfccb', border: '#65a30d', text: '#3f6212' },
        { fill: '#fde68a', border: '#ca8a04', text: '#854d0e' },
        { fill: '#e2e8f0', border: '#475569', text: '#334155' }
    ];
}

function buildVariantColorMap(frm) {
    const palette = getSalesOrderPalette();
    const map = {};
    let idx = 0;

    (frm.doc.item_variant_detail || []).forEach(function(row) {
        const code = row.variant_item_code;
        if (!code || map[code]) return;
        map[code] = palette[idx % palette.length];
        idx++;
    });

    return map;
}

function apply_variant_colors(frm) {
    setTimeout(function() {
        const variantColorMap = buildVariantColorMap(frm);

        // Color rows in item_variant_detail
        const variantGrid = frm.fields_dict.item_variant_detail && frm.fields_dict.item_variant_detail.grid;
        if (variantGrid && variantGrid.grid_rows) {
            variantGrid.grid_rows.forEach(function(gridRow) {
                const row = gridRow.doc || {};
                const color = variantColorMap[row.variant_item_code];
                const $row = $(gridRow.row || gridRow.wrapper);

                if (!$row || !$row.length) return;

                if (color) {
                    $row.css({
                        'background-color': color.fill,
                        'border-left': '4px solid ' + color.border
                    });
                } else {
                    $row.css({
                        'background-color': '',
                        'border-left': ''
                    });
                }
            });
        }

        // Color rows in mcp_stock_candidate
        const stockGrid = frm.fields_dict.mcp_stock_candidate && frm.fields_dict.mcp_stock_candidate.grid;
        if (stockGrid && stockGrid.grid_rows) {
            stockGrid.grid_rows.forEach(function(gridRow) {
                const row = gridRow.doc || {};
                const $row = $(gridRow.row || gridRow.wrapper);

                if (!$row || !$row.length) return;

                if (row.item_code === frm.doc.source_item) {
                    $row.css({
                        'background-color': '',
                        'border-left': '4px solid transparent'
                    });
                    return;
                }

                const color = variantColorMap[row.item_code];
                if (color) {
                    $row.css({
                        'background-color': color.fill,
                        'border-left': '4px solid ' + color.border
                    });
                } else {
                    $row.css({
                        'background-color': '',
                        'border-left': ''
                    });
                }
            });
        }
    }, 80);
}

function select_all_grid_rows(frm, fieldname) {
    setTimeout(function() {
        const field = frm.fields_dict[fieldname];
        if (!field || !field.grid || !field.grid.grid_rows) return;

        field.grid.grid_rows.forEach(function(gridRow) {
            try {
                if (gridRow.select) {
                    gridRow.select(true);
                }
            } catch (e) {
                // ignore UI-only selection failures
            }
        });
    }, 60);
}

function buildSalesOrderColorMap(nodes) {
    const palette = getSalesOrderPalette();
    const uniqueSalesOrders = [];
    const seen = {};

    (nodes || []).forEach(function(node) {
        (node.children || []).forEach(function(child) {
            const so = child.sales_order || 'NO-SO';
            if (child.node_type === 'finished_good' && !seen[so]) {
                seen[so] = true;
                uniqueSalesOrders.push(so);
            }
        });
    });

    const colorMap = {};
    uniqueSalesOrders.forEach(function(so, index) {
        colorMap[so] = palette[index % palette.length];
    });

    return colorMap;
}

function get_active_move_state(frm) {
    return frm.__mcp_move_state || null;
}

function get_active_merge_state(frm) {
    return frm.__mcp_merge_state || null;
}

function clear_merge_state(frm, options) {
    const opts = options || {};
    frm.__mcp_merge_state = null;
    if (!opts.silent) {
        frappe.show_alert({ message: __('Merge mode cancelled.'), indicator: 'orange' });
    }
    render_cutting_plan_preview(frm);
}

function ensure_move_escape_binding(frm) {
    if (frm.__mcp_move_escape_bound) return;
    frm.__mcp_move_escape_bound = true;
    $(document).off('keydown.mcpmove.' + frm.doctype + '.' + frm.docname);
    $(document).on('keydown.mcpmove.' + frm.doctype + '.' + frm.docname, function(event) {
        if (event.key !== 'Escape') return;
        if (!get_active_move_state(frm) && !get_active_merge_state(frm)) return;
        event.preventDefault();
        if (get_active_move_state(frm)) {
            clear_move_state(frm, { silent: false });
        }
        if (get_active_merge_state(frm)) {
            clear_merge_state(frm, { silent: false });
        }
    });
}

function clear_move_state(frm, options) {
    const opts = options || {};
    frm.__mcp_move_state = null;
    if (!opts.silent) {
        frappe.show_alert({ message: __('Move mode cancelled.'), indicator: 'orange' });
    }
    render_cutting_plan_preview(frm);
}

function start_move_mode(frm, nodeData) {
    frm.__mcp_move_state = {
        source_node_id: nodeData.node_id,
        source_serial_no: nodeData.source_serial_no,
        item_code: nodeData.item_code,
        sales_order: nodeData.sales_order,
        length_mm: flt(nodeData.length_mm),
        width_mm: flt(nodeData.width_mm),
        x: flt(nodeData.x),
        y: flt(nodeData.y)
    };
    frappe.show_alert({
        message: __('Move mode active. Go to another serial/tab and click a target position. Double-click or press Esc to cancel.'),
        indicator: 'blue'
    });
    render_cutting_plan_preview(frm);
}
function start_merge_mode(frm, nodeData, action) {
    const selectedAction = action === 'Single' ? 'Single' : 'Merge';
    frm.__mcp_merge_state = {
        action: selectedAction,
        source_serial_no: nodeData.source_serial_no,
        selected_node_ids: [nodeData.node_id],
        selected_nodes: [nodeData]
    };
    frappe.show_alert({
        message: __(selectedAction === 'Single' ? 'Single mode active. Click the second free region on the same serial.' : 'Merge mode active. Click contiguous free zones on the same serial. Double-click or press Esc to cancel.'),
        indicator: 'purple'
    });
    render_cutting_plan_preview(frm);
}

function intervals_overlap(a1, a2, b1, b2) {
    return Math.max(flt(a1), flt(b1)) < Math.min(flt(a2), flt(b2));
}

function are_free_rects_contiguous(a, b) {
    if (!a || !b) return false;
    const ax = flt(a.x || 0), ay = flt(a.y || 0), al = flt(a.length_mm || 0), aw = flt(a.width_mm || 0);
    const bx = flt(b.x || 0), by = flt(b.y || 0), bl = flt(b.length_mm || 0), bw = flt(b.width_mm || 0);
    const horiz = (ax + al === bx || bx + bl === ax) && intervals_overlap(ay, ay + aw, by, by + bw);
    const vert = (ay + aw === by || by + bw === ay) && intervals_overlap(ax, ax + al, bx, bx + bl);
    return horiz || vert;
}

function build_rect_from_node_data(nodeData) {
    return {
        id: nodeData.node_id,
        x: flt(nodeData.x || 0),
        y: flt(nodeData.y || 0),
        length_mm: flt(nodeData.length_mm || 0),
        width_mm: flt(nodeData.width_mm || 0),
        node_type: nodeData.node_type,
        source_serial_no: nodeData.source_serial_no
    };
}

function toggle_merge_selection(frm, nodeData) {
    const state = get_active_merge_state(frm);
    if (!state) return false;
    const isSingle = state.action === 'Single';
    if (!is_free_zone_type(nodeData.node_type)) {
        frappe.msgprint(__(isSingle ? 'Single requires two free regions, including at least one leftover.' : 'Merge is only available for leftover or waste zones.'));
        return true;
    }
    if (String(nodeData.source_serial_no || '') !== String(state.source_serial_no || '')) {
        frappe.msgprint(__('All merged zones must belong to the same serial.'));
        return true;
    }

    const ids = state.selected_node_ids || [];
    const idx = ids.indexOf(nodeData.node_id);
    if (idx >= 0) {
        if (ids.length === 1) {
            clear_merge_state(frm, { silent: false });
            return true;
        }
        state.selected_node_ids.splice(idx, 1);
        state.selected_nodes = (state.selected_nodes || []).filter(function(row) { return row.node_id !== nodeData.node_id; });
        render_cutting_plan_preview(frm);
        return true;
    }

    if (isSingle && state.selected_node_ids.length >= 2) {
        frappe.msgprint(__('Single supports exactly two free regions. Remove a selection before adding another.'));
        return true;
    }
    const candidate = build_rect_from_node_data(nodeData);
    const ok = (state.selected_nodes || []).some(function(row) {
        return are_free_rects_contiguous(candidate, build_rect_from_node_data(row));
    });
    if (!ok) {
        frappe.msgprint(__('Selected zone must be contiguous to the current merge selection.'));
        return true;
    }

    state.selected_node_ids.push(nodeData.node_id);
    state.selected_nodes.push(nodeData);
    render_cutting_plan_preview(frm);
    return true;
}

function build_selected_merge_rectangles(frm) {
    const state = get_active_merge_state(frm);
    return (state && state.selected_nodes) ? state.selected_nodes.map(build_rect_from_node_data) : [];
}

function rect_contains_point(rect, x, y) {
    return x >= flt(rect.x) && x < flt(rect.x) + flt(rect.length_mm) && y >= flt(rect.y) && y < flt(rect.y) + flt(rect.width_mm);
}

function build_occupancy_grid(rects) {
    const xs = []; const ys = [];
    (rects || []).forEach(function(r) {
        xs.push(flt(r.x), flt(r.x) + flt(r.length_mm));
        ys.push(flt(r.y), flt(r.y) + flt(r.width_mm));
    });
    const ux = Array.from(new Set(xs)).sort(function(a,b){return a-b;});
    const uy = Array.from(new Set(ys)).sort(function(a,b){return a-b;});
    const cells = [];
    for (let yi = 0; yi < uy.length - 1; yi++) {
        const row = [];
        for (let xi = 0; xi < ux.length - 1; xi++) {
            const cx = (ux[xi] + ux[xi+1]) / 2;
            const cy = (uy[yi] + uy[yi+1]) / 2;
            const occ = (rects || []).some(function(r){ return rect_contains_point(r, cx, cy); });
            row.push(occ);
        }
        cells.push(row);
    }
    return { xs: ux, ys: uy, cells: cells };
}

function find_largest_rectangle_in_grid(grid) {
    const xs = grid.xs, ys = grid.ys, cells = grid.cells;
    let best = null; let bestArea = 0;
    for (let y1 = 0; y1 < ys.length - 1; y1++) {
        for (let y2 = y1 + 1; y2 < ys.length; y2++) {
            for (let x1 = 0; x1 < xs.length - 1; x1++) {
                for (let x2 = x1 + 1; x2 < xs.length; x2++) {
                    let ok = true;
                    for (let yi = y1; yi < y2 && ok; yi++) {
                        for (let xi = x1; xi < x2; xi++) {
                            if (!cells[yi][xi]) { ok = false; break; }
                        }
                    }
                    if (!ok) continue;
                    const area = (xs[x2] - xs[x1]) * (ys[y2] - ys[y1]);
                    if (area > bestArea) {
                        bestArea = area;
                        best = { x: xs[x1], y: ys[y1], length_mm: xs[x2] - xs[x1], width_mm: ys[y2] - ys[y1] };
                    }
                }
            }
        }
    }
    return best;
}

function build_residual_rectangles_from_grid(grid, mergedRect) {
    const xs = grid.xs, ys = grid.ys, cells = grid.cells.map(function(r){ return r.slice(); });
    for (let yi = 0; yi < ys.length - 1; yi++) {
        for (let xi = 0; xi < xs.length - 1; xi++) {
            const cx = (xs[xi] + xs[xi+1]) / 2;
            const cy = (ys[yi] + ys[yi+1]) / 2;
            if (rect_contains_point(mergedRect, cx, cy)) {
                cells[yi][xi] = false;
            }
        }
    }
    const used = cells.map(function(r){ return r.map(function(){ return false; }); });
    const rects = [];
    for (let yi = 0; yi < ys.length - 1; yi++) {
        for (let xi = 0; xi < xs.length - 1; xi++) {
            if (!cells[yi][xi] || used[yi][xi]) continue;
            let maxWidth = 0;
            while (xi + maxWidth < xs.length - 1 && cells[yi][xi + maxWidth] && !used[yi][xi + maxWidth]) maxWidth++;
            let height = 1;
            let growing = true;
            while (yi + height < ys.length - 1 && growing) {
                for (let k = 0; k < maxWidth; k++) {
                    if (!cells[yi + height][xi + k] || used[yi + height][xi + k]) { growing = false; break; }
                }
                if (growing) height++;
            }
            for (let yj = yi; yj < yi + height; yj++) for (let xj = xi; xj < xi + maxWidth; xj++) used[yj][xj] = true;
            rects.push({ x: xs[xi], y: ys[yi], length_mm: xs[xi + maxWidth] - xs[xi], width_mm: ys[yi + height] - ys[yi] });
        }
    }
    return rects;
}

// Find an exact L-shape: two non-overlapping rectangles whose complement is
// one rectangle in the canonical top-left corner. The server validates again.
function build_single_geometry_js(rects) {
    if (rects.length !== 2 || rects.some(function(r) { return !is_free_zone_type(r.node_type) || r.length_mm <= 0 || r.width_mm <= 0; }) || !rects.some(function(r) { return r.node_type === 'leftover'; })) return null;
    if (rectangles_overlap(rects[0], rects[1])) return null;
    const x = Math.min.apply(null, rects.map(r => r.x));
    const y = Math.min.apply(null, rects.map(r => r.y));
    const maxX = Math.max.apply(null, rects.map(r => r.x + r.length_mm));
    const maxY = Math.max.apply(null, rects.map(r => r.y + r.width_mm));
    const length = maxX - x, width = maxY - y;
    const area = rects.reduce((sum, r) => sum + r.length_mm * r.width_mm, 0);
    const missing = length * width - area;
    if (missing <= 0.001) return null;
    const xs = Array.from(new Set([x, maxX].concat(rects.flatMap(r => [r.x, r.x + r.length_mm])))).sort((a,b) => a-b);
    const ys = Array.from(new Set([y, maxY].concat(rects.flatMap(r => [r.y, r.y + r.width_mm])))).sort((a,b) => a-b);
    for (const hx of xs.slice(1, -1)) {
        for (const hy of ys.slice(1, -1)) {
            const hole = {x, y, length_mm:hx-x, width_mm:hy-y};
            if (rectangles_overlap(rects[0], hole) || rectangles_overlap(rects[1], hole)) continue;
            if (Math.abs(hole.length_mm * hole.width_mm - missing) > 0.001) continue;
            return {x, y, length_mm:length, width_mm:width, removed_length_mm:hole.length_mm, removed_width_mm:hole.width_mm, area_mm2:area};
        }
    }
    return null;
}

function build_single_payload(frm, state, rects) {
    if (rects.length !== 2) return {ok:false, message:__('Select exactly two free rectangles for Single, including one leftover.')};
    const geometry = build_single_geometry_js(rects);
    if (!geometry) return {ok:false, message:__('Single requires an L-shaped leftover with one missing upper-left corner. Use Merge for full rectangles.')};
    return {ok:true, payload:{
        plan_node_id: state.selected_node_ids[0],
        source_serial_no: state.source_serial_no,
        original_node_type: rects[0].node_type,
        incident_action: 'Single',
        affected_node_ids_json: JSON.stringify(state.selected_node_ids),
        group_area_mm2: geometry.area_mm2,
        new_node_type: 'leftover',
        new_length_mm: geometry.length_mm,
        new_width_mm: geometry.width_mm,
        new_area_mm2: geometry.area_mm2,
        target_x_mm: geometry.x,
        target_y_mm: geometry.y,
        include_in_repack: 1,
        is_active: 1,
        remarks: JSON.stringify({removed_length_mm:geometry.removed_length_mm,removed_width_mm:geometry.removed_width_mm})
    }};
}

function build_merge_payload(frm) {
    const state = get_active_merge_state(frm);
    const rects = build_selected_merge_rectangles(frm);
    if (state && state.action === 'Single') return build_single_payload(frm, state, rects);
    if (!state || rects.length < 2) {
        return { ok: false, message: __('Select at least two free zones to merge.') };
    }
    const grid = build_occupancy_grid(rects);
    const merged = find_largest_rectangle_in_grid(grid);
    if (!merged) {
        return { ok: false, message: __('Could not compute a mergeable area from the selection.') };
    }
    const residuals = build_residual_rectangles_from_grid(grid, merged);
    const area = flt(merged.length_mm) * flt(merged.width_mm);
    return {
        ok: true,
        payload: {
            plan_node_id: state.selected_node_ids[0],
            source_serial_no: state.source_serial_no,
            original_node_type: 'leftover',
            original_item_code: '',
            original_length_mm: 0,
            original_width_mm: 0,
            original_area_mm2: 0,
            incident_action: 'Merge',
            affected_node_ids_json: JSON.stringify(state.selected_node_ids),
            group_area_mm2: rects.reduce(function(sum, r){ return sum + flt(r.length_mm) * flt(r.width_mm); }, 0),
            new_node_type: classify_free_zone_type(merged.length_mm, merged.width_mm),
            new_length_mm: merged.length_mm,
            new_width_mm: merged.width_mm,
            new_area_mm2: area,
            target_x_mm: merged.x,
            target_y_mm: merged.y,
            include_in_repack: 1,
            is_active: 1,
            remarks: JSON.stringify({ residual_rects: residuals })
        }
    };
}

function apply_current_merge_selection(frm) {
    const result = build_merge_payload(frm);
    if (!result.ok) {
        frappe.msgprint(result.message || __('Invalid merge selection.'));
        return;
    }
    upsert_incident_row(frm, result.payload);
    frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
    frm.__mcp_merge_state = null;
    frappe.show_alert({ message: __('Selection applied. Save to persist the result.'), indicator: 'green' });
    render_cutting_plan_preview(frm);
}

function rectangles_overlap(a, b) {
    return !(
        flt(a.x) + flt(a.length_mm) <= flt(b.x) ||
        flt(b.x) + flt(b.length_mm) <= flt(a.x) ||
        flt(a.y) + flt(a.width_mm) <= flt(b.y) ||
        flt(b.y) + flt(b.width_mm) <= flt(a.y)
    );
}

function clamp(value, minValue, maxValue) {
    if (maxValue < minValue) {
        return minValue;
    }
    return Math.max(minValue, Math.min(maxValue, value));
}

function child_id_js(child) {
    return String((child && (child.id || child.piece_uid)) || '').trim();
}

/**
 * Normalize a node_type string by trimming whitespace and converting to lower case.
 * This helper ensures that variations like 'Destroy', 'destroyed ' or ' destroy' are all
 * treated consistently when comparing node types.  It should be used wherever
 * comparisons on node_type are made.
 *
 * @param {string} nodeType The raw node_type value from a child node
 * @returns {string} A trimmed, lower‑cased version of the node type
 */
function normalize_node_type(nodeType) {
    return String(nodeType || '').trim().toLowerCase();
}

/**
 * Determine whether a given node_type corresponds to a destroyed region.  Some
 * services may label destroyed pieces as 'destroy' instead of 'destroyed'.
 * This helper considers both variants, and is case‑insensitive, so the rest of
 * the UI code can safely check against a single predicate.
 *
 * @param {string} nodeType The raw node_type value from a child node
 * @returns {boolean} True when the node type represents a destroyed piece
 */
function is_destroy_node_type(nodeType) {
    const t = normalize_node_type(nodeType);
    return t === 'destroyed' || t === 'destroy';
}

function node_serial_js(node) {
    return String((node && (node.serial_no || node.id)) || '').trim();
}

function is_free_zone_type(nodeType) {
    // Normalize the node type to ensure case and whitespace differences are ignored.
    const value = normalize_node_type(nodeType);
    return value === 'leftover' || value === 'waste';
}

function rect_contains_rect(outerRect, innerRect) {
    return (
        flt(innerRect.x) >= flt(outerRect.x) &&
        flt(innerRect.y) >= flt(outerRect.y) &&
        (flt(innerRect.x) + flt(innerRect.length_mm)) <= (flt(outerRect.x) + flt(outerRect.length_mm)) &&
        (flt(innerRect.y) + flt(innerRect.width_mm)) <= (flt(outerRect.y) + flt(outerRect.width_mm))
    );
}

function classify_free_zone_type(lengthMm, widthMm) {
    return Math.min(flt(lengthMm), flt(widthMm)) < flt(cfg().MCP_MIN_LEFTOVER_DIMENSION_MM)
        ? 'waste'
        : 'leftover';
}

function sort_children_js(children) {
    return (children || []).slice().sort(function(a, b) {
        const ay = flt((a && a.y) || 0);
        const by = flt((b && b.y) || 0);
        if (ay !== by) return ay - by;
        const ax = flt((a && a.x) || 0);
        const bx = flt((b && b.x) || 0);
        if (ax !== bx) return ax - bx;
        return child_id_js(a).localeCompare(child_id_js(b));
    });
}

function resolve_target_free_zone(targetNode, candidate, preferredZoneId) {
    const children = (targetNode && targetNode.children) || [];
    let preferred = null;
    const matches = [];

    children.forEach(function(child) {
        if (!is_free_zone_type(child && child.node_type)) {
            return;
        }
        const zoneRect = {
            x: flt((child && child.x) || 0),
            y: flt((child && child.y) || 0),
            length_mm: flt(get_display_length(child) || 0),
            width_mm: flt(get_display_width(child) || 0)
        };
        if (zoneRect.length_mm <= 0 || zoneRect.width_mm <= 0) {
            return;
        }
        if (!rect_contains_rect(zoneRect, candidate)) {
            return;
        }
        const zoneId = child_id_js(child);
        if (preferredZoneId && zoneId === String(preferredZoneId)) {
            preferred = child;
            return;
        }
        matches.push(child);
    });

    if (preferred) {
        return preferred;
    }

    matches.sort(function(a, b) {
        const areaA = flt(get_display_length(a) || 0) * flt(get_display_width(a) || 0);
        const areaB = flt(get_display_length(b) || 0) * flt(get_display_width(b) || 0);
        return areaA - areaB;
    });

    return matches.length ? matches[0] : null;
}

function build_target_move_payload(frm, targetSerialNo, targetX, targetY, options) {
    const opts = options || {};
    const preferredZoneId = opts.targetZoneId || '';
    const moveState = get_active_move_state(frm);
    if (!moveState) {
        return { ok: false, message: __('Move mode is not active.') };
    }

    const targetNode = (frm.__cut_nodes || []).find(function(node) {
        return node_serial_js(node) === String(targetSerialNo || '');
    });
    if (!targetNode) {
        return { ok: false, message: __('Target serial not found in current preview.') };
    }

    const pieceLength = flt(moveState.length_mm);
    const pieceWidth = flt(moveState.width_mm);
    const sheetLength = flt(targetNode.length_mm || targetNode.length || 0);
    const sheetWidth = flt(targetNode.width_mm || targetNode.width || 0);

    if (pieceLength <= 0 || pieceWidth <= 0 || sheetLength <= 0 || sheetWidth <= 0) {
        return { ok: false, message: __('Invalid dimensions for move.') };
    }

    if (targetX < 0 || targetY < 0 || (targetX + pieceLength) > sheetLength || (targetY + pieceWidth) > sheetWidth) {
        return { ok: false, message: __('The selected target position is outside the target serial boundaries.') };
    }

    const candidate = {
        x: flt(targetX),
        y: flt(targetY),
        length_mm: pieceLength,
        width_mm: pieceWidth
    };

    const targetZone = resolve_target_free_zone(targetNode, candidate, preferredZoneId);
    if (!targetZone) {
        return { ok: false, message: __('The selected target position is not fully contained in a free zone.') };
    }

    const targetZoneLength = flt(get_display_length(targetZone) || targetZone.length_mm || 0);
    const targetZoneWidth = flt(get_display_width(targetZone) || targetZone.width_mm || 0);

    // Business rules for move:
    // 1) target < source => impossible
    if (targetZoneLength < pieceLength || targetZoneWidth < pieceWidth) {
        return { ok: false, message: __('Target zone is smaller than source piece.') };
    }

    // 2) target = source => pure swap
    const isExactSwap = flt(targetZoneLength) === flt(pieceLength) && flt(targetZoneWidth) === flt(pieceWidth);
    // 3) target > source => swing with complement zones
    const isLargerTarget = flt(targetZoneLength) > flt(pieceLength) || flt(targetZoneWidth) > flt(pieceWidth);

    // Build the list of occupied zones on the target serial.  A zone is considered
    // occupied if it is a finished good or a destroyed region.  Free zones such
    // as leftovers and wastes are explicitly ignored here so that they can be
    // replaced by the moving finished good.  Additionally, we skip the source
    // node itself to avoid incorrectly flagging the original piece as an
    // obstruction when moving within the same serial.
    const occupied = (targetNode.children || []).filter(function(child) {
        const nodeId = child_id_js(child);
        // Never consider the source piece as an obstacle
        if (nodeId === String(moveState.source_node_id || '')) {
            return false;
        }
        // Normalize the type for consistent comparisons
        const normalizedType = normalize_node_type(child && child.node_type);
        // Free zones (leftover and waste) are allowed to be replaced
        if (is_free_zone_type(normalizedType)) {
            return false;
        }
        // Only finished goods and destroyed pieces block placement
        return normalizedType === 'finished_good' || is_destroy_node_type(normalizedType);
    });

    for (let i = 0; i < occupied.length; i++) {
        const child = occupied[i];
        const rect = {
            x: flt(child.x || 0),
            y: flt(child.y || 0),
            length_mm: flt(get_display_length(child) || 0),
            width_mm: flt(get_display_width(child) || 0)
        };
        if (rect.length_mm <= 0 || rect.width_mm <= 0) {
            continue;
        }
        if (rectangles_overlap(candidate, rect)) {
            return { ok: false, message: __('The selected target position overlaps an existing occupied zone.') };
        }
    }

    return {
        ok: true,
        payload: {
            plan_node_id: moveState.source_node_id,
            source_serial_no: moveState.source_serial_no,
            original_node_type: 'finished_good',
            original_item_code: moveState.item_code,
            original_length_mm: pieceLength,
            original_width_mm: pieceWidth,
            original_area_mm2: pieceLength * pieceWidth,
            incident_action: 'Move',
            affected_node_ids_json: JSON.stringify([moveState.source_node_id]),
            group_area_mm2: pieceLength * pieceWidth,
            new_node_type: 'finished_good',
            new_item_code: moveState.item_code,
            new_length_mm: pieceLength,
            new_width_mm: pieceWidth,
            new_area_mm2: pieceLength * pieceWidth,
            target_serial_no: targetSerialNo,
            target_zone_id: preferredZoneId || '',
            target_x_mm: targetX,
            target_y_mm: targetY,
            move_case: isExactSwap ? 'swap' : (isLargerTarget ? 'swing' : 'swap'),
            include_in_repack: 1,
            is_active: 1,
            remarks: ''
        }
    };
}

function try_finish_move_on_sheet(frm, event, $sheet, $clickedPiece) {
    const moveState = get_active_move_state(frm);
    if (!moveState) return false;

    const offset = $sheet.offset();
    if (!offset) return false;

    const serialNo = $sheet.attr('data-serial-no') || '';
    const scale = flt($sheet.attr('data-scale'));
    if (!serialNo || scale <= 0) return false;

    const rawX = (event.pageX - offset.left) / scale;
    const rawY = (event.pageY - offset.top) / scale;
    const pieceLength = flt(moveState.length_mm);
    const pieceWidth = flt(moveState.width_mm);

    let targetX = Math.max(0, rawX - (pieceLength / 2));
    let targetY = Math.max(0, rawY - (pieceWidth / 2));
    let targetZoneId = '';

    if ($clickedPiece && $clickedPiece.length) {
        const clickedNodeType = String($clickedPiece.attr('data-node-type') || '');
        if (is_free_zone_type(clickedNodeType)) {
            const zoneX = flt($clickedPiece.attr('data-x') || 0);
            const zoneY = flt($clickedPiece.attr('data-y') || 0);
            const zoneLength = flt($clickedPiece.attr('data-display-length') || $clickedPiece.attr('data-length') || 0);
            const zoneWidth = flt($clickedPiece.attr('data-display-width') || $clickedPiece.attr('data-width') || 0);

            targetZoneId = String($clickedPiece.attr('data-node-id') || '').trim();

            if (zoneLength > 0 && zoneWidth > 0) {
                if (pieceLength === zoneLength && pieceWidth === zoneWidth) {
                    targetX = zoneX;
                    targetY = zoneY;
                } else {
                    const minX = zoneX;
                    const maxX = zoneX + zoneLength - pieceLength;
                    const minY = zoneY;
                    const maxY = zoneY + zoneWidth - pieceWidth;
                    targetX = clamp(targetX, minX, maxX);
                    targetY = clamp(targetY, minY, maxY);
                }
            }
        }
    }

    const result = build_target_move_payload(frm, serialNo, targetX, targetY, { targetZoneId: targetZoneId });
    if (!result.ok) {
        frappe.msgprint(result.message || __('Invalid move target.'));
        return true;
    }

    upsert_incident_row(frm, result.payload);
    frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
    frm.__mcp_move_state = null;
    frappe.show_alert({ message: __('Piece moved in preview. Save to persist the new target serial.'), indicator: 'green' });
    render_cutting_plan_preview(frm);
    return true;
}

function render_cutting_plan_preview(frm) {
    ensure_move_escape_binding(frm);

    const previewField = frm.fields_dict.cutting_plan_preview;
    if (!previewField) {
        return;
    }

    const wrapper = previewField.$wrapper;
    wrapper.empty();

    wrapper.css({
        "width": "100%",
        "overflow": "hidden",
        "display": "block",
        "clear": "both"
    });

    const previewCol = frm.fields_dict.cutting_plan_preview.$wrapper.closest('.form-column');
    const summaryCol = frm.fields_dict.plan_summary && frm.fields_dict.plan_summary.$wrapper
        ? frm.fields_dict.plan_summary.$wrapper.closest('.form-column')
        : null;

    if (previewCol.length) {
        previewCol.css({
            "flex": "0 0 75%",
            "max-width": "75%",
            "width": "75%"
        });
    }

    if (summaryCol && summaryCol.length) {
        summaryCol.css({
            "flex": "0 0 25%",
            "max-width": "25%",
            "width": "25%"
        });
    }

    const jsonStr = get_preview_result_json(frm);
    let result;
    if (!jsonStr && (frm.__mcp_initial_candidates || []).length) {
        result = {tree: {nodes: frm.__mcp_initial_candidates.map(function(candidate) {
            const rl = flt(candidate.removed_length_mm || 0);
            const rw = flt(candidate.removed_width_mm || 0);
            return {
                node_type:'input_serial', serial_no:candidate.serial_no,
                length_mm:candidate.length_mm, width_mm:candidate.width_mm,
                area_mm2:candidate.area_mm2,
                children: rl && rw ? [{
                    id:String(candidate.serial_no) + '::PREEXISTING_CUTOUT',
                    node_type:'destroyed', x:0, y:0, length_mm:rl, width_mm:rw,
                    __original_length_mm:rl, __original_width_mm:rw,
                    __preexisting_cutout:1, include_in_repack:0
                }] : []
            };
        })}};
    } else if (!jsonStr) {
        wrapper.html('<p>No cutting plan available.</p>');
        return;
    } else {
        try {
            result = JSON.parse(jsonStr);
        } catch (e) {
            wrapper.html('<p>Invalid cutting plan data.</p>');
            return;
        }
    }

    const tree = result.tree || result;
    const nodes = (tree && tree.nodes) || [];
    if (!nodes.length) {
        wrapper.html('<p>No cutting plan available.</p>');
        return;
    }

    // Always preview incidents in Retour Terrain mode, regardless of resolution status.
    // We filter out 'Move' incidents from preview so that destroy/resize remain functional.
    const isRetour = get_mcp_mode(frm) === cfg().MCP_MODE_RETOUR_TERRAIN;
    const allIncidents = (frm.doc[cfg().MCP_INCIDENT_TABLE] || []);
    const previewIncidents = isRetour ? allIncidents : [];
    frm.__cut_nodes = apply_incidents_to_nodes(nodes, previewIncidents);
    frm.__cut_color_map = buildSalesOrderColorMap(frm.__cut_nodes);

    if (typeof frm.__cut_page === 'undefined') {
        frm.__cut_page = 0;
    }
    if (frm.__cut_page >= frm.__cut_nodes.length) {
        frm.__cut_page = frm.__cut_nodes.length - 1;
    }
    if (frm.__cut_page < 0) {
        frm.__cut_page = 0;
    }

    function updatePreview() {
        const idx = frm.__cut_page;
        const node = frm.__cut_nodes[idx];
        const length_mm = parseFloat(node.length_mm || node.length || 0);
        const width_mm = parseFloat(node.width_mm || node.width || 0);

        if (!length_mm || !width_mm) {
            wrapper.html('<p>Invalid cutting plan data.</p>');
            return;
        }

        const pageWidth = 560;
        const pageHeight = 400;
        const pagePadding = 16;

        const drawingWidth = pageWidth - (pagePadding * 2);
        const drawingHeight = pageHeight - (pagePadding * 2);

        const scale = Math.min(drawingWidth / length_mm, drawingHeight / width_mm);
        const sheetWidthPx = length_mm * scale;
        const sheetHeightPx = width_mm * scale;

        let usedPieceArea = 0;
        (node.children || []).forEach(function(child) {
            if (child.node_type !== 'finished_good') {
                return;
            }
            const cl = parseFloat(child.length_mm || child.length || 0);
            const cw = parseFloat(child.width_mm || child.width || 0);
            usedPieceArea += cl * cw;
        });

        const sheetArea = flt(node.area_mm2 || 0) || length_mm * width_mm;
        const occupancy = sheetArea ? (usedPieceArea / sheetArea) * 100 : 0;

        let html = '';
        const moveState = get_active_move_state(frm);
        const mergeState = get_active_merge_state(frm);
        if (moveState) {
            html += '<div style="margin-bottom:8px; padding:8px 10px; border:1px solid #93c5fd; background:#eff6ff; color:#1d4ed8; border-radius:6px;">';
            html += '<strong>Move mode</strong> — ' + frappe.utils.escape_html(moveState.source_node_id || '') + ' from ' + frappe.utils.escape_html(moveState.source_serial_no || '') + '. ';
            html += 'Click a target position on any serial preview. Double-click or press Esc to cancel.';
            html += '</div>';
        }
        if (mergeState) {
            const selectionAction = mergeState.action === 'Single' ? 'Single' : 'Merge';
            html += '<div style="margin-bottom:8px; padding:8px 10px; border:1px solid #c084fc; background:#faf5ff; color:#7e22ce; border-radius:6px;">';
            html += '<strong>' + selectionAction + ' mode</strong> — Serial ' + frappe.utils.escape_html(mergeState.source_serial_no || '') + '. Selected zones: ' + (mergeState.selected_node_ids || []).length + '. ';
            html += 'Click contiguous zones on the same serial. Double-click or press Esc to cancel.';
            if ((mergeState.selected_node_ids || []).length >= 2) {
                html += ' <button type="button" class="btn btn-xs btn-primary apply-merge-selection" style="margin-left:8px;">Apply ' + selectionAction + '</button>';
            }
            html += '</div>';
        }
        html += '<div style="margin-bottom:5px;">';
        html += '<strong>Serial ' + (idx + 1) + ' / ' + frm.__cut_nodes.length + '</strong> ';
        html += node.serial_no ? node.serial_no + ' ' : '';
        html += '(' + length_mm + ' x ' + width_mm + ') — ';
        const finishedGoodsCount = (node.children || []).filter(function(child) {
            return child.node_type === 'finished_good';
        }).length;
        html += 'Pieces: ' + finishedGoodsCount + ' — ';
        html += 'Utilisation: ' + occupancy.toFixed(1) + '%';
        html += '</div>';

        const legendMap = {};
        (node.children || []).forEach(function(child) {
            if (child.node_type === 'finished_good') {
                const so = child.sales_order || 'NO-SO';
                if (!legendMap[so]) {
                    legendMap[so] = (frm.__cut_color_map && frm.__cut_color_map[so]) || null;
                }
            }
        });

        html += '<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px;">';
        Object.keys(legendMap).forEach(function(so) {
            const c = legendMap[so];
            if (c) {
                html += '<div style="display:flex; align-items:center; gap:6px; font-size:12px;">';
                html += '<span style="display:inline-block; width:14px; height:14px; border:1px solid ' + c.border + '; background:' + c.fill + ';"></span>';
                html += '<span>' + frappe.utils.escape_html(so) + '</span>';
                html += '</div>';
            }
        });
        html += '</div>';

        html += `
            <div style="
                width:100%;
                max-width:${pageWidth}px;
                height:${pageHeight}px;
                border:1px solid #d1d5db;
                background:#ffffff;
                box-shadow:0 1px 4px rgba(0,0,0,0.08);
                margin-bottom:8px;
                display:flex;
                align-items:flex-start;
                justify-content:center;
                overflow:hidden;
                padding:${pagePadding}px;
                box-sizing:border-box;
            ">
                <div class="mcp-sheet-canvas" data-serial-no="${frappe.utils.escape_html(String(node.serial_no || ''))}" data-scale="${scale}" data-sheet-length="${length_mm}" data-sheet-width="${width_mm}" style="
                    position:relative;
                    width:${sheetWidthPx}px;
                    height:${sheetHeightPx}px;
                    border:1px solid #000;
                    background:#f9f9f9;
                    flex:none;
                    cursor:${get_active_move_state(frm) ? 'crosshair' : 'default'};
                ">
        `;

        (node.children || []).forEach(function(child) {
            // Pre-existing cutouts remain in the model for geometry and collision checks,
            // but must not paint over finished goods or the sheet background.
            if (child.__preexisting_cutout) return;
            const displayLength = get_display_length(child);
            const displayWidth = get_display_width(child);
            const cx = parseFloat((child.x || child.x === 0) ? child.x : 0);
            const cy = parseFloat((child.y || child.y === 0) ? child.y : 0);
            const cl = parseFloat(displayLength || 0);
            const cw = parseFloat(displayWidth || 0);
            const px = cx * scale;
            const py = cy * scale;
            const pw = cl * scale;
            const ph = cw * scale;
            const rotationFlag = child.rotation ? 'Rotated' : '';
            const refId = child.plan_ref_id || '';
            const pieceCode = child.piece_item_code || '';
            const so = child.sales_order || 'NO-SO';

            const tip = [];
            if (refId) tip.push('Piece: ' + refId);
            if (pieceCode) tip.push('Item: ' + pieceCode);
            if (cl && cw) tip.push(cl + ' x ' + cw);
            if (rotationFlag) tip.push(rotationFlag);
            if (child.sales_order) tip.push('SO: ' + child.sales_order);
            if (child.root_item_name) tip.push('Root: ' + child.root_item_name);
            if (child.__incident_action) tip.push('Incident: ' + child.__incident_action);
            if (child.__generated_from_resize) tip.push('Generated destroy from resize');

            let style = 'position:absolute; left:' + px + 'px; top:' + py + 'px; width:' + pw + 'px; height:' + ph + 'px; display:flex; align-items:center; justify-content:center; text-align:center; box-sizing:border-box; font-size:10px; cursor:pointer;';
            const moveStateActive = get_active_move_state(frm);
            const isMoveSource = moveStateActive && String(moveStateActive.source_node_id || '') === String(child.id || child.piece_uid || '');
            // Normalize the node type for consistent comparisons
            const normalizedType = normalize_node_type(child.node_type);
            if (normalizedType === 'leftover') {
                if (child.geometry_type === 'single' && flt(child.removed_length_mm) > 0 && flt(child.removed_width_mm) > 0) {
                    const hl = 100 * flt(child.removed_length_mm) / cl;
                    const hw = 100 * flt(child.removed_width_mm) / cw;
                    style += 'clip-path:polygon(' + hl + '% 0,100% 0,100% 100%,0 100%,0 ' + hw + '%,' + hl + '% ' + hw + '%);';
                }
                style += 'border:2px solid #6b7280; background-color:#f3f4f6; background-image:repeating-linear-gradient(45deg,#d1d5db,#d1d5db 6px,#f3f4f6 6px,#f3f4f6 12px); color:#1f2937;';
            } else if (normalizedType === 'waste') {
                style += 'border:2px solid #dc2626; background-color:#fee2e2; background-image:repeating-linear-gradient(45deg,#fca5a5,#fca5a5 6px,#fee2e2 6px,#fee2e2 12px); color:#7f1d1d;';
            } else if (is_destroy_node_type(normalizedType)) {
                style += child.__preexisting_cutout
                    ? 'border:2px solid rgba(185,28,28,0.24); background-color:rgba(220,38,38,0.14); color:rgba(127,29,29,0.65); cursor:default;'
                    : 'border:2px solid #374151; background-color:#4b5563; color:#f8fafc;';
            } else {
                const c = (frm.__cut_color_map && frm.__cut_color_map[so]) || { fill: '#e5e7eb', border: '#6b7280', text: '#111827' };
                style += 'border:1px solid ' + c.border + '; background:' + c.fill + '; color:' + c.text + ';';
            }

            if (isMoveSource) {
                style += 'outline:3px dashed #2563eb; outline-offset:-3px;';
            }
            const mergeStateActive = get_active_merge_state(frm);
            const isMergeSelected = mergeStateActive && (mergeStateActive.selected_node_ids || []).indexOf(String(child.id || child.piece_uid || '')) >= 0;
            if (isMergeSelected) {
                style += 'outline:3px dashed #7e22ce; outline-offset:-3px;';
            }

            let dataAttrs = '';
            dataAttrs += ' data-node-id="' + frappe.utils.escape_html(String(child.id || child.piece_uid || '')) + '"';
            dataAttrs += ' data-node-type="' + frappe.utils.escape_html(String(child.node_type || '')) + '"';
            dataAttrs += ' data-preexisting-cutout="' + (child.__preexisting_cutout ? '1' : '0') + '"';
            dataAttrs += ' data-source-serial="' + frappe.utils.escape_html(String(node.serial_no || '')) + '"';
            dataAttrs += ' data-length="' + frappe.utils.escape_html(String(child.length_mm || 0)) + '"';
            dataAttrs += ' data-width="' + frappe.utils.escape_html(String(child.width_mm || 0)) + '"';
            dataAttrs += ' data-display-length="' + frappe.utils.escape_html(String(displayLength || 0)) + '"';
            dataAttrs += ' data-display-width="' + frappe.utils.escape_html(String(displayWidth || 0)) + '"';
            dataAttrs += ' data-piece-item-code="' + frappe.utils.escape_html(String(child.piece_item_code || child.item_code || '')) + '"';
            dataAttrs += ' data-root-item-code="' + frappe.utils.escape_html(String(child.root_item_code || '')) + '"';
            dataAttrs += ' data-sales-order="' + frappe.utils.escape_html(String(child.sales_order || '')) + '"';
            dataAttrs += ' data-x="' + frappe.utils.escape_html(String(child.x || 0)) + '"';
            dataAttrs += ' data-y="' + frappe.utils.escape_html(String(child.y || 0)) + '"';

            const tooltip = tip.join('\n');
            html += '<div class="cut-piece" ' + dataAttrs + ' title="' + frappe.utils.escape_html(tooltip) + '" style="' + style + '">';

            let content = '';
            if (child.node_type === 'finished_good') {
                if (refId) {
                    content += '<div>' + frappe.utils.escape_html(refId) + '</div>';
                }
                if (pieceCode) {
                    content += '<div>' + frappe.utils.escape_html(pieceCode) + '</div>';
                }
            } else if (is_destroy_node_type(child.node_type)) {
                content += '<div>D</div>';
                content += '<div>' + cl + ' x ' + cw + '</div>';
            } else {
                // Determine the label based on normalized type: L for leftover, W otherwise
                const normTypeForLabel = normalize_node_type(child.node_type);
                const label = normTypeForLabel === 'leftover' ? 'L' : 'W';
                content += '<div>' + frappe.utils.escape_html(label) + '</div>';
                content += '<div>' + cl + ' x ' + cw + '</div>';
            }
            html += content;
            html += '</div>';
        });

        html += '</div></div>';
        html += '<div style="display:flex; align-items:center; gap:10px; margin-top:8px; margin-bottom:12px;">';
        const prevDisabled = frm.__cut_page <= 0 ? 'disabled' : '';
        const nextDisabled = frm.__cut_page >= frm.__cut_nodes.length - 1 ? 'disabled' : '';
        html += '<button type="button" class="btn btn-default cut-prev" ' + prevDisabled + '>Previous</button>';
        html += '<button type="button" class="btn btn-default cut-next" ' + nextDisabled + '>Next</button>';
        html += '</div>';

        wrapper.html(html);

        wrapper.find('.cut-prev').on('click', function() {
            if (frm.__cut_page > 0) {
                frm.__cut_page--;
                updatePreview();
            }
        });
        wrapper.find('.cut-next').on('click', function() {
            if (frm.__cut_page < frm.__cut_nodes.length - 1) {
                frm.__cut_page++;
                updatePreview();
            }
        });
        wrapper.find('.cut-piece').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const $piece = $(this);
            if ($piece.attr('data-preexisting-cutout') === '1') return;
            if (get_active_move_state(frm)) {
                try_finish_move_on_sheet(frm, e, $piece.closest('.mcp-sheet-canvas'), $piece);
                return;
            }
            if (get_active_merge_state(frm)) {
                toggle_merge_selection(frm, extract_node_data($piece));
                return;
            }
            on_cut_piece_click(frm, $piece);
        });
        wrapper.find('.mcp-sheet-canvas').on('click', function(e) {
            if (!get_active_move_state(frm)) {
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            try_finish_move_on_sheet(frm, e, $(this), null);
        });
        wrapper.find('.apply-merge-selection').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            apply_current_merge_selection(frm);
        });
        wrapper.off('dblclick.mcpmove').on('dblclick.mcpmove', function() {
            if (get_active_move_state(frm)) {
                clear_move_state(frm, { silent: false });
            }
            if (get_active_merge_state(frm)) {
                clear_merge_state(frm, { silent: false });
            }
        });
    }

    updatePreview();

    // === RENDER SUMMARY ===
    function renderSummary() {
        const summaryField = frm.fields_dict.plan_summary;
        if (!summaryField) return;

        const wrapper = summaryField.$wrapper;
        wrapper.empty();

        if (!frm.doc.summary_json) {
            wrapper.html('<p>No summary available.</p>');
            return;
        }

        let summary;
        try {
            summary = JSON.parse(frm.doc.summary_json);
        } catch (e) {
            wrapper.html('<p>Invalid summary data.</p>');
            return;
        }

        function fmt(v) {
            return (v || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
        }

        let html = `
            <div style="
                padding:12px;
                background:#ffffff;
                border:1px solid #e5e7eb;
                border-radius:6px;
                width:100%;
                box-sizing:border-box;
            ">

                <h4 style="margin-bottom:12px;">Summary</h4>

                <div style="
                    display:grid;
                    grid-template-columns: 1fr auto;
                    row-gap:8px;
                    column-gap:10px;
                    font-size:13px;
                    align-items:center;
                ">

                    <div><strong>Requested</strong></div>
                    <div>${fmt(summary.requested_piece_count)}</div>

                    <div><strong>Planned</strong></div>
                    <div>${fmt(summary.planned_piece_count)}</div>

                    <div><strong>Missing</strong></div>
                    <div style="color:${summary.missing_piece_count > 0 ? '#dc2626' : '#16a34a'};">
                        ${fmt(summary.missing_piece_count)}
                    </div>

                    <div style="grid-column:1 / -1;"><hr></div>

                    <div><strong>Input Serials</strong></div>
                    <div>${fmt(summary.used_input_serial_count)}</div>

                    <div><strong>Leftovers</strong></div>
                    <div>${fmt(summary.leftover_count)}</div>

                    <div style="grid-column:1 / -1;"><hr></div>

                    <div><strong>Required Area</strong></div>
                    <div>${fmt(summary.total_required_area_m2)} m²</div>

                    <div><strong>Used Area</strong></div>
                    <div>${fmt(summary.total_used_input_area_m2)} m²</div>

                    <div><strong>Leftover</strong></div>
                    <div>${fmt(summary.total_leftover_area_m2)} m²</div>

                    <div><strong>Waste</strong></div>
                    <div>${fmt(summary.total_waste_area_m2)} m²</div>

                </div>
            </div>
            `;

        wrapper.html(html);
    }
    renderSummary();
}

function on_cut_piece_click(frm, $piece) {
    if (get_mcp_mode(frm) !== cfg().MCP_MODE_RETOUR_TERRAIN) {
        frappe.msgprint(__('Incidents are only available in Retour Terrain mode.'));
        return;
    }
    if (frm.doc.docstatus !== 0) {
        frappe.msgprint(__('Incidents can only be added or modified when the plan is in Draft status.'));
        return;
    }
    let parsedResult = null;
    try {
        parsedResult = JSON.parse(get_preview_result_json(frm) || '{}');
    } catch (e) {
        parsedResult = null;
    }
    const resolvedTree = parsedResult ? (parsedResult.tree || parsedResult) : {};
    const treeAlreadyResolved = cint(resolvedTree.return_terrain_resolved || ((resolvedTree.options || {}).return_terrain_resolved) || 0) === 1;
    /*if (treeAlreadyResolved) {
        frappe.msgprint(__('This Retour Terrain plan is already resolved. Clear or adjust incidents, then regenerate from the base plan if you want a fresh recalculation.'));
        return;
    }*/

    const nodeData = extract_node_data($piece);
    const existingIncident = find_incident_row(frm, nodeData.node_id);

    const d = new frappe.ui.Dialog({
        title: __('Action on Piece'),
        fields: [
            {
                fieldname: 'incident_action',
                fieldtype: 'Select',
                label: __('Action'),
                options: cfg().MCP_INCIDENT_ACTIONS.join('\n'),
                reqd: 1,
                default: existingIncident ? existingIncident.incident_action : 'Resize'
            },
            {
                fieldname: 'new_length_mm',
                fieldtype: 'Float',
                label: __('New Length (mm)'),
                default: existingIncident ? flt(existingIncident.new_length_mm) : flt(nodeData.length_mm),
                depends_on: 'eval:doc.incident_action==="Resize"'
            },
            {
                fieldname: 'new_width_mm',
                fieldtype: 'Float',
                label: __('New Width (mm)'),
                default: existingIncident ? flt(existingIncident.new_width_mm) : flt(nodeData.width_mm),
                depends_on: 'eval:doc.incident_action==="Resize"'
            },
            {
                fieldname: 'remarks',
                fieldtype: 'Small Text',
                label: __('Remarks'),
                default: existingIncident ? (existingIncident.remarks || '') : ''
            }
        ],
        primary_action_label: __('Apply'),
        primary_action(values) {
            if (values.incident_action === 'Move') {
                if (nodeData.node_type !== 'finished_good') {
                    frappe.msgprint(__('Move is only available for finished goods.'));
                    return;
                }
                d.hide();
                start_move_mode(frm, nodeData);
                return;
            }
            if (values.incident_action === 'Single') {
                if (!is_free_zone_type(nodeData.node_type)) {
                    frappe.msgprint(__('Single is only available for leftover or waste zones.'));
                    return;
                }
                d.hide();
                start_merge_mode(frm, nodeData, 'Single');
                return;
            }
            if (values.incident_action === 'Merge') {
                if (!is_free_zone_type(nodeData.node_type)) {
                    frappe.msgprint(__('Merge is only available for leftover or waste zones.'));
                    return;
                }
                d.hide();
                start_merge_mode(frm, nodeData);
                return;
            }

            const result = build_incident_payload(frm, nodeData, values);
            if (!result.ok) {
                frappe.msgprint(result.message || __('Invalid incident.'));
                return;
            }
            upsert_incident_row(frm, result.payload);
            d.hide();
            frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
            render_cutting_plan_preview(frm);
        }
    });

    d.show();
}

function build_incident_payload(frm, nodeData, values) {
    const action = values.incident_action;
    const groupNodeIds = [nodeData.node_id];
    const originalArea = flt(nodeData.length_mm) * flt(nodeData.width_mm);
    let newLength = flt(values.new_length_mm);
    let newWidth = flt(values.new_width_mm);
    let newArea = 0;
    let newNodeType = nodeData.node_type;
    let includeInRepack = 1;

    if (action === 'Move') {
        return [clone_child(child)];
    }
    if (action === 'Merge') {
        return [clone_child(child)];
    }
    if (action === 'Merge') {
        return { ok: false, message: __('Use Merge mode to select contiguous free zones on the same serial.') };
    }

    if (action === 'Destroy') {
        newLength = 0;
        newWidth = 0;
        newArea = 0;
        newNodeType = 'destroyed';
        includeInRepack = 0;
    } else {
        if (newLength <= 0 || newWidth <= 0) {
            return { ok: false, message: __('Length and Width must be greater than zero.') };
        }
        newArea = newLength * newWidth;
        if (newArea > originalArea) {
            return { ok: false, message: __('The new area cannot exceed the original area for this first version.') };
        }
        newNodeType = Math.min(newLength, newWidth) < cfg().MCP_MIN_LEFTOVER_DIMENSION_MM ? 'waste' : 'leftover';
        includeInRepack = 1;
    }

    return {
        ok: true,
        payload: {
            plan_node_id: nodeData.node_id,
            source_serial_no: nodeData.source_serial_no,
            original_node_type: nodeData.node_type,
            original_item_code: nodeData.item_code,
            original_length_mm: flt(nodeData.length_mm),
            original_width_mm: flt(nodeData.width_mm),
            original_area_mm2: originalArea,
            incident_action: action,
            affected_node_ids_json: JSON.stringify(groupNodeIds),
            group_area_mm2: originalArea,
            new_node_type: newNodeType,
            new_item_code: nodeData.item_code,
            new_length_mm: newLength,
            new_width_mm: newWidth,
            new_area_mm2: newArea,
            include_in_repack: includeInRepack,
            is_active: 1,
            remarks: values.remarks || ''
        }
    };
}

function extract_node_data($piece) {
    return {
        node_id: $piece.attr('data-node-id') || '',
        node_type: $piece.attr('data-node-type') || '',
        source_serial_no: $piece.attr('data-source-serial') || '',
        item_code: $piece.attr('data-piece-item-code') || $piece.attr('data-root-item-code') || '',
        length_mm: flt($piece.attr('data-length')),
        width_mm: flt($piece.attr('data-width')),
        display_length_mm: flt($piece.attr('data-display-length')),
        display_width_mm: flt($piece.attr('data-display-width')),
        x: flt($piece.attr('data-x')),
        y: flt($piece.attr('data-y')),
        sales_order: $piece.attr('data-sales-order') || ''
    };
}

function find_incident_row(frm, planNodeId) {
    const rows = frm.doc[cfg().MCP_INCIDENT_TABLE] || [];
    for (let i = 0; i < rows.length; i++) {
        if ((rows[i].plan_node_id || '') === planNodeId && cint(rows[i].is_active || 0) === 1) {
            return rows[i];
        }
    }
    return null;
}

function upsert_incident_row(frm, payload) {
    let row = find_incident_row(frm, payload.plan_node_id);
    if (!row) {
        row = frm.add_child(cfg().MCP_INCIDENT_TABLE);
    }
    Object.keys(payload).forEach(function(key) {
        row[key] = payload[key];
    });
}

function clone_child(child) {
    return Object.assign({}, child);
}

function apply_destroy_to_child_js(child) {
    const out = clone_child(child);
    out.node_type = 'destroyed';
    out.__incident_action = 'Destroy';
    out.__original_length_mm = flt(child.length_mm || 0);
    out.__original_width_mm = flt(child.width_mm || 0);

    // Keep visual footprint through display helpers,
    // but make the logical dimensions zero for "destroyed"
    out.length_mm = 0;
    out.width_mm = 0;

    return out;
}

function build_destroy_regions_from_resize_js(child, keptLength, keptWidth) {
    const originalLength = flt(child.length_mm || 0);
    const originalWidth = flt(child.width_mm || 0);
    const x = flt(child.x || 0);
    const y = flt(child.y || 0);

    const destroys = [];

    if (keptLength >= originalLength && keptWidth >= originalWidth) {
        return destroys;
    }

    const rightWidth = originalLength - keptLength;
    if (rightWidth > 0) {
        const destroyRight = clone_child(child);
        destroyRight.node_type = 'destroyed';
        destroyRight.__generated_from_resize = 1;
        destroyRight.__destroy_region_kind = 'right_strip';
        destroyRight.__incident_action = 'Resize';

        destroyRight.x = x + keptLength;
        destroyRight.y = y;
        destroyRight.length_mm = rightWidth;
        destroyRight.width_mm = originalWidth;

        // IMPORTANT: preview must show exact destroy dimensions
        destroyRight.__original_length_mm = rightWidth;
        destroyRight.__original_width_mm = originalWidth;

        destroyRight.__kept_length_mm = keptLength;
        destroyRight.__kept_width_mm = keptWidth;

        destroys.push(destroyRight);
    }

    const bottomHeight = originalWidth - keptWidth;
    if (bottomHeight > 0) {
        const destroyBottom = clone_child(child);
        destroyBottom.node_type = 'destroyed';
        destroyBottom.__generated_from_resize = 1;
        destroyBottom.__destroy_region_kind = 'bottom_strip';
        destroyBottom.__incident_action = 'Resize';

        destroyBottom.x = x;
        destroyBottom.y = y + keptWidth;
        destroyBottom.length_mm = keptLength;
        destroyBottom.width_mm = bottomHeight;

        // IMPORTANT: preview must show exact destroy dimensions
        destroyBottom.__original_length_mm = keptLength;
        destroyBottom.__original_width_mm = bottomHeight;

        destroyBottom.__kept_length_mm = keptLength;
        destroyBottom.__kept_width_mm = keptWidth;

        destroys.push(destroyBottom);
    }

    return destroys;
}

function apply_resize_to_child_as_nodes_js(child, incident) {
    const originalLength = flt(child.length_mm || 0);
    const originalWidth = flt(child.width_mm || 0);

    const newLength = flt(incident.new_length_mm || 0);
    const newWidth = flt(incident.new_width_mm || 0);
    const newType = (incident.new_node_type || child.node_type || '').trim();

    if (newLength <= 0 || newWidth <= 0) {
        return [clone_child(child)];
    }

    if (newLength > originalLength || newWidth > originalWidth) {
        return [clone_child(child)];
    }

    // 1) modified / kept part
    const modified = clone_child(child);
    modified.__incident_action = 'Resize';
    modified.__incident_name = incident.name;
    modified.__original_length_mm = originalLength;
    modified.__original_width_mm = originalWidth;
    modified.node_type = newType || modified.node_type;
    modified.length_mm = newLength;
    modified.width_mm = newWidth;

    // 2) exact destroy complements
    const generatedDestroys = build_destroy_regions_from_resize_js(
        child,
        newLength,
        newWidth
    );

    const results = [modified];
    generatedDestroys.forEach(function(d) {
        results.push(d);
    });

    return results;
}

function apply_incident_to_child_as_nodes_js(child, incident) {
    if (!incident) {
        return [clone_child(child)];
    }

    const action = (incident.incident_action || '').trim();

    if (action === 'Move') {
        return [clone_child(child)];
    }
    if (action === 'Merge') {
        return [clone_child(child)];
    }
    if (action === 'Merge') {
        return { ok: false, message: __('Use Merge mode to select contiguous free zones on the same serial.') };
    }

    if (action === 'Destroy') {
        return [apply_destroy_to_child_js(child)];
    }

    if (action === 'Resize') {
        return apply_resize_to_child_as_nodes_js(child, incident);
    }

    return [clone_child(child)];
}

function build_free_zone_from_rect_js(templateChild, x, y, lengthMm, widthMm, suffix) {
    const l = flt(lengthMm || 0);
    const w = flt(widthMm || 0);
    if (l <= 0 || w <= 0) {
        return null;
    }

    const out = clone_child(templateChild || {});
    const baseId = child_id_js(templateChild) || 'zone';
    out.id = suffix ? (baseId + suffix) : baseId;
    out.node_type = classify_free_zone_type(l, w);
    out.x = flt(x || 0);
    out.y = flt(y || 0);
    out.length_mm = l;
    out.width_mm = w;
    out.__incident_action = 'Move';
    out.__generated_from_move = 1;
    out.__original_length_mm = l;
    out.__original_width_mm = w;
    out.include_in_repack = 1;
    return out;
}

function build_free_zone_from_child_js(child, suffix) {
    return build_free_zone_from_rect_js(
        child,
        flt(child.x || 0),
        flt(child.y || 0),
        flt(child.length_mm || 0),
        flt(child.width_mm || 0),
        suffix || '__freed'
    );
}

function build_target_zone_complements_js(targetZone, candidate) {
    const zoneX = flt(targetZone.x || 0);
    const zoneY = flt(targetZone.y || 0);
    const zoneL = flt(get_display_length(targetZone) || targetZone.length_mm || 0);
    const zoneW = flt(get_display_width(targetZone) || targetZone.width_mm || 0);
    const candX = flt(candidate.x || 0);
    const candY = flt(candidate.y || 0);
    const candL = flt(candidate.length_mm || 0);
    const candW = flt(candidate.width_mm || 0);

    const rows = [];
    const left = build_free_zone_from_rect_js(targetZone, zoneX, zoneY, candX - zoneX, zoneW, '__move_left');
    if (left) rows.push(left);
    const right = build_free_zone_from_rect_js(targetZone, candX + candL, zoneY, (zoneX + zoneL) - (candX + candL), zoneW, '__move_right');
    if (right) rows.push(right);
    const top = build_free_zone_from_rect_js(targetZone, candX, zoneY, candL, candY - zoneY, '__move_top');
    if (top) rows.push(top);
    const bottom = build_free_zone_from_rect_js(targetZone, candX, candY + candW, candL, (zoneY + zoneW) - (candY + candW), '__move_bottom');
    if (bottom) rows.push(bottom);
    return rows;
}

function build_rectangles_from_merge_residuals(templateChild, residualRects) {
    return (residualRects || []).map(function(rect, idx) {
        const row = build_free_zone_from_rect_js(templateChild, rect.x, rect.y, rect.length_mm, rect.width_mm, '__merge_residual_' + idx);
        return row;
    }).filter(Boolean);
}

function build_single_output_children_js(templateChild, incident) {
    const meta = (() => { try { return JSON.parse(incident.remarks || '{}'); } catch(e) { return {}; } })();
    const out = clone_child(templateChild);
    out.id = child_id_js(templateChild) + '__single';
    delete out.piece_uid;
    out.node_type = 'leftover';
    out.geometry_type = 'single';
    out.x = flt(incident.target_x_mm || 0);
    out.y = flt(incident.target_y_mm || 0);
    out.length_mm = flt(incident.new_length_mm || 0);
    out.width_mm = flt(incident.new_width_mm || 0);
    out.removed_length_mm = flt(meta.removed_length_mm || 0);
    out.removed_width_mm = flt(meta.removed_width_mm || 0);
    out.area_mm2 = flt(incident.new_area_mm2 || 0);
    out.effective_length_mm = out.length_mm;
    out.effective_width_mm = out.width_mm;
    out.effective_area_mm2 = out.area_mm2;
    out.include_in_repack = 1;
    out.__incident_action = 'Single';
    return [out];
}

function build_merge_output_children(templateChild, incident) {
    const merged = build_free_zone_from_rect_js(
        templateChild,
        flt(incident.target_x_mm || 0),
        flt(incident.target_y_mm || 0),
        flt(incident.new_length_mm || 0),
        flt(incident.new_width_mm || 0),
        '__merged'
    );
    if (merged) {
        merged.node_type = incident.new_node_type || merged.node_type;
        merged.__incident_action = 'Merge';
    }
    let residuals = [];
    try {
        const parsed = incident.remarks ? JSON.parse(incident.remarks) : {};
        residuals = (parsed && parsed.residual_rects) || [];
    } catch (e) {
        residuals = [];
    }
    const rows = [];
    if (merged) rows.push(merged);
    build_rectangles_from_merge_residuals(templateChild, residuals).forEach(function(row) {
        row.__incident_action = 'Merge';
        rows.push(row);
    });
    return rows;
}

function apply_incidents_to_nodes(nodes, incidents) {
    const incidentMap = build_incident_map(incidents || []);
    const sourceMoveIds = {};
    const mergeConsumedIds = {};
    const processedMergeKeys = {};
    const consumedTargetZonesBySerial = {};
    const additionsBySerial = {};
    const originalNodeBySerial = {};

    (nodes || []).forEach(function(node) {
        originalNodeBySerial[node_serial_js(node)] = node;
    });

    (nodes || []).forEach(function(node) {
        const sourceSerial = node_serial_js(node);
        (node.children || []).forEach(function(child) {
            const childId = child_id_js(child);
            const incident = incidentMap[childId];
            const action = String((incident && incident.incident_action) || '').trim();
            if (action === 'Merge' || action === 'Single') {
                const mergeKey = action + ':' + String((incident && incident.name) || (incident && incident.plan_node_id) || childId);
                const targetSerial = String((incident && incident.source_serial_no) || sourceSerial).trim() || sourceSerial;
                let affectedIds = [];
                try { affectedIds = JSON.parse((incident && incident.affected_node_ids_json) || '[]') || []; } catch (e) { affectedIds = []; }
                if (affectedIds.indexOf(childId) >= 0) {
                    mergeConsumedIds[targetSerial] = mergeConsumedIds[targetSerial] || {};
                    mergeConsumedIds[targetSerial][childId] = true;
                }
                if (!processedMergeKeys[mergeKey]) {
                    processedMergeKeys[mergeKey] = true;
                    additionsBySerial[targetSerial] = additionsBySerial[targetSerial] || [];
                    const additions = action === 'Single' ? build_single_output_children_js(child, incident) : build_merge_output_children(child, incident);
                    additions.forEach(function(row) { additionsBySerial[targetSerial].push(row); });
                }
                return;
            }
            if (action !== 'Move' || String((child && child.node_type) || '').trim() !== 'finished_good') {
                return;
            }

            sourceMoveIds[childId] = true;
            additionsBySerial[sourceSerial] = additionsBySerial[sourceSerial] || [];

            // Determine the target serial. Default to source serial when none provided
            const targetSerial = String((incident && incident.target_serial_no) || sourceSerial).trim() || sourceSerial;
            // Resolve the proposed coordinates for the move.  If not specified on the
            // incident the current child coordinates are used.
            const targetX = (incident && incident.target_x_mm) != null ? incident.target_x_mm : (child.x || 0);
            const targetY = (incident && incident.target_y_mm) != null ? incident.target_y_mm : (child.y || 0);

            // Only free the source zone when the move actually places the piece in a
            // different location.  When the target serial and coordinates match the
            // original, freeing would produce a leftover overlapping the moved piece.
            const sameSpot = (targetSerial === sourceSerial) && (flt(targetX) === flt(child.x || 0)) && (flt(targetY) === flt(child.y || 0));
            if (!sameSpot) {
                const freedZone = build_free_zone_from_child_js(child, '__freed');
                if (freedZone) {
                    additionsBySerial[sourceSerial].push(freedZone);
                }
            }

            const targetNode = originalNodeBySerial[targetSerial];
            // Build the moved child at the new location
            const movedChild = clone_child(child);
            movedChild.x = flt(targetX);
            movedChild.y = flt(targetY);
            movedChild.source_serial_no = targetSerial;
            movedChild.__incident_action = 'Move';
            movedChild.__moved_from_serial_no = sourceSerial;
            movedChild.__moved_to_serial_no = targetSerial;

            additionsBySerial[targetSerial] = additionsBySerial[targetSerial] || [];
            additionsBySerial[targetSerial].push(movedChild);

            if (!targetNode) {
                return;
            }

            const candidate = {
                x: flt(movedChild.x || 0),
                y: flt(movedChild.y || 0),
                length_mm: flt(movedChild.length_mm || 0),
                width_mm: flt(movedChild.width_mm || 0)
            };
            const targetZone = resolve_target_free_zone(targetNode, candidate, String((incident && incident.target_zone_id) || ''));
            if (!targetZone) {
                return;
            }

            consumedTargetZonesBySerial[targetSerial] = consumedTargetZonesBySerial[targetSerial] || {};
            consumedTargetZonesBySerial[targetSerial][child_id_js(targetZone)] = true;
            build_target_zone_complements_js(targetZone, candidate).forEach(function(zone) {
                additionsBySerial[targetSerial].push(zone);
            });
        });
    });

    return (nodes || []).map(function(node) {
        const nodeClone = Object.assign({}, node);
        const serial = node_serial_js(node);
        const newChildren = [];

        (node.children || []).forEach(function(child) {
            const childClone = Object.assign({}, child);
            const childId = child_id_js(childClone);
            const incident = incidentMap[childId];
            const action = String((incident && incident.incident_action) || '').trim();

            if (sourceMoveIds[childId]) {
                return;
            }
            if ((mergeConsumedIds[serial] || {})[childId]) {
                return;
            }
            if ((consumedTargetZonesBySerial[serial] || {})[childId]) {
                return;
            }

            const effectiveChildren = apply_incident_to_child_as_nodes_js(childClone, action === 'Move' ? null : incident);
            if (Array.isArray(effectiveChildren)) {
                effectiveChildren.forEach(function(effectiveChild) {
                    newChildren.push(effectiveChild);
                });
            }
        });

        (additionsBySerial[serial] || []).forEach(function(extraChild) {
            newChildren.push(extraChild);
        });

        nodeClone.children = sort_children_js(newChildren);
        return nodeClone;
    });
}

function build_incident_map(incidents) {
    const map = {};
    (incidents || []).forEach(function(row) {
        if (!row || cint(row.is_active || 0) !== 1) {
            return;
        }
        const action = String((row.incident_action) || '').trim();
        if (action === 'Merge' || action === 'Single') {
            let ids = [];
            try { ids = JSON.parse(row.affected_node_ids_json || '[]') || []; } catch (e) { ids = []; }
            ids.forEach(function(id) { if (id) map[String(id)] = row; });
            return;
        }
        if (!row.plan_node_id) {
            return;
        }
        map[row.plan_node_id] = row;
    });
    return map;
}

function get_display_length(child) {
    // For destroyed/destroy nodes, return the original dimension so they occupy the original footprint.
    if (is_destroy_node_type(child && child.node_type) && child.__original_length_mm) {
        return child.__original_length_mm;
    }
    return child.length_mm;
}

function get_display_width(child) {
    // For destroyed/destroy nodes, return the original dimension so they occupy the original footprint.
    if (is_destroy_node_type(child && child.node_type) && child.__original_width_mm) {
        return child.__original_width_mm;
    }
    return child.width_mm;
}



    const api = {
        configure,
        get_mcp_mode,
        apply_mcp_mode_ui,
        apply_variant_colors,
        select_all_grid_rows,
        render_cutting_plan_preview,
        clear_move_state,
        clear_merge_state
    };

    global.MatRecoMCPUI = api;
})(window);
