(() => {
  // ../mat_reco/mat_reco/public/js/material_cutting_plan_ui.bundle.js
  (function(global) {
    const DEFAULT_CONFIG = {
      MCP_INCIDENT_TABLE: "material_plan_incidents",
      MCP_INCIDENT_ACTIONS: ["Resize", "Destroy", "Move"],
      MCP_MIN_LEFTOVER_DIMENSION_MM: 500,
      MCP_MODE_PLANIFICATION: "Planification",
      MCP_MODE_RETOUR_TERRAIN: "Retour Terrain",
      MCP_STOCK_CANDIDATE_TABLE: "mcp_stock_candidate"
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
      const raw = String(frm.doc.mcp_mode || "").trim().toLowerCase();
      const plan = String(cfg().MCP_MODE_PLANIFICATION || "").trim().toLowerCase();
      const retour = String(cfg().MCP_MODE_RETOUR_TERRAIN || "").trim().toLowerCase();
      if (raw === retour) {
        return cfg().MCP_MODE_RETOUR_TERRAIN;
      }
      return cfg().MCP_MODE_PLANIFICATION;
    }
    function set_grid_column_read_only(frm, tableFieldname, columnFieldname, isReadOnly) {
      try {
        const field = frm.fields_dict[tableFieldname];
        const grid = field && field.grid;
        if (!grid || !grid.update_docfield_property)
          return;
        grid.update_docfield_property(columnFieldname, "read_only", isReadOnly ? 1 : 0);
      } catch (e) {
        console.error("[MCP] Failed to update grid column property:", tableFieldname, columnFieldname, e);
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
      set_grid_column_read_only(frm, cfg().MCP_STOCK_CANDIDATE_TABLE, "is_qualified", !isPlanification);
      set_grid_column_read_only(frm, cfg().MCP_STOCK_CANDIDATE_TABLE, "is_active_input", !isRetourTerrain);
      frm.refresh_field(cfg().MCP_STOCK_CANDIDATE_TABLE);
      frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
    }
    function getSalesOrderPalette() {
      return [
        { fill: "#dbeafe", border: "#2563eb", text: "#1e3a8a" },
        { fill: "#dcfce7", border: "#16a34a", text: "#166534" },
        { fill: "#fef3c7", border: "#d97706", text: "#92400e" },
        { fill: "#fce7f3", border: "#db2777", text: "#9d174d" },
        { fill: "#ede9fe", border: "#7c3aed", text: "#5b21b6" },
        { fill: "#fee2e2", border: "#dc2626", text: "#991b1b" },
        { fill: "#cffafe", border: "#0891b2", text: "#164e63" },
        { fill: "#ecfccb", border: "#65a30d", text: "#3f6212" },
        { fill: "#fde68a", border: "#ca8a04", text: "#854d0e" },
        { fill: "#e2e8f0", border: "#475569", text: "#334155" }
      ];
    }
    function buildVariantColorMap(frm) {
      const palette = getSalesOrderPalette();
      const map = {};
      let idx = 0;
      (frm.doc.item_variant_detail || []).forEach(function(row) {
        const code = row.variant_item_code;
        if (!code || map[code])
          return;
        map[code] = palette[idx % palette.length];
        idx++;
      });
      return map;
    }
    function apply_variant_colors(frm) {
      setTimeout(function() {
        const variantColorMap = buildVariantColorMap(frm);
        const variantGrid = frm.fields_dict.item_variant_detail && frm.fields_dict.item_variant_detail.grid;
        if (variantGrid && variantGrid.grid_rows) {
          variantGrid.grid_rows.forEach(function(gridRow) {
            const row = gridRow.doc || {};
            const color = variantColorMap[row.variant_item_code];
            const $row = $(gridRow.row || gridRow.wrapper);
            if (!$row || !$row.length)
              return;
            if (color) {
              $row.css({
                "background-color": color.fill,
                "border-left": "4px solid " + color.border
              });
            } else {
              $row.css({
                "background-color": "",
                "border-left": ""
              });
            }
          });
        }
        const stockGrid = frm.fields_dict.mcp_stock_candidate && frm.fields_dict.mcp_stock_candidate.grid;
        if (stockGrid && stockGrid.grid_rows) {
          stockGrid.grid_rows.forEach(function(gridRow) {
            const row = gridRow.doc || {};
            const $row = $(gridRow.row || gridRow.wrapper);
            if (!$row || !$row.length)
              return;
            if (row.item_code === frm.doc.source_item) {
              $row.css({
                "background-color": "",
                "border-left": "4px solid transparent"
              });
              return;
            }
            const color = variantColorMap[row.item_code];
            if (color) {
              $row.css({
                "background-color": color.fill,
                "border-left": "4px solid " + color.border
              });
            } else {
              $row.css({
                "background-color": "",
                "border-left": ""
              });
            }
          });
        }
      }, 80);
    }
    function select_all_grid_rows(frm, fieldname) {
      setTimeout(function() {
        const field = frm.fields_dict[fieldname];
        if (!field || !field.grid || !field.grid.grid_rows)
          return;
        field.grid.grid_rows.forEach(function(gridRow) {
          try {
            if (gridRow.select) {
              gridRow.select(true);
            }
          } catch (e) {
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
          const so = child.sales_order || "NO-SO";
          if (child.node_type === "finished_good" && !seen[so]) {
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
    function ensure_move_escape_binding(frm) {
      if (frm.__mcp_move_escape_bound)
        return;
      frm.__mcp_move_escape_bound = true;
      $(document).off("keydown.mcpmove." + frm.doctype + "." + frm.docname);
      $(document).on("keydown.mcpmove." + frm.doctype + "." + frm.docname, function(event) {
        if (event.key !== "Escape")
          return;
        if (!get_active_move_state(frm))
          return;
        event.preventDefault();
        clear_move_state(frm, { silent: false });
      });
    }
    function clear_move_state(frm, options) {
      const opts = options || {};
      frm.__mcp_move_state = null;
      if (!opts.silent) {
        frappe.show_alert({ message: __("Move mode cancelled."), indicator: "orange" });
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
        message: __("Move mode active. Go to another serial/tab and click a target position. Double-click or press Esc to cancel."),
        indicator: "blue"
      });
      render_cutting_plan_preview(frm);
    }
    function rectangles_overlap(a, b) {
      return !(flt(a.x) + flt(a.length_mm) <= flt(b.x) || flt(b.x) + flt(b.length_mm) <= flt(a.x) || flt(a.y) + flt(a.width_mm) <= flt(b.y) || flt(b.y) + flt(b.width_mm) <= flt(a.y));
    }
    function clamp(value, minValue, maxValue) {
      if (maxValue < minValue) {
        return minValue;
      }
      return Math.max(minValue, Math.min(maxValue, value));
    }
    function child_id_js(child) {
      return String(child && (child.id || child.piece_uid) || "").trim();
    }
    function normalize_node_type(nodeType) {
      return String(nodeType || "").trim().toLowerCase();
    }
    function is_destroy_node_type(nodeType) {
      const t = normalize_node_type(nodeType);
      return t === "destroyed" || t === "destroy";
    }
    function node_serial_js(node) {
      return String(node && (node.serial_no || node.id) || "").trim();
    }
    function is_free_zone_type(nodeType) {
      const value = normalize_node_type(nodeType);
      return value === "leftover" || value === "waste";
    }
    function rect_contains_rect(outerRect, innerRect) {
      return flt(innerRect.x) >= flt(outerRect.x) && flt(innerRect.y) >= flt(outerRect.y) && flt(innerRect.x) + flt(innerRect.length_mm) <= flt(outerRect.x) + flt(outerRect.length_mm) && flt(innerRect.y) + flt(innerRect.width_mm) <= flt(outerRect.y) + flt(outerRect.width_mm);
    }
    function classify_free_zone_type(lengthMm, widthMm) {
      return Math.min(flt(lengthMm), flt(widthMm)) < flt(cfg().MCP_MIN_LEFTOVER_DIMENSION_MM) ? "waste" : "leftover";
    }
    function sort_children_js(children) {
      return (children || []).slice().sort(function(a, b) {
        const ay = flt(a && a.y || 0);
        const by = flt(b && b.y || 0);
        if (ay !== by)
          return ay - by;
        const ax = flt(a && a.x || 0);
        const bx = flt(b && b.x || 0);
        if (ax !== bx)
          return ax - bx;
        return child_id_js(a).localeCompare(child_id_js(b));
      });
    }
    function resolve_target_free_zone(targetNode, candidate, preferredZoneId) {
      const children = targetNode && targetNode.children || [];
      let preferred = null;
      const matches = [];
      children.forEach(function(child) {
        if (!is_free_zone_type(child && child.node_type)) {
          return;
        }
        const zoneRect = {
          x: flt(child && child.x || 0),
          y: flt(child && child.y || 0),
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
      const preferredZoneId = opts.targetZoneId || "";
      const moveState = get_active_move_state(frm);
      if (!moveState) {
        return { ok: false, message: __("Move mode is not active.") };
      }
      const targetNode = (frm.__cut_nodes || []).find(function(node) {
        return node_serial_js(node) === String(targetSerialNo || "");
      });
      if (!targetNode) {
        return { ok: false, message: __("Target serial not found in current preview.") };
      }
      const pieceLength = flt(moveState.length_mm);
      const pieceWidth = flt(moveState.width_mm);
      const sheetLength = flt(targetNode.length_mm || targetNode.length || 0);
      const sheetWidth = flt(targetNode.width_mm || targetNode.width || 0);
      if (pieceLength <= 0 || pieceWidth <= 0 || sheetLength <= 0 || sheetWidth <= 0) {
        return { ok: false, message: __("Invalid dimensions for move.") };
      }
      if (targetX < 0 || targetY < 0 || targetX + pieceLength > sheetLength || targetY + pieceWidth > sheetWidth) {
        return { ok: false, message: __("The selected target position is outside the target serial boundaries.") };
      }
      const candidate = {
        x: flt(targetX),
        y: flt(targetY),
        length_mm: pieceLength,
        width_mm: pieceWidth
      };
      const targetZone = resolve_target_free_zone(targetNode, candidate, preferredZoneId);
      if (!targetZone) {
        return { ok: false, message: __("The selected target position is not fully contained in a free zone.") };
      }
      const zoneLength = flt(get_display_length(targetZone) || 0);
      const zoneWidth = flt(get_display_width(targetZone) || 0);
      if (pieceLength > zoneLength || pieceWidth > zoneWidth) {
        return { ok: false, message: __("The moving piece is larger than the selected free zone and cannot be swapped.") };
      }
      const swapOnly = pieceLength === zoneLength && pieceWidth === zoneWidth;
      const occupied = (targetNode.children || []).filter(function(child) {
        const nodeId = child_id_js(child);
        if (nodeId === String(moveState.source_node_id || "")) {
          return false;
        }
        const normalizedType = normalize_node_type(child && child.node_type);
        if (is_free_zone_type(normalizedType)) {
          return false;
        }
        return normalizedType === "finished_good" || is_destroy_node_type(normalizedType);
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
          return { ok: false, message: __("The selected target position overlaps an existing occupied zone.") };
        }
      }
      return {
        ok: true,
        payload: {
          plan_node_id: moveState.source_node_id,
          source_serial_no: moveState.source_serial_no,
          original_node_type: "finished_good",
          original_item_code: moveState.item_code,
          original_length_mm: pieceLength,
          original_width_mm: pieceWidth,
          original_area_mm2: pieceLength * pieceWidth,
          incident_action: "Move",
          affected_node_ids_json: JSON.stringify([moveState.source_node_id]),
          group_area_mm2: pieceLength * pieceWidth,
          new_node_type: "finished_good",
          new_item_code: moveState.item_code,
          new_length_mm: pieceLength,
          new_width_mm: pieceWidth,
          new_area_mm2: pieceLength * pieceWidth,
          target_serial_no: targetSerialNo,
          target_x_mm: targetX,
          target_y_mm: targetY,
          include_in_repack: 1,
          is_active: 1,
          remarks: "",
          swap_only: swapOnly ? 1 : 0
        }
      };
    }
    function try_finish_move_on_sheet(frm, event, $sheet, $clickedPiece) {
      const moveState = get_active_move_state(frm);
      if (!moveState)
        return false;
      const offset = $sheet.offset();
      if (!offset)
        return false;
      const serialNo = $sheet.attr("data-serial-no") || "";
      const scale = flt($sheet.attr("data-scale"));
      if (!serialNo || scale <= 0)
        return false;
      const rawX = (event.pageX - offset.left) / scale;
      const rawY = (event.pageY - offset.top) / scale;
      const pieceLength = flt(moveState.length_mm);
      const pieceWidth = flt(moveState.width_mm);
      let targetX = Math.max(0, rawX - pieceLength / 2);
      let targetY = Math.max(0, rawY - pieceWidth / 2);
      let targetZoneId = "";
      if ($clickedPiece && $clickedPiece.length) {
        const clickedNodeType = String($clickedPiece.attr("data-node-type") || "");
        if (is_free_zone_type(clickedNodeType)) {
          const zoneX = flt($clickedPiece.attr("data-x") || 0);
          const zoneY = flt($clickedPiece.attr("data-y") || 0);
          const zoneLength = flt($clickedPiece.attr("data-display-length") || $clickedPiece.attr("data-length") || 0);
          const zoneWidth = flt($clickedPiece.attr("data-display-width") || $clickedPiece.attr("data-width") || 0);
          targetZoneId = String($clickedPiece.attr("data-node-id") || "").trim();
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
      const result = build_target_move_payload(frm, serialNo, targetX, targetY, { targetZoneId });
      if (!result.ok) {
        frappe.msgprint(result.message || __("Invalid move target."));
        return true;
      }
      upsert_incident_row(frm, result.payload);
      frm.refresh_field(cfg().MCP_INCIDENT_TABLE);
      frm.__mcp_move_state = null;
      frappe.show_alert({ message: __("Piece moved in preview. Save to persist the new target serial."), indicator: "green" });
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
      const previewCol = frm.fields_dict.cutting_plan_preview.$wrapper.closest(".form-column");
      const summaryCol = frm.fields_dict.plan_summary && frm.fields_dict.plan_summary.$wrapper ? frm.fields_dict.plan_summary.$wrapper.closest(".form-column") : null;
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
        wrapper.html("<p>No cutting plan available.</p>");
        return;
      }
      let result;
      try {
        result = JSON.parse(jsonStr);
      } catch (e) {
        wrapper.html("<p>Invalid cutting plan data.</p>");
        return;
      }
      const tree = result.tree || result;
      const nodes = tree && tree.nodes || [];
      if (!nodes.length) {
        wrapper.html("<p>No cutting plan available.</p>");
        return;
      }
      const isRetour = get_mcp_mode(frm) === cfg().MCP_MODE_RETOUR_TERRAIN;
      const allIncidents = frm.doc[cfg().MCP_INCIDENT_TABLE] || [];
      const previewIncidents = isRetour ? allIncidents.filter(function(inc) {
        const action = String(inc && inc.incident_action || "").trim().toLowerCase();
        return action !== "move";
      }) : [];
      frm.__cut_nodes = apply_incidents_to_nodes(nodes, previewIncidents);
      frm.__cut_color_map = buildSalesOrderColorMap(frm.__cut_nodes);
      if (typeof frm.__cut_page === "undefined") {
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
          wrapper.html("<p>Invalid cutting plan data.</p>");
          return;
        }
        const pageWidth = 560;
        const pageHeight = 400;
        const pagePadding = 16;
        const drawingWidth = pageWidth - pagePadding * 2;
        const drawingHeight = pageHeight - pagePadding * 2;
        const scale = Math.min(drawingWidth / length_mm, drawingHeight / width_mm);
        const sheetWidthPx = length_mm * scale;
        const sheetHeightPx = width_mm * scale;
        let usedPieceArea = 0;
        (node.children || []).forEach(function(child) {
          if (child.node_type !== "finished_good") {
            return;
          }
          const cl = parseFloat(child.length_mm || child.length || 0);
          const cw = parseFloat(child.width_mm || child.width || 0);
          usedPieceArea += cl * cw;
        });
        const sheetArea = length_mm * width_mm;
        const occupancy = sheetArea ? usedPieceArea / sheetArea * 100 : 0;
        let html = "";
        const moveState = get_active_move_state(frm);
        if (moveState) {
          html += '<div style="margin-bottom:8px; padding:8px 10px; border:1px solid #93c5fd; background:#eff6ff; color:#1d4ed8; border-radius:6px;">';
          html += "<strong>Move mode</strong> \u2014 " + frappe.utils.escape_html(moveState.source_node_id || "") + " from " + frappe.utils.escape_html(moveState.source_serial_no || "") + ". ";
          html += "Click a target position on any serial preview. Double-click or press Esc to cancel.";
          html += "</div>";
        }
        html += '<div style="margin-bottom:5px;">';
        html += "<strong>Serial " + (idx + 1) + " / " + frm.__cut_nodes.length + "</strong> ";
        html += node.serial_no ? node.serial_no + " " : "";
        html += "(" + length_mm + " x " + width_mm + ") \u2014 ";
        const finishedGoodsCount = (node.children || []).filter(function(child) {
          return child.node_type === "finished_good";
        }).length;
        html += "Pieces: " + finishedGoodsCount + " \u2014 ";
        html += "Utilisation: " + occupancy.toFixed(1) + "%";
        html += "</div>";
        const legendMap = {};
        (node.children || []).forEach(function(child) {
          if (child.node_type === "finished_good") {
            const so = child.sales_order || "NO-SO";
            if (!legendMap[so]) {
              legendMap[so] = frm.__cut_color_map && frm.__cut_color_map[so] || null;
            }
          }
        });
        html += '<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px;">';
        Object.keys(legendMap).forEach(function(so) {
          const c = legendMap[so];
          if (c) {
            html += '<div style="display:flex; align-items:center; gap:6px; font-size:12px;">';
            html += '<span style="display:inline-block; width:14px; height:14px; border:1px solid ' + c.border + "; background:" + c.fill + ';"></span>';
            html += "<span>" + frappe.utils.escape_html(so) + "</span>";
            html += "</div>";
          }
        });
        html += "</div>";
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
                <div class="mcp-sheet-canvas" data-serial-no="${frappe.utils.escape_html(String(node.serial_no || ""))}" data-scale="${scale}" data-sheet-length="${length_mm}" data-sheet-width="${width_mm}" style="
                    position:relative;
                    width:${sheetWidthPx}px;
                    height:${sheetHeightPx}px;
                    border:1px solid #000;
                    background:#f9f9f9;
                    flex:none;
                    cursor:${get_active_move_state(frm) ? "crosshair" : "default"};
                ">
        `;
        (node.children || []).forEach(function(child) {
          const displayLength = get_display_length(child);
          const displayWidth = get_display_width(child);
          const cx = parseFloat(child.x || child.x === 0 ? child.x : 0);
          const cy = parseFloat(child.y || child.y === 0 ? child.y : 0);
          const cl = parseFloat(displayLength || 0);
          const cw = parseFloat(displayWidth || 0);
          const px = cx * scale;
          const py = cy * scale;
          const pw = cl * scale;
          const ph = cw * scale;
          const rotationFlag = child.rotation ? "Rotated" : "";
          const refId = child.plan_ref_id || "";
          const pieceCode = child.piece_item_code || "";
          const so = child.sales_order || "NO-SO";
          const tip = [];
          if (refId)
            tip.push("Piece: " + refId);
          if (pieceCode)
            tip.push("Item: " + pieceCode);
          if (cl && cw)
            tip.push(cl + " x " + cw);
          if (rotationFlag)
            tip.push(rotationFlag);
          if (child.sales_order)
            tip.push("SO: " + child.sales_order);
          if (child.root_item_name)
            tip.push("Root: " + child.root_item_name);
          if (child.__incident_action)
            tip.push("Incident: " + child.__incident_action);
          if (child.__generated_from_resize)
            tip.push("Generated destroy from resize");
          let style = "position:absolute; left:" + px + "px; top:" + py + "px; width:" + pw + "px; height:" + ph + "px; display:flex; align-items:center; justify-content:center; text-align:center; box-sizing:border-box; font-size:10px; cursor:pointer;";
          const moveStateActive = get_active_move_state(frm);
          const isMoveSource = moveStateActive && String(moveStateActive.source_node_id || "") === String(child.id || child.piece_uid || "");
          const normalizedType = normalize_node_type(child.node_type);
          if (normalizedType === "leftover") {
            style += "border:2px solid #6b7280; background-color:#f3f4f6; background-image:repeating-linear-gradient(45deg,#d1d5db,#d1d5db 6px,#f3f4f6 6px,#f3f4f6 12px); color:#1f2937;";
          } else if (normalizedType === "waste") {
            style += "border:2px solid #dc2626; background-color:#fee2e2; background-image:repeating-linear-gradient(45deg,#fca5a5,#fca5a5 6px,#fee2e2 6px,#fee2e2 12px); color:#7f1d1d;";
          } else if (is_destroy_node_type(normalizedType)) {
            style += "border:2px solid #374151; background-color:#4b5563; color:#f8fafc;";
          } else {
            const c = frm.__cut_color_map && frm.__cut_color_map[so] || { fill: "#e5e7eb", border: "#6b7280", text: "#111827" };
            style += "border:1px solid " + c.border + "; background:" + c.fill + "; color:" + c.text + ";";
          }
          if (isMoveSource) {
            style += "outline:3px dashed #2563eb; outline-offset:-3px;";
          }
          let dataAttrs = "";
          dataAttrs += ' data-node-id="' + frappe.utils.escape_html(String(child.id || child.piece_uid || "")) + '"';
          dataAttrs += ' data-node-type="' + frappe.utils.escape_html(String(child.node_type || "")) + '"';
          dataAttrs += ' data-source-serial="' + frappe.utils.escape_html(String(node.serial_no || "")) + '"';
          dataAttrs += ' data-length="' + frappe.utils.escape_html(String(child.length_mm || 0)) + '"';
          dataAttrs += ' data-width="' + frappe.utils.escape_html(String(child.width_mm || 0)) + '"';
          dataAttrs += ' data-display-length="' + frappe.utils.escape_html(String(displayLength || 0)) + '"';
          dataAttrs += ' data-display-width="' + frappe.utils.escape_html(String(displayWidth || 0)) + '"';
          dataAttrs += ' data-piece-item-code="' + frappe.utils.escape_html(String(child.piece_item_code || child.item_code || "")) + '"';
          dataAttrs += ' data-root-item-code="' + frappe.utils.escape_html(String(child.root_item_code || "")) + '"';
          dataAttrs += ' data-sales-order="' + frappe.utils.escape_html(String(child.sales_order || "")) + '"';
          dataAttrs += ' data-x="' + frappe.utils.escape_html(String(child.x || 0)) + '"';
          dataAttrs += ' data-y="' + frappe.utils.escape_html(String(child.y || 0)) + '"';
          const tooltip = tip.join("\n");
          html += '<div class="cut-piece" ' + dataAttrs + ' title="' + frappe.utils.escape_html(tooltip) + '" style="' + style + '">';
          let content = "";
          if (child.node_type === "finished_good") {
            if (refId) {
              content += "<div>" + frappe.utils.escape_html(refId) + "</div>";
            }
            if (pieceCode) {
              content += "<div>" + frappe.utils.escape_html(pieceCode) + "</div>";
            }
          } else if (is_destroy_node_type(child.node_type)) {
            content += "<div>D</div>";
            content += "<div>" + cl + " x " + cw + "</div>";
          } else {
            const normTypeForLabel = normalize_node_type(child.node_type);
            const label = normTypeForLabel === "leftover" ? "L" : "W";
            content += "<div>" + frappe.utils.escape_html(label) + "</div>";
            content += "<div>" + cl + " x " + cw + "</div>";
          }
          html += content;
          html += "</div>";
        });
        html += "</div></div>";
        html += '<div style="display:flex; align-items:center; gap:10px; margin-top:8px; margin-bottom:12px;">';
        const prevDisabled = frm.__cut_page <= 0 ? "disabled" : "";
        const nextDisabled = frm.__cut_page >= frm.__cut_nodes.length - 1 ? "disabled" : "";
        html += '<button type="button" class="btn btn-default cut-prev" ' + prevDisabled + ">Previous</button>";
        html += '<button type="button" class="btn btn-default cut-next" ' + nextDisabled + ">Next</button>";
        html += "</div>";
        wrapper.html(html);
        wrapper.find(".cut-prev").on("click", function() {
          if (frm.__cut_page > 0) {
            frm.__cut_page--;
            updatePreview();
          }
        });
        wrapper.find(".cut-next").on("click", function() {
          if (frm.__cut_page < frm.__cut_nodes.length - 1) {
            frm.__cut_page++;
            updatePreview();
          }
        });
        wrapper.find(".cut-piece").on("click", function(e) {
          e.preventDefault();
          e.stopPropagation();
          const $piece = $(this);
          if (get_active_move_state(frm)) {
            try_finish_move_on_sheet(frm, e, $piece.closest(".mcp-sheet-canvas"), $piece);
            return;
          }
          on_cut_piece_click(frm, $piece);
        });
        wrapper.find(".mcp-sheet-canvas").on("click", function(e) {
          if (!get_active_move_state(frm)) {
            return;
          }
          e.preventDefault();
          e.stopPropagation();
          try_finish_move_on_sheet(frm, e, $(this), null);
        });
        wrapper.off("dblclick.mcpmove").on("dblclick.mcpmove", function() {
          if (get_active_move_state(frm)) {
            clear_move_state(frm, { silent: false });
          }
        });
      }
      updatePreview();
      function renderSummary() {
        const summaryField = frm.fields_dict.plan_summary;
        if (!summaryField)
          return;
        const wrapper2 = summaryField.$wrapper;
        wrapper2.empty();
        if (!frm.doc.summary_json) {
          wrapper2.html("<p>No summary available.</p>");
          return;
        }
        let summary;
        try {
          summary = JSON.parse(frm.doc.summary_json);
        } catch (e) {
          wrapper2.html("<p>Invalid summary data.</p>");
          return;
        }
        function fmt(v) {
          return (v || 0).toLocaleString(void 0, { maximumFractionDigits: 2 });
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
                    <div style="color:${summary.missing_piece_count > 0 ? "#dc2626" : "#16a34a"};">
                        ${fmt(summary.missing_piece_count)}
                    </div>

                    <div style="grid-column:1 / -1;"><hr></div>

                    <div><strong>Input Serials</strong></div>
                    <div>${fmt(summary.used_input_serial_count)}</div>

                    <div><strong>Leftovers</strong></div>
                    <div>${fmt(summary.leftover_count)}</div>

                    <div style="grid-column:1 / -1;"><hr></div>

                    <div><strong>Required Area</strong></div>
                    <div>${fmt(summary.total_required_area_m2)} m\xB2</div>

                    <div><strong>Used Area</strong></div>
                    <div>${fmt(summary.total_used_input_area_m2)} m\xB2</div>

                    <div><strong>Leftover</strong></div>
                    <div>${fmt(summary.total_leftover_area_m2)} m\xB2</div>

                    <div><strong>Waste</strong></div>
                    <div>${fmt(summary.total_waste_area_m2)} m\xB2</div>

                </div>
            </div>
            `;
        wrapper2.html(html);
      }
      renderSummary();
    }
    function on_cut_piece_click(frm, $piece) {
      if (get_mcp_mode(frm) !== cfg().MCP_MODE_RETOUR_TERRAIN) {
        frappe.msgprint(__("Incidents are only available in Retour Terrain mode."));
        return;
      }
      if (frm.doc.docstatus !== 0) {
        frappe.msgprint(__("Incidents can only be added or modified when the plan is in Draft status."));
        return;
      }
      let parsedResult = null;
      try {
        parsedResult = JSON.parse(frm.doc.result_json || frm.doc.result_tree_json || "{}");
      } catch (e) {
        parsedResult = null;
      }
      const resolvedTree = parsedResult ? parsedResult.tree || parsedResult : {};
      const treeAlreadyResolved = cint(resolvedTree.return_terrain_resolved || (resolvedTree.options || {}).return_terrain_resolved || 0) === 1;
      const nodeData = extract_node_data($piece);
      const existingIncident = find_incident_row(frm, nodeData.node_id);
      const d = new frappe.ui.Dialog({
        title: __("Action on Piece"),
        fields: [
          {
            fieldname: "incident_action",
            fieldtype: "Select",
            label: __("Action"),
            options: cfg().MCP_INCIDENT_ACTIONS.join("\n"),
            reqd: 1,
            default: existingIncident ? existingIncident.incident_action : "Resize"
          },
          {
            fieldname: "new_length_mm",
            fieldtype: "Float",
            label: __("New Length (mm)"),
            default: existingIncident ? flt(existingIncident.new_length_mm) : flt(nodeData.length_mm),
            depends_on: 'eval:doc.incident_action==="Resize"'
          },
          {
            fieldname: "new_width_mm",
            fieldtype: "Float",
            label: __("New Width (mm)"),
            default: existingIncident ? flt(existingIncident.new_width_mm) : flt(nodeData.width_mm),
            depends_on: 'eval:doc.incident_action==="Resize"'
          },
          {
            fieldname: "remarks",
            fieldtype: "Small Text",
            label: __("Remarks"),
            default: existingIncident ? existingIncident.remarks || "" : ""
          }
        ],
        primary_action_label: __("Apply"),
        primary_action(values) {
          if (values.incident_action === "Move") {
            if (nodeData.node_type !== "finished_good") {
              frappe.msgprint(__("Move is only available for finished goods."));
              return;
            }
            d.hide();
            start_move_mode(frm, nodeData);
            return;
          }
          const result = build_incident_payload(frm, nodeData, values);
          if (!result.ok) {
            frappe.msgprint(result.message || __("Invalid incident."));
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
      if (action === "Move") {
        return { ok: false, message: __("Use Move mode to select a target position on another serial.") };
      }
      if (action === "Destroy") {
        newLength = 0;
        newWidth = 0;
        newArea = 0;
        newNodeType = "destroyed";
        includeInRepack = 0;
      } else {
        if (newLength <= 0 || newWidth <= 0) {
          return { ok: false, message: __("Length and Width must be greater than zero.") };
        }
        newArea = newLength * newWidth;
        if (newArea > originalArea) {
          return { ok: false, message: __("The new area cannot exceed the original area for this first version.") };
        }
        newNodeType = Math.min(newLength, newWidth) < cfg().MCP_MIN_LEFTOVER_DIMENSION_MM ? "waste" : "leftover";
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
          remarks: values.remarks || ""
        }
      };
    }
    function extract_node_data($piece) {
      return {
        node_id: $piece.attr("data-node-id") || "",
        node_type: $piece.attr("data-node-type") || "",
        source_serial_no: $piece.attr("data-source-serial") || "",
        item_code: $piece.attr("data-piece-item-code") || $piece.attr("data-root-item-code") || "",
        length_mm: flt($piece.attr("data-length")),
        width_mm: flt($piece.attr("data-width")),
        display_length_mm: flt($piece.attr("data-display-length")),
        display_width_mm: flt($piece.attr("data-display-width")),
        x: flt($piece.attr("data-x")),
        y: flt($piece.attr("data-y")),
        sales_order: $piece.attr("data-sales-order") || ""
      };
    }
    function find_incident_row(frm, planNodeId) {
      const rows = frm.doc[cfg().MCP_INCIDENT_TABLE] || [];
      for (let i = 0; i < rows.length; i++) {
        if ((rows[i].plan_node_id || "") === planNodeId && cint(rows[i].is_active || 0) === 1) {
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
      out.node_type = "destroyed";
      out.__incident_action = "Destroy";
      out.__original_length_mm = flt(child.length_mm || 0);
      out.__original_width_mm = flt(child.width_mm || 0);
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
        destroyRight.node_type = "destroyed";
        destroyRight.__generated_from_resize = 1;
        destroyRight.__destroy_region_kind = "right_strip";
        destroyRight.__incident_action = "Resize";
        destroyRight.x = x + keptLength;
        destroyRight.y = y;
        destroyRight.length_mm = rightWidth;
        destroyRight.width_mm = originalWidth;
        destroyRight.__original_length_mm = rightWidth;
        destroyRight.__original_width_mm = originalWidth;
        destroyRight.__kept_length_mm = keptLength;
        destroyRight.__kept_width_mm = keptWidth;
        destroys.push(destroyRight);
      }
      const bottomHeight = originalWidth - keptWidth;
      if (bottomHeight > 0) {
        const destroyBottom = clone_child(child);
        destroyBottom.node_type = "destroyed";
        destroyBottom.__generated_from_resize = 1;
        destroyBottom.__destroy_region_kind = "bottom_strip";
        destroyBottom.__incident_action = "Resize";
        destroyBottom.x = x;
        destroyBottom.y = y + keptWidth;
        destroyBottom.length_mm = keptLength;
        destroyBottom.width_mm = bottomHeight;
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
      const newType = (incident.new_node_type || child.node_type || "").trim();
      if (newLength <= 0 || newWidth <= 0) {
        return [clone_child(child)];
      }
      if (newLength > originalLength || newWidth > originalWidth) {
        return [clone_child(child)];
      }
      const modified = clone_child(child);
      modified.__incident_action = "Resize";
      modified.__incident_name = incident.name;
      modified.__original_length_mm = originalLength;
      modified.__original_width_mm = originalWidth;
      modified.node_type = newType || modified.node_type;
      modified.length_mm = newLength;
      modified.width_mm = newWidth;
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
      const action = (incident.incident_action || "").trim();
      if (action === "Move") {
        return { ok: false, message: __("Use Move mode to select a target position on another serial.") };
      }
      if (action === "Destroy") {
        return [apply_destroy_to_child_js(child)];
      }
      if (action === "Resize") {
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
      const baseId = child_id_js(templateChild) || "zone";
      out.id = suffix ? baseId + suffix : baseId;
      out.node_type = classify_free_zone_type(l, w);
      out.x = flt(x || 0);
      out.y = flt(y || 0);
      out.length_mm = l;
      out.width_mm = w;
      out.__incident_action = "Move";
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
        suffix || "__freed"
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
      const left = build_free_zone_from_rect_js(targetZone, zoneX, zoneY, candX - zoneX, zoneW, "__move_left");
      if (left)
        rows.push(left);
      const right = build_free_zone_from_rect_js(targetZone, candX + candL, zoneY, zoneX + zoneL - (candX + candL), zoneW, "__move_right");
      if (right)
        rows.push(right);
      const top = build_free_zone_from_rect_js(targetZone, candX, zoneY, candL, candY - zoneY, "__move_top");
      if (top)
        rows.push(top);
      const bottom = build_free_zone_from_rect_js(targetZone, candX, candY + candW, candL, zoneY + zoneW - (candY + candW), "__move_bottom");
      if (bottom)
        rows.push(bottom);
      return rows;
    }
    function apply_incidents_to_nodes(nodes, incidents) {
      const incidentMap = build_incident_map(incidents || []);
      const sourceMoveIds = {};
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
          const action = String(incident && incident.incident_action || "").trim();
          if (action !== "Move" || String(child && child.node_type || "").trim() !== "finished_good") {
            return;
          }
          sourceMoveIds[childId] = true;
          additionsBySerial[sourceSerial] = additionsBySerial[sourceSerial] || [];
          const targetSerial = String(incident && incident.target_serial_no || sourceSerial).trim() || sourceSerial;
          const targetX = (incident && incident.target_x_mm) != null ? incident.target_x_mm : child.x || 0;
          const targetY = (incident && incident.target_y_mm) != null ? incident.target_y_mm : child.y || 0;
          const sameSpot = targetSerial === sourceSerial && flt(targetX) === flt(child.x || 0) && flt(targetY) === flt(child.y || 0);
          if (!sameSpot) {
            const freedZone = build_free_zone_from_child_js(child, "__freed");
            if (freedZone) {
              additionsBySerial[sourceSerial].push(freedZone);
            }
          }
          const targetNode = originalNodeBySerial[targetSerial];
          const movedChild = clone_child(child);
          movedChild.x = flt(targetX);
          movedChild.y = flt(targetY);
          movedChild.source_serial_no = targetSerial;
          movedChild.__incident_action = "Move";
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
          const targetZone = resolve_target_free_zone(targetNode, candidate, "");
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
          const action = String(incident && incident.incident_action || "").trim();
          if (sourceMoveIds[childId]) {
            return;
          }
          if ((consumedTargetZonesBySerial[serial] || {})[childId]) {
            return;
          }
          const effectiveChildren = apply_incident_to_child_as_nodes_js(childClone, action === "Move" ? null : incident);
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
        if (!row || !row.plan_node_id || cint(row.is_active || 0) !== 1) {
          return;
        }
        map[row.plan_node_id] = row;
      });
      return map;
    }
    function get_display_length(child) {
      if (is_destroy_node_type(child && child.node_type) && child.__original_length_mm) {
        return child.__original_length_mm;
      }
      return child.length_mm;
    }
    function get_display_width(child) {
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
      clear_move_state
    };
    global.MatRecoMCPUI = api;
  })(window);
})();
//# sourceMappingURL=material_cutting_plan_ui.bundle.WXMQLEXC.js.map
