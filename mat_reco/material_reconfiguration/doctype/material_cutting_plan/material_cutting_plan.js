// Copyright (c) 2026, Richard Amouzou and contributors
// For license information, please see license.txt

// Client-side script for Material Cutting Plan

const MCP_INCIDENT_TABLE = 'material_plan_incidents';
const MCP_INCIDENT_ACTIONS = ['Resize', 'Destroy'];
const MCP_MIN_LEFTOVER_DIMENSION_MM = 500;

frappe.ui.form.on('Material Cutting Plan', {
    refresh: function(frm) {
        /*frm.add_custom_button(
            __('Get Non Processed Orders'),
            function() {
                frappe.call({
                    method: 'mat_reco.material_reconfiguration.api.get_non_processed_orders',
                    args: {
                        source_item: frm.doc.source_item
                    },
                    callback: function(r) {
                        if (!r.message) {
                            return;
                        }

                        frm.clear_table('selected_sales_orders');
                        $.each(r.message, function(i, so) {
                            let row = frm.add_child('selected_sales_orders');
                            row.sales_order = so.name;
                            row.customer = so.customer;
                        });
                        frm.refresh_field('selected_sales_orders');
                    }
                });
            },
            __('Order Selection')
        );*/

        frm.add_custom_button(
            __('Select Orders for Source Item'),
            function() {
                if (!frm.doc.source_item) {
                    frappe.msgprint(__('Please select a Source Item first.'));
                    return;
                }

                frappe.call({
                    method: 'mat_reco.material_reconfiguration.api.get_orders_by_source_item',
                    args: { source_item: frm.doc.source_item },
                    callback: function(r) {
                        if (!r.message) {
                            return;
                        }

                        frm.clear_table('selected_sales_orders');
                        $.each(r.message, function(i, so) {
                            let row = frm.add_child('selected_sales_orders');
                            row.sales_order = so.name;
                            if (so.customer) {
                                row.customer = so.customer;
                            }
                        });
                        frm.refresh_field('selected_sales_orders');
                    }
                });
            },
            //__('Order Selection')
        );

        frm.add_custom_button(__('Create Draft Repack'), function() {
            if (!frm.doc.name) {
                frappe.msgprint(__('Please save the Material Cutting Plan first.'));
                return;
            }

            frappe.call({
                method: 'mat_reco.material_reconfiguration.services.repack_draft_service.make_repack_draft',
                args: {
                    material_cutting_plan_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __('Preparing draft Repack Stock Entry...'),
                callback: function(r) {
                    if (!r.message) {
                        return;
                    }

                    const doc = frappe.model.sync(r.message)[0];
                    frappe.set_route('Form', doc.doctype, doc.name);
                }
            });
        });

        render_cutting_plan_preview(frm);
    },

    result_json: function(frm) {
        render_cutting_plan_preview(frm);
    },

    result_tree_json: function(frm) {
        render_cutting_plan_preview(frm);
    },

    material_plan_incidents: function(frm) {
        render_cutting_plan_preview(frm);
    }
});

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

function render_cutting_plan_preview(frm) {
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

    const jsonStr = frm.doc.result_json || frm.doc.result_tree_json;
    if (!jsonStr) {
        wrapper.html('<p>No cutting plan available.</p>');
        return;
    }

    let result;
    try {
        result = JSON.parse(jsonStr);
    } catch (e) {
        wrapper.html('<p>Invalid cutting plan data.</p>');
        return;
    }

    const tree = result.tree || result;
    const nodes = (tree && tree.nodes) || [];
    if (!nodes.length) {
        wrapper.html('<p>No cutting plan available.</p>');
        return;
    }

    frm.__cut_nodes = apply_incidents_to_nodes(nodes, frm.doc[MCP_INCIDENT_TABLE] || []);
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

        const sheetArea = length_mm * width_mm;
        const occupancy = sheetArea ? (usedPieceArea / sheetArea) * 100 : 0;

        let html = '';
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
                <div style="
                    position:relative;
                    width:${sheetWidthPx}px;
                    height:${sheetHeightPx}px;
                    border:1px solid #000;
                    background:#f9f9f9;
                    flex:none;
                ">
        `;

        (node.children || []).forEach(function(child) {
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

            let style = 'position:absolute; left:' + px + 'px; top:' + py + 'px; width:' + pw + 'px; height:' + ph + 'px; display:flex; align-items:center; justify-content:center; text-align:center; box-sizing:border-box; font-size:10px; cursor:pointer;';
            if (child.node_type === 'leftover') {
                style += 'border:2px solid #6b7280; background-color:#f3f4f6; background-image:repeating-linear-gradient(45deg,#d1d5db,#d1d5db 6px,#f3f4f6 6px,#f3f4f6 12px); color:#1f2937;';
            } else if (child.node_type === 'waste') {
                style += 'border:2px solid #dc2626; background-color:#fee2e2; background-image:repeating-linear-gradient(45deg,#fca5a5,#fca5a5 6px,#fee2e2 6px,#fee2e2 12px); color:#7f1d1d;';
            } else if (child.node_type === 'destroyed') {
                style += 'border:2px solid #374151; background-color:#4b5563; color:#f8fafc;';
            } else {
                const c = (frm.__cut_color_map && frm.__cut_color_map[so]) || { fill: '#e5e7eb', border: '#6b7280', text: '#111827' };
                style += 'border:1px solid ' + c.border + '; background:' + c.fill + '; color:' + c.text + ';';
            }

            let dataAttrs = '';
            dataAttrs += ' data-node-id="' + frappe.utils.escape_html(String(child.id || child.piece_uid || '')) + '"';
            dataAttrs += ' data-node-type="' + frappe.utils.escape_html(String(child.node_type || '')) + '"';
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
            } else if (child.node_type === 'destroyed') {
                content += '<div>D</div>';
                content += '<div>' + cl + ' x ' + cw + '</div>';
            } else {
                const label = child.node_type === 'leftover' ? 'L' : 'W';
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
            on_cut_piece_click(frm, $(this));
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
    if (frm.doc.docstatus !== 0) {
        frappe.msgprint(__('Incidents can only be added or modified when the plan is in Draft status.'));
        return;
    }
    const nodeData = extract_node_data($piece);
    const existingIncident = find_incident_row(frm, nodeData.node_id);

    const d = new frappe.ui.Dialog({
        title: __('Action on Piece'),
        fields: [
            {
                fieldname: 'incident_action',
                fieldtype: 'Select',
                label: __('Action'),
                options: MCP_INCIDENT_ACTIONS.join('\n'),
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
            const result = build_incident_payload(frm, nodeData, values);
            if (!result.ok) {
                frappe.msgprint(result.message || __('Invalid incident.'));
                return;
            }
            upsert_incident_row(frm, result.payload);
            d.hide();
            frm.refresh_field(MCP_INCIDENT_TABLE);
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
        newNodeType = Math.min(newLength, newWidth) < MCP_MIN_LEFTOVER_DIMENSION_MM ? 'waste' : 'leftover';
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
    const rows = frm.doc[MCP_INCIDENT_TABLE] || [];
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
        row = frm.add_child(MCP_INCIDENT_TABLE);
    }
    Object.keys(payload).forEach(function(key) {
        row[key] = payload[key];
    });
}

function apply_incidents_to_nodes(nodes, incidents) {
    const incidentMap = build_incident_map(incidents || []);
    return (nodes || []).map(function(node) {
        const nodeClone = Object.assign({}, node);
        nodeClone.children = (node.children || []).map(function(child) {
            const clonedChild = Object.assign({}, child);
            const incident = incidentMap[clonedChild.id || clonedChild.piece_uid || ''];
            if (!incident) {
                return clonedChild;
            }
            clonedChild.__incident_action = incident.incident_action;
            clonedChild.__incident_name = incident.name;
            clonedChild.__original_length_mm = clonedChild.length_mm;
            clonedChild.__original_width_mm = clonedChild.width_mm;
            if ((incident.incident_action || '') === 'Destroy') {
                clonedChild.node_type = 'destroyed';
                clonedChild.length_mm = 0;
                clonedChild.width_mm = 0;
            } else if ((incident.incident_action || '') === 'Resize') {
                clonedChild.node_type = incident.new_node_type || clonedChild.node_type;
                clonedChild.length_mm = flt(incident.new_length_mm || clonedChild.length_mm);
                clonedChild.width_mm = flt(incident.new_width_mm || clonedChild.width_mm);
            }
            return clonedChild;
        });
        return nodeClone;
    });
}

function build_incident_map(incidents) {
    const map = {};
    (incidents || []).forEach(function(row) {
        if (!row || !row.plan_node_id || cint(row.is_active || 0) !== 1) {
            return;
        }
        map[row.plan_node_id] = row;
    });
    return map;
}

function get_display_length(child) {
    if (child.node_type === 'destroyed' && child.__original_length_mm) {
        return child.__original_length_mm;
    }
    return child.length_mm;
}

function get_display_width(child) {
    if (child.node_type === 'destroyed' && child.__original_width_mm) {
        return child.__original_width_mm;
    }
    return child.width_mm;
}
