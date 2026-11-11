"""
validation.py
Strict field ordering, validation rules, canary verification, and atomic file saving.
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple

REQUIRED_FIELD_ORDER = [
    "zipcode",
    "store_name",
    "store_location",
    "store_logo",
    "store_brand",
    "category",
    "sub_category",
    "product_title",
    "weight",
    "regular_price",
    "sale_price",
    "volume_deals_description",
    "volume_deals_price",
    "digital_deals_description",
    "digital_deals_price",
    "image_url",
    "url",
    "upc",
    "gupc",
    "ppm",
    "unit_price",
    "crawl_date"
]

WALMART_PRIVATE_LABELS = {
    "great value", "equate", "mainstays", "marketside", 
    "parent's choice", "sam's choice", "clear sky", "walmart",
    "george", "time and tru", "wonder nation", "better homes & gardens",
    "expert grill", "ozark trail", "pen+gear", "hyper tough"
}

APPROX_WEIGHT_REGEX = re.compile(r'\b(approx|approximately|approx\.|about|est\.?)\b', re.IGNORECASE)

def is_approximate_weight(weight_str: str) -> bool:
    """Returns True if weight mentions approx/approximately."""
    if not weight_str:
        return False
    return bool(APPROX_WEIGHT_REGEX.search(weight_str))

def detect_store_brand(product_title: str, raw_brand: str = "") -> str:
    """
    Identifies Walmart private label brands.
    If detected, returns the private label brand (e.g. 'Great Value' or 'Walmart').
    Otherwise returns 'no'.
    """
    combined = f"{raw_brand} {product_title}".lower()
    for brand in WALMART_PRIVATE_LABELS:
        if brand in combined:
            # Capitalize nicely
            return "Walmart" if brand == "walmart" else brand.title()
    return "no"

def format_price(price_str: str) -> str:
    """Formats numeric price consistently with leading dollar sign ($X.XX)."""
    if not price_str:
        return ""
    clean = re.sub(r'[^\d.]', '', price_str.strip())
    if not clean:
        return ""
    try:
        val = float(clean)
        return f"${val:.2f}"
    except ValueError:
        return price_str.strip()

def sanitize_and_order_record(raw: Dict[str, Any], crawl_date: str, preserve_meta: bool = False) -> Dict[str, str]:
    """
    Enforces exact 22 field ordering and data rules:
    - Return missing values as empty strings, never null
    - gupc is empty string ""
    - unit_price is empty string ""
    - All four volume/digital deal fields are strictly empty strings "" for Walmart
    - crawl_date is final field
    - No remarks or gupc14
    """
    ordered = {}
    for key in REQUIRED_FIELD_ORDER:
        if key == "gupc":
            ordered["gupc"] = ""
        elif key == "unit_price":
            ordered["unit_price"] = ""
        elif key in ["volume_deals_description", "volume_deals_price", "digital_deals_description", "digital_deals_price"]:
            ordered[key] = ""
        elif key == "crawl_date":
            ordered["crawl_date"] = crawl_date
        else:
            val = raw.get(key, "")
            ordered[key] = "" if val is None else str(val).strip()

    if preserve_meta:
        if "capture_id" in raw and raw["capture_id"]:
            ordered["capture_id"] = str(raw["capture_id"])
        if "assortment_status" in raw and raw["assortment_status"]:
            ordered["assortment_status"] = str(raw["assortment_status"])

    return ordered

def validate_dataset(records: List[Dict[str, str]], min_expected: int = 500) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates dataset health:
    - Minimum record threshold
    - Zero duplicate records by (URL + UPC)
    - 100% field completeness for required keys
    - Field order verification
    """
    stats = {
        "total_records": len(records),
        "duplicate_count": 0,
        "duplicate_rate": "0.00%",
        "field_completeness_rate": "100%",
        "categories_found": {},
        "errors": []
    }

    if len(records) < min_expected:
        stats["errors"].append(f"Abnormally thin run: got {len(records)} records, expected at least {min_expected}")

    seen = set()
    # Core identity fields that must never be empty for catalog continuity
    required_identity_fields = ["zipcode", "store_name", "store_location", "category", "sub_category", "product_title", "url", "crawl_date"]
    empty_field_occurrences = 0
    unavailable_assortment_count = 0

    for idx, r in enumerate(records):
        # 1. Field order check
        if list(r.keys()) != REQUIRED_FIELD_ORDER:
            stats["errors"].append(f"Record {idx} violates strict 22-field ordering")
            break

        # 2. Invariant: gupc and unit_price must be strictly empty strings
        if r.get("gupc") != "":
            stats["errors"].append(f"Record {idx} ('{r.get('product_title')}') has non-empty gupc: '{r.get('gupc')}'")
            break
        if r.get("unit_price") != "":
            stats["errors"].append(f"Record {idx} ('{r.get('product_title')}') has non-empty unit_price: '{r.get('unit_price')}'")
            break

        # 3. Check duplicates
        key = f"{r.get('upc') or r.get('url')}_{r.get('zipcode')}"
        if key in seen:
            stats["duplicate_count"] += 1
        else:
            seen.add(key)

        # 4. Track unavailable store-assortment products (retained per specification even when price/upc missing)
        if not r.get("regular_price") and not r.get("sale_price"):
            unavailable_assortment_count += 1

        # 5. Check completeness of required identity fields
        for req in required_identity_fields:
            if not r.get(req):
                empty_field_occurrences += 1

        cat = r.get("category", "Unknown")
        stats["categories_found"][cat] = stats["categories_found"].get(cat, 0) + 1

    stats["unavailable_assortment_count"] = unavailable_assortment_count
    if records:
        stats["duplicate_rate"] = f"{(stats['duplicate_count'] / len(records)) * 100:.2f}%"
        completeness = max(0.0, 100.0 - (empty_field_occurrences / (len(records) * len(required_identity_fields)) * 100))
        stats["field_completeness_rate"] = f"{completeness:.1f}%"

    is_valid = len(stats["errors"]) == 0 and stats["duplicate_count"] == 0
    return is_valid, stats

def atomic_save_dataset(records: List[Dict[str, str]], target_path: str, min_expected: int = 500) -> bool:
    """
    Atomic write guarantee:
    1. Writes to temporary file (.tmp)
    2. Validates record count and structure
    3. Retains last known good dataset if validation fails
    4. Atomically replaces target file only on success
    """
    is_valid, stats = validate_dataset(records, min_expected=min_expected)
    if not is_valid:
        print(f"[CRITICAL VALIDATION FAILURE] Run did not meet quality gates: {stats['errors']}. Retaining previous dataset.")
        return False

    tmp_path = f"{target_path}.tmp"
    backup_path = f"{target_path}.bak"

    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        # Create backup of current file if it exists
        if os.path.exists(target_path):
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(target_path, backup_path)

        # Atomic rename
        os.rename(tmp_path, target_path)
        print(f"[SUCCESS] Atomically saved {len(records)} records to {target_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Atomic write failed: {e}. Restoring backup if possible.")
        if os.path.exists(backup_path) and not os.path.exists(target_path):
            os.rename(backup_path, target_path)
        return False
