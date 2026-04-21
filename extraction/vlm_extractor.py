import json
import logging
import time

import ollama

from .prompts import EXTRACTION_PROMPT, MODEL_NAME
from .validator import validate, auto_fix, build_correction_prompt

logger = logging.getLogger(__name__)

EMPTY_RESULT = {
    "invoice_no": None,
    "date": None,
    "customer_name": None,
    "customer_address": None,
    "customer_gstin": None,
    "gross_total": None,
    "discount": None,
    "total_after_discount": None,
    "sgst": None,
    "cgst": None,
    "net_total": None,
    "line_items": [],
}


def extract_invoice(
    image_path: str,
    max_retries: int = 2,
    validation_retries: int = 2,
) -> dict:
    """Extract invoice data with validation and targeted re-extraction.

    First performs a standard extraction, then validates the result. If
    validation fails, applies auto-fixes where possible and sends a
    targeted correction prompt for remaining issues, up to
    ``validation_retries`` times.

    The returned dict always contains a ``_discrepancies`` key with any
    validation failures that could not be resolved.
    """
    data = _raw_extract(image_path, EXTRACTION_PROMPT, max_retries)
    if _is_empty(data):
        data["_discrepancies"] = []
        return data

    for attempt in range(validation_retries):
        failures = validate(data)

        if not failures:
            logger.info("All validations passed for %s", image_path)
            data["_discrepancies"] = []
            return data

        data, failures = auto_fix(data, failures)

        unfixed = [f for f in failures if not f.get("auto_fixed")]
        if not unfixed:
            logger.info(
                "All issues auto-fixed for %s (attempt %d)",
                image_path, attempt + 1,
            )
            data["_discrepancies"] = []
            return data

        logger.info(
            "Validation attempt %d for %s: %d issue(s) remain, re-extracting",
            attempt + 1, image_path, len(unfixed),
        )

        correction_prompt = build_correction_prompt(data, failures)
        new_data = _raw_extract(image_path, correction_prompt, max_retries=1)

        if not _is_empty(new_data):
            data = new_data

    final_failures = validate(data)
    data, final_failures = auto_fix(data, final_failures)
    remaining = [f for f in final_failures if not f.get("auto_fixed")]

    if remaining:
        logger.warning(
            "Validation retries exhausted for %s, %d issue(s) remain: %s",
            image_path,
            len(remaining),
            "; ".join(f["rule"] for f in remaining),
        )
    else:
        logger.info("All validations passed for %s after retries", image_path)

    data["_discrepancies"] = remaining
    return data


def _raw_extract(image_path: str, prompt: str, max_retries: int = 2) -> dict:
    """Send an image + prompt to the VLM and return normalized data."""
    for attempt in range(max_retries + 1):
        try:
            start = time.time()
            response = ollama.chat(
                model=MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [image_path],
                }],
                format="json",
            )
            elapsed = time.time() - start
            logger.info("VLM inference took %.1fs for %s", elapsed, image_path)

            raw = response["message"]["content"]
            data = json.loads(raw)
            return _normalize(data)

        except json.JSONDecodeError:
            logger.warning(
                "JSON parse failed on attempt %d for %s", attempt + 1, image_path
            )
            if attempt == max_retries:
                logger.error("All retries exhausted for %s, returning empty result", image_path)
                return dict(EMPTY_RESULT)

        except Exception as e:
            logger.error("VLM extraction failed for %s: %s", image_path, e)
            return dict(EMPTY_RESULT)

    return dict(EMPTY_RESULT)


def _is_empty(data: dict) -> bool:
    """Check if extraction returned essentially nothing."""
    for key, default in EMPTY_RESULT.items():
        if key == "line_items":
            if data.get("line_items"):
                return False
        elif data.get(key) is not None:
            return False
    return True


def _normalize(data: dict) -> dict:
    """Ensure the result dict has all expected keys with correct types."""
    result = dict(EMPTY_RESULT)

    for key in EMPTY_RESULT:
        if key == "line_items":
            continue
        if key in data:
            result[key] = _clean_null(data[key])

    numeric_fields = [
        "gross_total", "discount", "total_after_discount",
        "sgst", "cgst", "net_total",
    ]
    for field in numeric_fields:
        val = result[field]
        if val is not None:
            if isinstance(val, str) and val.strip().lower().startswith("error"):
                result[field] = "error"
            else:
                try:
                    result[field] = float(val)
                except (ValueError, TypeError):
                    result[field] = "error"

    raw_items = data.get("line_items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = {
            "hsn_code": _clean_null(item.get("hsn_code")),
            "description": _clean_null(item.get("description")),
            "size": _clean_null(item.get("size")),
            "qty": _to_number(item.get("qty")),
            "rate": _to_number(item.get("rate")),
            "amount": _to_number(item.get("amount")),
        }
        has_data = (
            normalized["description"]
            or normalized["amount"] is not None
            or normalized["qty"] is not None
        )
        if has_data:
            items.append(normalized)

    result["line_items"] = items
    return result


def _clean_null(val):
    """Convert string 'null'/'None'/'' to actual None."""
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower() in ("null", "none", "n/a", ""):
        return None
    return val


def _to_number(val):
    if val is None:
        return None
    val = _clean_null(val)
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower().startswith("error"):
        return "error"
    try:
        return float(val)
    except (ValueError, TypeError):
        return "error"
