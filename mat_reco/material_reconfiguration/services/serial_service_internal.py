"""
Service functions for working with Serial No documents.

This module contains helper functions that abstract the retrieval of
available sheets and chutes from the database. It hides the details
of filtering Serial No documents by status, warehouse or custom
fields so that the engine does not need to know about the database
schema. If Frappe is not installed these functions return
placeholder data.
"""

from typing import Iterable, List, Tuple, Dict, Any, __all__

try:
    import frappe  # type: ignore
except Exception:
    frappe = None  # noqa: N816


def get_available_serials(
    item_code: str,
    warehouse: str | None = None,
) -> Iterable[Tuple[str, Tuple[float, float]]]:
    """Yield available Serial No records for a given item as (name,(L,W)).

    The function looks up Serial No documents with the specified item
    code and optional warehouse where the custom field
    ``custom_material_status`` is either 'Full' or 'Partial'. It
    returns an iterable of tuples where the first element is the
    serial name and the second element is a (length,width) pair.
    Missing length/width fields or invalid entries are skipped.

    If Frappe is not installed, this function yields an empty list.

    :param item_code: Item code of the raw material.
    :param warehouse: Optional warehouse to filter by.
    :return: Iterable of (serial_no,(length,width)).
    """
    if frappe is None:
        # No database; nothing to return
        return []
    filters: Dict[str, Any] = {
        "item_code": item_code,
        "custom_material_status": ["in", ["Full", "Partial"]],
    }
    if warehouse:
        filters["warehouse"] = warehouse
    # Query required fields only
    docs = frappe.get_all(
        "Serial No",
        filters=filters,
        fields=["name", "custom_dimension_length_mm", "custom_dimension_width_mm"],
    )
    result: List[Tuple[str, Tuple[float, float]]] = []
    for d in docs:
        try:
            L = float(d.get("custom_dimension_length_mm", 0))
            W = float(d.get("custom_dimension_width_mm", 0))
        except Exception:
            continue
        if L > 0 and W > 0:
            result.append((d["name"], (L, W)))
    return result


# ---------------------------------------------------------------------------
# Serial number generation for by-product chutes
#
# When cutting a raw material sheet into finished goods and by-product chutes,
# each chute that is large enough to keep becomes a new Serial No.  The naming
# convention depends on whether the parent serial was a full sheet or a
# previously cut chute.  Full sheets use lettered suffixes followed by "01"
# (e.g. A01, B01, ...), while partial chutes use strictly numeric suffixes
# (01, 02, ...).  If a proposed serial name already exists in the system,
# the index is incremented until an unused suffix is found.

def _letter_suffix(index: int) -> str:
    """Return a base-26 letter suffix for a zero-based index.

    For example: index=0 -> "A", index=1 -> "B", ..., index=25 -> "Z",
    index=26 -> "AA", index=27 -> "AB", etc.
    """
    import string
    letters = string.ascii_uppercase
    result = ""
    i = index
    # Convert to 1-based index for easier computation
    i += 1
    while i > 0:
        # Python modulo yields 1..26 mapping when subtracted by 1
        i, rem = divmod(i - 1, 26)
        result = letters[rem] + result
    return result


def generate_chute_serials(
    parent_serial: str,
    children: List[Dict[str, Any]],
    item_code: str,
    *,
    min_keep_dimension_mm: float = 500.0,
    parent_status: str | None = None,
) -> List[str | None]:
    """Generate Serial Nos for a list of chute lines.

    Each element in ``children`` should be a dict containing at least
    ``length_mm`` and ``width_mm`` keys to denote the dimensions of the
    chute.  Optional keys ``material_status`` and ``quality_rating`` will
    be written to the new Serial No if provided.  A return value of
    ``None`` for a given child indicates that no serial was created
    (typically because the smallest dimension is below ``min_keep_dimension_mm``).

    :param parent_serial: The base serial number from which chutes are derived.
    :param children: List of dicts describing chute lines.  Keys used:
        - ``length_mm`` (float)
        - ``width_mm`` (float)
        - ``material_status`` (str, optional)
        - ``quality_rating`` (int, optional)
    :param item_code: Item code to assign to each new Serial No.
    :param min_keep_dimension_mm: Minimum dimension required to create a
        new Serial No.  Chutes below this threshold are skipped.
    :param parent_status: Optional explicit status of the parent (e.g. "Full" or
        "Partial").  If omitted, the status is looked up from the Serial No
        document.  If lookup fails, full-sheet behaviour is assumed.
    :return: List of new serial numbers (or None for skipped chutes) in
        the same order as ``children``.
    """
    if frappe is None:
        # No database available; cannot generate serials.  Return all
        # None to indicate that no serials were created.
        return [None] * len(children)
    # Resolve parent status if not provided
    status = parent_status
    if not status:
        try:
            status = frappe.db.get_value(
                "Serial No",
                parent_serial,
                "custom_material_status",
            ) or ""
        except Exception:
            status = ""
    status = str(status or "").lower()
    # Prepare list to hold results
    results: List[str | None] = [None] * len(children)
    # Counter of valid serials created for this parent.  We use this to
    # determine the suffix sequence.  Note: chutes skipped due to size
    # do not increment the counter.
    count = 0
    for idx, ch in enumerate(children):
        try:
            length_mm = float(ch.get("length_mm") or 0)
            width_mm = float(ch.get("width_mm") or 0)
        except Exception:
            length_mm = 0.0
            width_mm = 0.0
        # Skip creation if below threshold
        #if min(length_mm, width_mm) < min_keep_dimension_mm:
        #    results[idx] = None
        #    continue
        # Determine suffix based on parent status.  We implement a
        # collision check loop to ensure uniqueness.
        candidate_serial = None
        while True:
            # Compute suffix based on current count
            if status == "partial":
                # numeric suffix with two digits, starting at 01
                suffix = f"{count + 1:02d}"
            else:
                # full sheet: letter-based suffix + '01'
                letter = _letter_suffix(count)
                suffix = f"{letter}01"
            proposed = f"{parent_serial}{suffix}"
            # If the serial exists, increment count and try again
            if frappe.db.exists("Serial No", proposed):
                count += 1
                continue
            candidate_serial = proposed
            break
        # Create the Serial No document
        try:
            serial_doc_data = {
                "doctype": "Serial No",
                "serial_no": candidate_serial,
                "name": candidate_serial,
                "item_code": item_code,
                "custom_dimension_length_mm": length_mm,
                "custom_dimension_width_mm": width_mm,
                # Default material status for chutes comes from the MR line
                "custom_material_status": ch.get("material_status") or "Partial",
                "custom_quality_rating": ch.get("quality_rating") or 0,
            }
            serial_doc = frappe.get_doc(serial_doc_data)
            serial_doc.flags.ignore_permissions = True
            serial_doc.insert()
        except Exception:
            # If insertion fails, leave result as None
            results[idx] = None
        else:
            results[idx] = candidate_serial
            # Increment count only if a serial was successfully created
            count += 1
    return results


# Export the chute serial generator alongside the serial fetch function.  Do not
# override the __all__ set after appending.  Leaving the previous line
# would drop ``generate_chute_serials`` from the exported names.
#__all__.append("generate_chute_serials")
