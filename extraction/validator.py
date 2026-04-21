import logging
import re

logger = logging.getLogger(__name__)

TOLERANCE = 1.0


def _is_numeric(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def validate(data: dict) -> list[dict]:
    """Run all 7 business rules against extracted invoice data.

    Returns a list of failure dicts. Empty list means all rules passed.
    Each failure has: rule, message, fields, expected, actual, auto_fixed.
    """
    failures = []
    failures.extend(_rule_gst_format(data))
    failures.extend(_rule_cgst_equals_sgst(data))
    failures.extend(_rule_discount_arithmetic(data))
    failures.extend(_rule_tax_percentage(data))
    failures.extend(_rule_net_total(data))
    failures.extend(_rule_date_format(data))
    failures.extend(_rule_line_item_arithmetic(data))
    return failures


def auto_fix(data: dict, failures: list[dict]) -> tuple[dict, list[dict]]:
    """Apply automatic corrections where possible. Returns (fixed_data, updated_failures)."""
    data = dict(data)
    data["line_items"] = list(data.get("line_items", []))
    updated = []

    for f in failures:
        if f["rule"] == "cgst_equals_sgst" and not f.get("auto_fixed"):
            data, fixed = _fix_cgst_sgst(data, f)
            if fixed:
                f = dict(f, auto_fixed=True)
        updated.append(f)

    return data, updated


def build_correction_prompt(data: dict, failures: list[dict]) -> str:
    """Build a targeted prompt that tells the VLM what it got wrong."""
    from .prompts import EXTRACTION_PROMPT

    unfixed = [f for f in failures if not f.get("auto_fixed")]
    if not unfixed:
        return EXTRACTION_PROMPT

    prev_values = (
        f"  invoice_no={data.get('invoice_no')}, date={data.get('date')},\n"
        f"  customer_gstin={data.get('customer_gstin')},\n"
        f"  gross_total={data.get('gross_total')}, discount={data.get('discount')},\n"
        f"  total_after_discount={data.get('total_after_discount')},\n"
        f"  sgst={data.get('sgst')}, cgst={data.get('cgst')}, net_total={data.get('net_total')}"
    )

    issues = []
    for f in unfixed:
        issues.append(f"- {f['message']}")

    issues_block = "\n".join(issues)

    return (
        f"{EXTRACTION_PROMPT}\n\n"
        f"IMPORTANT CORRECTION NOTICE:\n"
        f"A previous extraction of this same invoice produced these values:\n"
        f"{prev_values}\n\n"
        f"However, the following validation checks FAILED:\n"
        f"{issues_block}\n\n"
        f"Please re-examine the image very carefully, paying special attention to the "
        f"fields mentioned above. The handwritten numbers may have been misread.\n"
        f"Remember:\n"
        f"- The date is handwritten with VERTICAL LINES as day/month/year separators, "
        f"NOT the digit 1. A vertical bar | looks like 1 but is a separator.\n"
        f"- GST number is exactly 15 alphanumeric characters starting with 27.\n"
        f"- CGST and SGST are always equal.\n"
        f"- For each line item, Qty * Rate = Amount.\n"
        f"- Gross Total - Discount = Total After Discount.\n"
        f"- SGST and CGST are either 2.5% or 6% of Total After Discount.\n"
        f"- Net Total = Total After Discount + SGST + CGST.\n\n"
        f"Return ONLY the corrected JSON object."
    )


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

def _rule_gst_format(data: dict) -> list[dict]:
    gstin = data.get("customer_gstin")
    if gstin is None or gstin == "error":
        return []

    gstin_str = str(gstin).strip()
    clean = re.sub(r"[^A-Za-z0-9]", "", gstin_str)

    if len(clean) == 15 and clean[:2] == "27" and clean.isalnum():
        if clean != gstin_str:
            data["customer_gstin"] = clean
        return []

    return [{
        "rule": "gst_format",
        "message": (
            f"Customer GSTIN '{gstin_str}' is invalid. "
            f"Must be exactly 15 alphanumeric characters starting with '27'."
        ),
        "fields": ["customer_gstin"],
        "expected": "15 alphanumeric chars starting with 27",
        "actual": gstin_str,
        "auto_fixed": False,
    }]


def _rule_cgst_equals_sgst(data: dict) -> list[dict]:
    sgst = data.get("sgst")
    cgst = data.get("cgst")

    if not _is_numeric(sgst) or not _is_numeric(cgst):
        return []

    if abs(sgst - cgst) <= TOLERANCE:
        return []

    return [{
        "rule": "cgst_equals_sgst",
        "message": (
            f"CGST ({cgst}) and SGST ({sgst}) should be equal but differ."
        ),
        "fields": ["sgst", "cgst"],
        "expected": "sgst == cgst",
        "actual": f"sgst={sgst}, cgst={cgst}",
        "auto_fixed": False,
    }]


def _fix_cgst_sgst(data: dict, failure: dict) -> tuple[dict, bool]:
    """Pick the tax value closest to a valid percentage of total_after_discount."""
    sgst = data.get("sgst")
    cgst = data.get("cgst")
    tad = data.get("total_after_discount")

    if not _is_numeric(sgst) or not _is_numeric(cgst):
        return data, False

    if _is_numeric(tad) and tad > 0:
        expected_2_5 = round(tad * 0.025, 2)
        expected_6 = round(tad * 0.06, 2)
        candidates = [expected_2_5, expected_6]

        best_sgst = min(candidates, key=lambda c: abs(c - sgst))
        best_cgst = min(candidates, key=lambda c: abs(c - cgst))

        dist_sgst = abs(best_sgst - sgst)
        dist_cgst = abs(best_cgst - cgst)

        if dist_sgst <= dist_cgst:
            chosen = sgst
        else:
            chosen = cgst

        best_match = min(candidates, key=lambda c: abs(c - chosen))
        if abs(best_match - chosen) <= TOLERANCE:
            chosen = best_match
    else:
        chosen = sgst

    logger.info("Auto-fixing CGST/SGST: both set to %s (was sgst=%s, cgst=%s)", chosen, sgst, cgst)
    data["sgst"] = chosen
    data["cgst"] = chosen
    return data, True


def _rule_discount_arithmetic(data: dict) -> list[dict]:
    gross = data.get("gross_total")
    discount = data.get("discount")
    tad = data.get("total_after_discount")

    if not all(_is_numeric(v) for v in (gross, discount, tad)):
        return []

    expected = gross - discount
    if abs(expected - tad) <= TOLERANCE:
        return []

    return [{
        "rule": "discount_arithmetic",
        "message": (
            f"Gross Total ({gross}) - Discount ({discount}) = {expected}, "
            f"but Total After Discount is {tad}."
        ),
        "fields": ["gross_total", "discount", "total_after_discount"],
        "expected": expected,
        "actual": tad,
        "auto_fixed": False,
    }]


def _rule_tax_percentage(data: dict) -> list[dict]:
    tad = data.get("total_after_discount")
    sgst = data.get("sgst")
    cgst = data.get("cgst")

    if not _is_numeric(tad) or tad <= 0:
        return []

    failures = []
    expected_2_5 = round(tad * 0.025, 2)
    expected_6 = round(tad * 0.06, 2)

    for name, val in [("sgst", sgst), ("cgst", cgst)]:
        if not _is_numeric(val):
            continue
        matches_2_5 = abs(val - expected_2_5) <= TOLERANCE
        matches_6 = abs(val - expected_6) <= TOLERANCE
        if not matches_2_5 and not matches_6:
            failures.append({
                "rule": "tax_percentage",
                "message": (
                    f"{name.upper()} ({val}) is neither 2.5% ({expected_2_5}) "
                    f"nor 6% ({expected_6}) of Total After Discount ({tad})."
                ),
                "fields": [name, "total_after_discount"],
                "expected": f"2.5%={expected_2_5} or 6%={expected_6}",
                "actual": val,
                "auto_fixed": False,
            })

    return failures


def _rule_net_total(data: dict) -> list[dict]:
    tad = data.get("total_after_discount")
    sgst = data.get("sgst")
    cgst = data.get("cgst")
    net = data.get("net_total")

    if not all(_is_numeric(v) for v in (tad, sgst, cgst, net)):
        return []

    expected = tad + sgst + cgst
    if abs(expected - net) <= TOLERANCE:
        return []

    return [{
        "rule": "net_total",
        "message": (
            f"Total After Discount ({tad}) + SGST ({sgst}) + CGST ({cgst}) = {expected}, "
            f"but Net Total is {net}."
        ),
        "fields": ["total_after_discount", "sgst", "cgst", "net_total"],
        "expected": expected,
        "actual": net,
        "auto_fixed": False,
    }]


def _rule_date_format(data: dict) -> list[dict]:
    date_val = data.get("date")
    if date_val is None or date_val == "error":
        return []

    date_str = str(date_val).strip()

    separators = re.findall(r"[/\-.|]", date_str)
    if len(separators) < 2:
        return [{
            "rule": "date_format",
            "message": (
                f"Date '{date_str}' does not have clear day/month/year separators. "
                f"The handwritten date uses vertical lines (|) as separators which "
                f"may be confused with the digit 1."
            ),
            "fields": ["date"],
            "expected": "dd/mm/yy or dd-mm-yy format",
            "actual": date_str,
            "auto_fixed": False,
        }]

    parts = re.split(r"[/\-.|]+", date_str)
    if len(parts) >= 2:
        try:
            day = int(parts[0])
            month_str = parts[1]
            month_names = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            if month_str.lower()[:3] in month_names:
                month = month_names[month_str.lower()[:3]]
            else:
                month = int(month_str)

            if day < 1 or day > 31 or month < 1 or month > 12:
                return [{
                    "rule": "date_format",
                    "message": (
                        f"Date '{date_str}' has invalid day ({day}) or month ({month}). "
                        f"The vertical line separator may have been read as digit 1."
                    ),
                    "fields": ["date"],
                    "expected": "day 1-31, month 1-12",
                    "actual": f"day={day}, month={month}",
                    "auto_fixed": False,
                }]
        except (ValueError, IndexError):
            pass

    return []


def _rule_line_item_arithmetic(data: dict) -> list[dict]:
    failures = []
    for i, item in enumerate(data.get("line_items", [])):
        qty = item.get("qty")
        rate = item.get("rate")
        amount = item.get("amount")

        if not all(_is_numeric(v) for v in (qty, rate, amount)):
            continue

        expected = qty * rate
        if abs(expected - amount) <= TOLERANCE:
            continue

        desc = item.get("description") or item.get("size") or f"item #{i+1}"
        failures.append({
            "rule": "line_item_arithmetic",
            "message": (
                f"Line item '{desc}' (size {item.get('size')}): "
                f"Qty ({qty}) * Rate ({rate}) = {expected}, but Amount is {amount}."
            ),
            "fields": [f"line_items[{i}].qty", f"line_items[{i}].rate", f"line_items[{i}].amount"],
            "expected": expected,
            "actual": amount,
            "auto_fixed": False,
        })

    return failures
