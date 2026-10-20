# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from mat_reco.material_reconfiguration.api import create_serial_batch_bundle
from mat_reco.material_reconfiguration.utils.serial_naming import make_material_serial_no
from mat_reco.material_reconfiguration.utils.accounting_dimensions import (
    resolve_accounting_dimensions,
    resolve_and_apply_stock_entry_dimensions,
)


SUPPORTED_ITEM_TYPES = {"PRIMAIRE", "DECOUPE"}
DETAIL_FIELD = "material_receipt_plan_serial"


class MaterialReceiptPlan(Document):
	"""Prepare dimensioned serialized material then post a standard Material Receipt."""

	def before_validate(self):
		self._set_item_type()
		self._sync_detail_row_count()
		self._apply_primary_dimensions()
		self._calculate_areas_and_rates()

	def validate(self):
		self._validate_header()
		self._calculate_areas_and_rates()
		self._ensure_generated_serial_numbers()

	def before_submit(self):
		self._validate_for_submit()
		self._calculate_areas_and_rates()
		self._validate_accounting_dimensions()

	def on_submit(self):
		self._create_material_receipt()

	def on_cancel(self):
		se_name = (self.stock_entry or "").strip() if self.meta.has_field("stock_entry") else ""
		if not se_name:
			se_name = frappe.db.get_value(
				"Stock Entry",
				{
					"docstatus": 1,
					"remarks": self._stock_entry_remark(),
				},
				"name",
			)
		if se_name and frappe.db.exists("Stock Entry", se_name):
			se_doc = frappe.get_doc("Stock Entry", se_name)
			if se_doc.docstatus == 1:
				se_doc.cancel()

	# ------------------------------------------------------------------
	# Draft preparation / validation
	# ------------------------------------------------------------------
	def _rows(self):
		return self.get(DETAIL_FIELD) or []

	def _set_item_type(self):
		if not self.item_code:
			self.item_type = None
			return
		self.item_type = frappe.db.get_value("Item", self.item_code, "custom_item_types") or ""

	def _validate_header(self):
		if not self.company:
			frappe.throw(_("Company is required."))
		if not self.target_warehouse:
			frappe.throw(_("Warehouse is required."))
		if not self.item_code:
			frappe.throw(_("Item is required."))

		item_type = (self.item_type or "").strip().upper()
		if item_type not in SUPPORTED_ITEM_TYPES:
			frappe.throw(
				_(
					"Material Receipt Plan is reserved for PRIMAIRE and DECOUPE items. "
					"Use the standard ERPNext Material Receipt for item {0}."
				).format(frappe.bold(self.item_code))
			)

		qty = flt(self.qty)
		if qty <= 0 or qty != cint(qty):
			frappe.throw(
				_("Quantity must be a positive whole number because each detail row represents one Serial No.")
			)

		if flt(self.amount) < 0:
			frappe.throw(_("Amount cannot be negative."))

	def _sync_detail_row_count(self):
		qty = cint(flt(self.qty))
		if qty <= 0:
			return

		while len(self._rows()) < qty:
			self.append(DETAIL_FIELD, {})

		# Serial Nos only get created on submit, so draft rows may safely be
		# removed from the end when quantity is reduced.
		while len(self._rows()) > qty:
			self.get(DETAIL_FIELD).pop()

	def _apply_primary_dimensions(self):
		if (self.item_type or "").strip().upper() != "PRIMAIRE" or not self.item_code:
			return

		dims = frappe.db.get_value(
			"Item",
			self.item_code,
			["custom_sheet_length_mm", "custom_sheet_width_mm", "custom_thickness_mm"],
			as_dict=True,
		) or {}

		length_mm = flt(dims.get("custom_sheet_length_mm"))
		width_mm = flt(dims.get("custom_sheet_width_mm"))
		thickness_mm = flt(dims.get("custom_thickness_mm"))

		for row in self._rows():
			row.length_mm = length_mm
			row.width_mm = width_mm
			row.thickness_mm = thickness_mm

	def _calculate_areas_and_rates(self):
		"""Calculate area and allocate header amount to serial rows by area.

		Each detail row represents exactly one serial/piece (Stock Entry qty=1),
		therefore row.basic_rate is the incoming value of that piece, not a rate
		per square metre.
		"""
		rows = self._rows()
		total_area = 0.0

		for row in rows:
			length_mm = flt(row.length_mm)
			width_mm = flt(row.width_mm)
			row.area_m2 = (
				length_mm * width_mm / 1_000_000.0
				if length_mm > 0 and width_mm > 0
				else 0.0
			)
			total_area += flt(row.area_m2)

		self.total_area = total_area

		amount = flt(self.amount)
		positive_rows = [row for row in rows if flt(row.area_m2) > 0]

		if total_area <= 0 or not positive_rows:
			for row in rows:
				row.basic_rate = 0
			return

		# Use the header currency precision and put the rounding residual on the
		# last valid row. This guarantees sum(detail.basic_rate) == amount.
		precision = self.precision("amount") or 2
		allocated = 0.0

		for idx, row in enumerate(positive_rows):
			if idx == len(positive_rows) - 1:
				row.basic_rate = flt(amount - allocated, precision)
			else:
				row.basic_rate = flt(
					amount * flt(row.area_m2) / total_area,
					precision,
				)
				allocated += flt(row.basic_rate)

		for row in rows:
			if flt(row.area_m2) <= 0:
				row.basic_rate = 0

	def _ensure_generated_serial_numbers(self):
		"""Assign stable planned Serial No values while the plan is still a draft.

		The generated value is stored in a Data field because the corresponding
		Serial No document does not exist until submit. Once submitted, the real
		Link field ``serial_no`` is populated with the created Serial No.
		"""
		if not self.item_code or not self.posting_date:
			return

		for row in self._rows():
			if (row.generated_serial_no or "").strip():
				continue
			row.generated_serial_no = make_material_serial_no(
				source="Stock Entry",
				item_code=self.item_code,
				posting_date=self.posting_date,
			)

	def _validate_for_submit(self):
		self._validate_header()
		rows = self._rows()

		if len(rows) != cint(self.qty):
			frappe.throw(_("The number of material detail rows must equal Quantity."))
		if not rows:
			frappe.throw(_("At least one material detail row is required."))

		for row in rows:
			if not (row.generated_serial_no or "").strip():
				frappe.throw(
					_("Row {0}: Serial No has not been generated. Save the plan first.").format(row.idx)
				)
			if flt(row.length_mm) <= 0 or flt(row.width_mm) <= 0:
				frappe.throw(
					_("Row {0}: Length and Width must be greater than zero.").format(row.idx)
				)
			if flt(row.thickness_mm) <= 0:
				frappe.throw(
					_("Row {0}: Thickness must be greater than zero.").format(row.idx)
				)

		if flt(self.total_area) <= 0:
			frappe.throw(_("Total Area must be greater than zero."))

		item = frappe.db.get_value(
			"Item",
			self.item_code,
			["has_serial_no", "is_stock_item"],
			as_dict=True,
		) or {}
		if not cint(item.get("is_stock_item")):
			frappe.throw(_("Item {0} must be a stock item.").format(frappe.bold(self.item_code)))
		if not cint(item.get("has_serial_no")):
			frappe.throw(
				_("Item {0} must have serial numbers enabled.").format(frappe.bold(self.item_code))
			)
		if frappe.db.exists(
			"Stock Entry",
			{"docstatus": ["<", 2], "remarks": self._stock_entry_remark()},
		):
			frappe.throw(_("A Stock Entry has already been created for this Material Receipt Plan."))


	def _accounting_dimension_fallback_docs(self):
		"""Return business objects that may carry Accounting Dimension values."""
		fallbacks = []
		if self.target_warehouse and frappe.db.exists("Warehouse", self.target_warehouse):
			fallbacks.append(frappe.get_cached_doc("Warehouse", self.target_warehouse))
		return fallbacks

	def _validate_accounting_dimensions(self):
		"""Fail before posting if a mandatory dimension cannot be resolved."""
		resolve_accounting_dimensions(
			self,
			self.company,
			fallback_docs=self._accounting_dimension_fallback_docs(),
			validate_mandatory=True,
		)

	# ------------------------------------------------------------------
	# Standard ERPNext stock posting
	# ------------------------------------------------------------------
	def _stock_entry_remark(self):
		return _("Created from Material Receipt Plan {0}").format(self.name)

	def _create_material_receipt(self):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Receipt"
		se.company = self.company
		if self.posting_date:
			se.posting_date = self.posting_date
		se.remarks = self._stock_entry_remark()
		#if se.custom_material_receipt_plan:
		se.custom_material_receipt_plan = self.name

		if hasattr(se, "set_basic_rate_manually"):
			se.set_basic_rate_manually = 1

		for row in self._rows():
			serial_no = (row.generated_serial_no or "").strip()
			if not serial_no:
				frappe.throw(
					_("Row {0}: generated Serial No is missing. Save the plan before submitting.").format(row.idx)
				)

			self._create_receipt_serial(serial_no, row)

			bundle_name = create_serial_batch_bundle(
				company=self.company,
				voucher_type="Stock Entry",
				item_code=self.item_code,
				warehouse=self.target_warehouse,
				serials=[serial_no],
				transaction_type="Inward",
			)

			item_row = se.append("items", {})
			item_row.item_code = self.item_code
			item_row.t_warehouse = self.target_warehouse
			item_row.qty = 1
			item_row.basic_rate = flt(row.basic_rate)
			item_row.valuation_rate = flt(row.basic_rate)
			item_row.serial_and_batch_bundle = bundle_name

			if hasattr(item_row, "set_basic_rate_manually"):
				item_row.set_basic_rate_manually = 1
			if hasattr(item_row, "incoming_rate"):
				item_row.incoming_rate = flt(row.basic_rate)
			if hasattr(item_row, "allow_zero_valuation_rate") and flt(row.basic_rate) == 0:
				item_row.allow_zero_valuation_rate = 1

			# Reuse existing standard/custom Stock Entry Detail fields.
			if hasattr(item_row, "custom_dimension_length_mm"):
				item_row.custom_dimension_length_mm = flt(row.length_mm)
			if hasattr(item_row, "custom_dimension_width_mm"):
				item_row.custom_dimension_width_mm = flt(row.width_mm)
			if hasattr(item_row, "custom_dimension_thickness_mm"):
				item_row.custom_dimension_thickness_mm = flt(row.thickness_mm)

			row.serial_no = serial_no

		# Use ERPNext Accounting Dimension configuration dynamically. Values are
		# resolved from the Material Receipt Plan first, then the target Warehouse,
		# then the company default configured on the Accounting Dimension. They are
		# copied to both Stock Entry and Stock Entry Detail before validation/GL.
		resolve_and_apply_stock_entry_dimensions(
			se,
			source_doc=self,
			fallback_docs=self._accounting_dimension_fallback_docs(),
			validate_mandatory=True,
		)

		se.flags.ignore_permissions = True
		se.insert()
		se.submit()

		# The plan is already submitted at this point. Persist links directly
		# without attempting another save on the submitted document.
		for row in self._rows():
			if row.name and row.serial_no:
				frappe.db.set_value(
					"Material Receipt Plan Serial",
					row.name,
					"serial_no",
					row.serial_no,
					update_modified=False,
				)

		if self.meta.has_field("stock_entry"):
			self.stock_entry = se.name
			frappe.db.set_value(
				"Material Receipt Plan",
				self.name,
				"stock_entry",
				se.name,
				update_modified=False,
			)

		return se

	def _create_receipt_serial(self, serial_no, row):
		if frappe.db.exists("Serial No", serial_no):
			frappe.throw(_("Serial No {0} already exists.").format(frappe.bold(serial_no)))

		serial_doc = frappe.new_doc("Serial No")
		serial_doc.name = serial_no
		serial_doc.serial_no = serial_no
		serial_doc.item_code = self.item_code
		serial_doc.company = self.company
		serial_doc.status = "Inactive"

		# These existing fields are exactly what Material Reconfiguration uses
		# when selecting available material candidates.
		if hasattr(serial_doc, "custom_dimension_length_mm"):
			serial_doc.custom_dimension_length_mm = flt(row.length_mm)
		if hasattr(serial_doc, "custom_dimension_width_mm"):
			serial_doc.custom_dimension_width_mm = flt(row.width_mm)
		if hasattr(serial_doc, "custom_dimension_thickness_mm"):
			serial_doc.custom_dimension_thickness_mm = flt(row.thickness_mm)
		if hasattr(serial_doc, "custom_surface_mm2"):
			serial_doc.custom_surface_mm2 = flt(row.length_mm) * flt(row.width_mm)
		if hasattr(serial_doc, "custom_perimeter_mm"):
			serial_doc.custom_perimeter_mm = 2 * (flt(row.length_mm) + flt(row.width_mm))
		if hasattr(serial_doc, "custom_material_status"):
			serial_doc.custom_material_status = "Full"
		if hasattr(serial_doc, "custom_root_serial_no"):
			serial_doc.custom_root_serial_no = serial_no
		if hasattr(serial_doc, "custom_parent_serial_no"):
			serial_doc.custom_parent_serial_no = None

		serial_doc.flags.ignore_permissions = True
		serial_doc.insert()
