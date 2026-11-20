"""
walmart_scraper.py
Production-Ready Walmart Scraper for Microsoft Azure
Location-Specific • Multi-Location • Azure Ready
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
"""

import asyncio
import csv
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
except ImportError:
    async_playwright = None
    Page = Any  # type: ignore
    BrowserContext = Any  # type: ignore

# Ensure scraper directory is in Python path for standalone or package execution
_scraper_dir = os.path.dirname(os.path.abspath(__file__))
if _scraper_dir not in sys.path:
    sys.path.insert(0, _scraper_dir)

try:
    from config import StoreConfig, ScraperSettings, DEFAULT_STORES, get_settings
    from validation import (
        sanitize_and_order_record,
        is_approximate_weight,
        detect_store_brand,
        format_price,
        validate_dataset,
        REQUIRED_FIELD_ORDER
    )
    from checkpoint_manager import CheckpointManager, sanitize_captured_request, compute_routes_signature
    from azure_integration import resolve_key_vault_proxy_secrets, ensure_proxy_credentials_ready, AzureBlobPublisher
except ImportError:
    from scraper.config import StoreConfig, ScraperSettings, DEFAULT_STORES, get_settings
    from scraper.validation import (
        sanitize_and_order_record,
        is_approximate_weight,
        detect_store_brand,
        format_price,
        validate_dataset,
        REQUIRED_FIELD_ORDER
    )
    from scraper.checkpoint_manager import CheckpointManager, sanitize_captured_request, compute_routes_signature
    from scraper.azure_integration import resolve_key_vault_proxy_secrets, ensure_proxy_credentials_ready, AzureBlobPublisher

# Recognized affirmative fulfillment modes (reject substrings like NOT_PICKUP or PICKUP_UNAVAILABLE)
RECOGNIZED_AFFIRMATIVE_PICKUP_MODES = {
    "PICKUP",
    "STORE_PICKUP",
    "IN_STORE_PICKUP",
    "CURBSIDE_PICKUP",
    "GROCERY_PICKUP"
}

NON_PICKUP_FULFILLMENT_MODES = {
    "SHIPPING",
    "DELIVERY",
    "UNSCHEDULED_DELIVERY",
    "SHIP_TO_HOME",
    "FC_DELIVERY",
    "TWO_DAY_SHIPPING",
}

def is_exact_affirmative_fulfillment(mode: Any, allowed_modes: Optional[Set[str]] = None) -> bool:
    """
    Validates exact affirmative fulfillment mode.
    Strictly rejects substring false-positives such as 'NOT_PICKUP' or 'PICKUP_UNAVAILABLE'.
    """
    if not mode:
        return False
    mode_str = str(mode).strip().upper()
    if any(neg in mode_str for neg in ["NOT", "UNAVAILABLE", "NO_PICKUP", "DISABLED", "NONE"]):
        return False
    valid = allowed_modes or RECOGNIZED_AFFIRMATIVE_PICKUP_MODES
    return mode_str in valid

def is_affirmative_availability(avail: Any) -> bool:
    """
    Requires affirmative availability for pickup.
    Rejects missing (None), boolean False, string 'false', '0', 'unavailable', or empty flags.
    """
    if avail is True:
        return True
    if isinstance(avail, str):
        return avail.strip().lower() in {"true", "1", "yes", "available", "in_stock"}
    if isinstance(avail, (int, float)) and avail == 1:
        return True
    return False

STORE_ID_KEYS = (
    "storeId",
    "pickupStoreId",
    "fulfillmentStoreId",
    "nodeId",
    "store_id",
    "storeNumber",
    "pickupNodeId",
    "fulfillmentNodeId",
)

VARIANT_ID_KEYS = (
    "variantId",
    "usVariantId",
    "selectedVariantId",
    "canonicalVariantId",
    "primaryVariantId",
)


def _norm_id(val: Any) -> str:
    if val is None or isinstance(val, (bool, dict, list)):
        return ""
    s = str(val).strip()
    if s.lower() in {"", "none", "null", "undefined"}:
        return ""
    return s


def collect_distinct_store_ids(
    obj: Any,
    exclude_price_info: bool = False,
) -> Set[str]:
    """
    Collects ALL non-empty store identifiers across direct and nested store/fulfillment
    keys without short-circuiting so conflicting store evidence (e.g. storeId='3891'
    alongside pickupStoreId='9999') is always detected and rejected.
    """
    stores: Set[str] = set()
    if not isinstance(obj, dict):
        return stores

    for k in STORE_ID_KEYS:
        sid = _norm_id(obj.get(k))
        if sid:
            stores.add(sid)

    nested_keys = ["store", "pickupStore", "fulfillmentStore", "fulfillment", "location", "deliveryStore"]
    if not exclude_price_info:
        nested_keys.extend(["priceInfo", "currentPrice"])

    for nk in nested_keys:
        sub = obj.get(nk)
        if not isinstance(sub, dict):
            continue
        for k in STORE_ID_KEYS:
            sid = _norm_id(sub.get(k))
            if sid:
                stores.add(sid)
        if nk in {"store", "pickupStore", "fulfillmentStore", "deliveryStore"}:
            sid = _norm_id(sub.get("id"))
            if sid:
                stores.add(sid)
        if nk == "priceInfo" and isinstance(sub.get("currentPrice"), dict):
            for k in STORE_ID_KEYS:
                sid = _norm_id(sub["currentPrice"].get(k))
                if sid:
                    stores.add(sid)

    return stores


def extract_distinct_variant_ids(obj: Any) -> Set[str]:
    """Extracts distinct variant identifiers from an item or offer dict."""
    variants: Set[str] = set()
    if not isinstance(obj, dict):
        return variants
    for k in VARIANT_ID_KEYS:
        vid = _norm_id(obj.get(k))
        if vid:
            variants.add(vid)
    v_sub = obj.get("variant")
    if isinstance(v_sub, dict):
        for k in ("variantId", "usVariantId", "id"):
            vid = _norm_id(v_sub.get(k))
            if vid:
                variants.add(vid)
    return variants


def extract_all_item_variant_ids(itm: Dict[str, Any]) -> Set[str]:
    """Extracts all declared variant IDs for an item, including variants/selectedVariants lists."""
    variants = extract_distinct_variant_ids(itm)
    for list_key in ("variants", "variantOptions", "selectedVariants"):
        val = itm.get(list_key)
        if isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict):
                    variants.update(extract_distinct_variant_ids(entry))
                    eid = _norm_id(entry.get("id"))
                    if eid:
                        variants.add(eid)
                else:
                    eid = _norm_id(entry)
                    if eid:
                        variants.add(eid)
        elif isinstance(val, dict):
            variants.update(extract_distinct_variant_ids(val))
    return variants


def is_walmart_first_party_seller(obj: Any) -> bool:
    """
    Verifies seller identity belongs to Walmart first-party retail when seller fields exist.
    Rejects explicit 3P / Marketplace / non-Walmart sellers.
    """
    if not isinstance(obj, dict):
        return True
    if obj.get("isThirdParty") is True or obj.get("marketplaceSeller") is True:
        return False
    sold_by_wmt = obj.get("soldByWalmart")
    if sold_by_wmt is False or (isinstance(sold_by_wmt, str) and sold_by_wmt.strip().lower() in {"false", "0", "no"}):
        return False

    seller_obj = obj.get("seller") if isinstance(obj.get("seller"), dict) else {}
    seller_type = str(obj.get("sellerType") or seller_obj.get("type") or "").strip().upper()
    if any(tag in seller_type for tag in ("3P", "THIRD_PARTY", "MARKETPLACE", "PRO_SELLER", "EXTERNAL")):
        return False

    seller_name = str(
        obj.get("sellerName")
        or obj.get("sellerDisplayName")
        or seller_obj.get("name")
        or seller_obj.get("displayName")
        or ""
    ).strip()
    if seller_name and "walmart" not in seller_name.lower():
        return False

    seller_id = str(
        obj.get("sellerId")
        or obj.get("catalogSellerId")
        or seller_obj.get("id")
        or ""
    ).strip()
    if seller_id and seller_id.lower() not in {"0", "walmart", "walmart.com", "wmt"}:
        if not seller_name or "walmart" not in seller_name.lower():
            return False

    return True


def has_affirmative_walmart_first_party_seller(obj: Any) -> bool:
    """
    Requires affirmative, explicit evidence that an offer belongs to Walmart first-party (1P).
    Absent seller metadata fails closed (returns False).
    """
    if not isinstance(obj, dict):
        return False
    if not is_walmart_first_party_seller(obj):
        return False

    sold_by_wmt = obj.get("soldByWalmart")
    if sold_by_wmt is True or (isinstance(sold_by_wmt, str) and sold_by_wmt.strip().lower() in {"true", "1", "yes"}):
        return True

    seller_obj = obj.get("seller") if isinstance(obj.get("seller"), dict) else {}
    seller_type = str(obj.get("sellerType") or seller_obj.get("type") or "").strip().upper()
    if seller_type in {"FIRST_PARTY", "1P", "WALMART", "WMT", "WALMART_1P"}:
        return True

    seller_name = str(
        obj.get("sellerName")
        or obj.get("sellerDisplayName")
        or seller_obj.get("name")
        or seller_obj.get("displayName")
        or ""
    ).strip().lower()
    if "walmart" in seller_name:
        return True

    seller_id = str(
        obj.get("sellerId")
        or obj.get("catalogSellerId")
        or seller_obj.get("id")
        or ""
    ).strip().lower()
    if seller_id in {"0", "walmart", "walmart.com", "wmt"}:
        return True

    return False


def extract_source_upc(itm: Dict[str, Any]) -> str:
    """Extracts 11-14 digit retailer UPC/GTIN from item payload dictionaries."""
    if not isinstance(itm, dict):
        return ""
    sources = [itm]
    for sub_key in ("canonicalProduct", "product", "productInfo", "identifiers"):
        sub_obj = itm.get(sub_key)
        if isinstance(sub_obj, dict):
            sources.append(sub_obj)
    for src in sources:
        for k in ("upc", "gtin12", "gtin13", "gtin", "gtin14", "barcode"):
            raw_val = src.get(k)
            if raw_val is None:
                continue
            cleaned = re.sub(r"[\s\-]", "", str(raw_val).strip())
            if re.match(r"^\d{11,14}$", cleaned):
                return cleaned
    return ""


def _extract_offer_price_string(obj: Dict[str, Any]) -> str:
    """Extracts the displayed offer price string without guessing from unrelated subtrees."""
    if not isinstance(obj, dict):
        return ""
    p_info = obj.get("priceInfo") if isinstance(obj.get("priceInfo"), dict) else {}
    curr_from_p = p_info.get("currentPrice") if isinstance(p_info.get("currentPrice"), dict) else {}
    curr_direct = obj.get("currentPrice") if isinstance(obj.get("currentPrice"), dict) else {}

    for val in (
        p_info.get("linePrice"),
        curr_from_p.get("priceString"),
        curr_from_p.get("price"),
        curr_direct.get("priceString"),
        curr_direct.get("price"),
        obj.get("linePrice"),
        obj.get("priceString"),
        obj.get("price"),
    ):
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def select_bound_pickup_offer(
    itm: Dict[str, Any],
    page_store_id: Optional[str],
    page_fulfillment_mode: Optional[str],
    target_store_id: str,
) -> Dict[str, Any]:
    """
    Strictly binds a priced offer via traceable links to:
    - item ID (matching usItemId/itemId)
    - variant ID (matching item variant declarations when specified)
    - offer ID (non-empty, matching selectedOfferId when specified)
    - affirmative first-party Walmart seller
    - affirmative pickup fulfillment mode & availability (without conflicting modes)
    - unambiguous, non-conflicting target store ID (never falling back to page store for bare nested offers)
    Refuses top-level priceInfo fallback when nested offer containers exist without a traceable match.
    """
    itm_id = _norm_id(itm.get("usItemId") or itm.get("id"))
    source_upc = extract_source_upc(itm)
    f_info = itm.get("fulfillment") if isinstance(itm.get("fulfillment"), dict) else {}
    p_info = itm.get("priceInfo") if isinstance(itm.get("priceInfo"), dict) else {}

    item_variant_ids = extract_all_item_variant_ids(itm)
    item_selected_variant = _norm_id(
        itm.get("selectedVariantId") or itm.get("variantId") or itm.get("usVariantId") or itm.get("canonicalVariantId")
    )
    item_selected_offer = _norm_id(itm.get("selectedOfferId") or itm.get("offerId"))

    item_pickup_avail = f_info.get("pickupAvailable") if f_info else None
    item_instore_stock = f_info.get("inStoreStock") if f_info else None
    if item_pickup_avail is None and isinstance(itm.get("availabilityStatusV2"), dict):
        avail_val = str(itm["availabilityStatusV2"].get("value") or "").upper()
        if avail_val == "IN_STOCK":
            item_pickup_avail = True
            item_instore_stock = True
        elif avail_val in {"OUT_OF_STOCK", "NOT_AVAILABLE"}:
            item_pickup_avail = False
            item_instore_stock = False

    # Collect nested candidate offers if provided
    has_nested_container = False
    candidate_offers: List[Dict[str, Any]] = []
    for key in ("offers", "fulfillmentOptions", "fulfillmentOptionList", "fulfillmentSummaries"):
        val = itm.get(key)
        if isinstance(val, list):
            has_nested_container = True
            candidate_offers.extend([o for o in val if isinstance(o, dict)])
    for key in ("offer", "offerInfo"):
        val = itm.get(key)
        if isinstance(val, dict):
            has_nested_container = True
            candidate_offers.append(val)
    if f_info:
        for key in ("pickupOptions", "offers", "fulfillmentOptions"):
            val = f_info.get(key)
            if isinstance(val, list):
                has_nested_container = True
                candidate_offers.extend([o for o in val if isinstance(o, dict)])
        if isinstance(f_info.get("pickup"), dict):
            has_nested_container = True
            candidate_offers.append(f_info["pickup"])
    if isinstance(p_info.get("offer"), dict):
        has_nested_container = True
        candidate_offers.append(p_info["offer"])
    if isinstance(p_info.get("offers"), list):
        has_nested_container = True
        candidate_offers.extend([o for o in p_info["offers"] if isinstance(o, dict)])

    item_seller_ok = is_walmart_first_party_seller(itm)
    itm_direct_stores = collect_distinct_store_ids(itm, exclude_price_info=True)

    if has_nested_container:
        itm_store_conflict = len(itm_direct_stores) > 1
        saw_offer_store_conflict = False
        if not itm_store_conflict and item_seller_ok:
            for off in candidate_offers:
                # 1. Traceable Item ID link (must explicitly exist on offer and match item)
                off_us_item = _norm_id(off.get("usItemId"))
                off_alt_item = _norm_id(off.get("itemId"))
                if off_us_item and off_alt_item and off_us_item != off_alt_item:
                    continue
                off_item_id = off_us_item or off_alt_item
                if not off_item_id or not itm_id or off_item_id != itm_id:
                    continue

                # 2. Traceable Offer ID link (must exist on offer and match selectedOfferId if set)
                off_id = _norm_id(off.get("offerId") or off.get("id"))
                if not off_id:
                    continue
                if item_selected_offer and off_id != item_selected_offer:
                    continue

                # 3. Traceable Variant ID link (must exist unambiguously on offer and match item variant if declared)
                off_variants = extract_distinct_variant_ids(off)
                if len(off_variants) != 1:
                    continue
                off_variant_id = next(iter(off_variants))
                if item_selected_variant and off_variant_id != item_selected_variant:
                    continue
                if item_variant_ids and off_variant_id not in item_variant_ids:
                    continue

                # 4. Affirmative First-Party Walmart Seller on offer itself (missing seller fails closed)
                off_f_sub = off.get("fulfillment") if isinstance(off.get("fulfillment"), dict) else {}
                if not has_affirmative_walmart_first_party_seller(off) or (off_f_sub and not is_walmart_first_party_seller(off_f_sub)):
                    continue

                # 5. Affirmative Pickup Mode without conflicting non-pickup modes
                off_modes = [
                    str(m).strip()
                    for m in (
                        off.get("fulfillmentMode"),
                        off.get("fulfillmentType"),
                        off.get("fulfillmentOption"),
                        off.get("mode"),
                        off_f_sub.get("fulfillmentMode"),
                        off_f_sub.get("fulfillmentType"),
                    )
                    if m is not None and str(m).strip()
                ]
                if not off_modes or not all(is_exact_affirmative_fulfillment(m) for m in off_modes):
                    continue
                off_fulfill = off_modes[0]

                # 6. Affirmative Pickup Availability
                if off.get("pickupAvailable") is False or off.get("available") is False or off_f_sub.get("pickupAvailable") is False:
                    continue
                off_avail = off.get("pickupAvailable")
                if off_avail is None:
                    off_avail = off.get("available")
                if off_avail is None and off_f_sub:
                    off_avail = off_f_sub.get("pickupAvailable")
                if off_avail is None:
                    off_avail = item_pickup_avail
                if not is_affirmative_availability(off_avail):
                    continue

                # 7. Unambiguous, non-conflicting target store ID ON the offer itself
                # Never fall back to page_store_id or itm.storeId for an offer lacking its own store.
                # Reject conflicting store IDs (e.g. storeId='3891' and pickupStoreId='9999').
                off_stores = collect_distinct_store_ids(off, exclude_price_info=False)
                if len(off_stores) > 1:
                    saw_offer_store_conflict = True
                    continue
                if len(off_stores) != 1:
                    continue
                resolved_store = next(iter(off_stores))
                if resolved_store != str(target_store_id):
                    continue
                if len(itm_direct_stores) == 1 and next(iter(itm_direct_stores)) != resolved_store:
                    saw_offer_store_conflict = True
                    continue

                off_stock = (
                    off.get("inStoreStock")
                    if off.get("inStoreStock") is not None
                    else (off_f_sub.get("inStoreStock") if off_f_sub.get("inStoreStock") is not None else item_instore_stock)
                )
                off_price = _extract_offer_price_string(off)

                return {
                    "store_id": resolved_store,
                    "fulfillment_mode": str(off_fulfill).strip().upper(),
                    "pickup_available": off_avail,
                    "in_store_stock": off_stock,
                    "observed_sale_price": off_price,
                    "offer_id": off_id,
                    "variant_id": off_variant_id,
                    "source_upc": source_upc,
                    "seller_ok": True,
                    "nested_offers_evaluated": True,
                    "store_conflict": False,
                }

        # Nested offers existed but NONE passed strict traceable 1P target-store pickup binding.
        # Refuse top-level priceInfo fallback and keep eligible page store assortment with blank local money.
        has_any_store_conflict = itm_store_conflict or saw_offer_store_conflict
        if has_any_store_conflict and page_store_id is not None:
            fallback_store = str(page_store_id)
        elif len(itm_direct_stores) == 1 and next(iter(itm_direct_stores)) != str(target_store_id):
            fallback_store = next(iter(itm_direct_stores))
        else:
            fallback_store = (
                str(page_store_id)
                if page_store_id is not None
                else (next(iter(itm_direct_stores)) if len(itm_direct_stores) == 1 else None)
            )
        return {
            "store_id": fallback_store,
            "fulfillment_mode": "CONFLICTING_STORE_EVIDENCE" if has_any_store_conflict else "NON_PICKUP_OFFER_ONLY",
            "pickup_available": False,
            "in_store_stock": item_instore_stock,
            "observed_sale_price": "",
            "offer_id": "",
            "variant_id": "",
            "source_upc": source_upc,
            "seller_ok": item_seller_ok,
            "nested_offers_evaluated": True,
            "store_conflict": has_any_store_conflict,
        }

    # No nested offer list: validate top-level item/priceInfo/fulfillment directly
    curr_p_obj = p_info.get("currentPrice") if isinstance(p_info.get("currentPrice"), dict) else {}
    if not item_seller_ok or not is_walmart_first_party_seller(p_info) or not is_walmart_first_party_seller(curr_p_obj):
        return {
            "store_id": str(itm.get("storeId") or page_store_id) if (itm.get("storeId") or page_store_id) is not None else None,
            "fulfillment_mode": str(itm.get("fulfillmentMode") or page_fulfillment_mode or ""),
            "pickup_available": False,
            "in_store_stock": item_instore_stock,
            "observed_sale_price": "",
            "offer_id": _norm_id(curr_p_obj.get("offerId") or p_info.get("offerId") or itm.get("offerId")),
            "variant_id": item_selected_variant,
            "source_upc": source_upc,
            "seller_ok": False,
            "nested_offers_evaluated": False,
            "store_conflict": False,
        }

    flat_stores = collect_distinct_store_ids(itm, exclude_price_info=False)
    if len(flat_stores) > 1:
        return {
            "store_id": str(page_store_id) if page_store_id is not None else None,
            "fulfillment_mode": "CONFLICTING_STORE_EVIDENCE",
            "pickup_available": False,
            "in_store_stock": item_instore_stock,
            "observed_sale_price": "",
            "offer_id": "",
            "variant_id": item_selected_variant,
            "source_upc": source_upc,
            "seller_ok": True,
            "nested_offers_evaluated": False,
            "store_conflict": True,
        }

    item_store = next(iter(flat_stores)) if len(flat_stores) == 1 else page_store_id
    flat_modes = [
        str(m).strip()
        for m in (
            curr_p_obj.get("fulfillmentMode"),
            curr_p_obj.get("fulfillmentType"),
            p_info.get("fulfillmentMode"),
            p_info.get("fulfillmentType"),
            f_info.get("fulfillmentMode") if f_info else None,
            f_info.get("fulfillmentType") if f_info else None,
            itm.get("fulfillmentMode"),
            itm.get("fulfillmentType"),
        )
        if m is not None and str(m).strip()
    ]
    if flat_modes:
        if any(not is_exact_affirmative_fulfillment(m) for m in flat_modes):
            item_fulfill = next(m for m in flat_modes if not is_exact_affirmative_fulfillment(m))
        else:
            item_fulfill = flat_modes[0]
    else:
        item_fulfill = page_fulfillment_mode

    line_p = _extract_offer_price_string(itm)
    offer_id = _norm_id(curr_p_obj.get("offerId") or p_info.get("offerId") or itm.get("offerId"))

    return {
        "store_id": str(item_store) if item_store is not None else None,
        "fulfillment_mode": str(item_fulfill) if item_fulfill is not None else None,
        "pickup_available": item_pickup_avail,
        "in_store_stock": item_instore_stock,
        "observed_sale_price": line_p,
        "offer_id": offer_id,
        "variant_id": item_selected_variant,
        "source_upc": source_upc,
        "seller_ok": True,
        "nested_offers_evaluated": False,
        "store_conflict": False,
    }

def build_structured_category_url(base_url: str, page_number: int) -> str:
    """
    Builds category pagination URL using structured query parameter updates.
    Preserves existing query parameters without appending invalid duplicate '?' characters.
    """
    parsed = urlparse(base_url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    if page_number > 1:
        query_params["page"] = [str(page_number)]
    else:
        query_params.pop("page", None)
    query_params["affinityOverride"] = ["store"]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

def parse_header_results_count(header_text: str) -> Optional[int]:
    """Parses total reported item count from a category results header string."""
    if not header_text:
        return None
    m_showing = re.search(
        r'\b(?:showing\s+)?(?:\d+\s*-\s*)?(\d+)\s+of\s+(\d+)\s+(?:results|items|products)\b',
        header_text,
        re.IGNORECASE,
    )
    if m_showing:
        return int(m_showing.group(2))
    m_exact = re.search(r'\b(\d+)\s+(?:results|items|products)\b', header_text, re.IGNORECASE)
    if m_exact:
        return int(m_exact.group(1))
    return None

async def read_page_header_results_count(page: Any) -> Optional[int]:
    """Reads the scoped category search header total results count if present."""
    if not page:
        return None
    category_count_selectors = [
        '[data-automation-id="results-count"]',
        '[data-testid="results-count"]',
        '[data-automation-id="total-results"]',
        '[data-testid="total-results"]',
        '[data-automation-id="search-header"]',
        '[data-testid="search-header"]',
        '[data-automation-id="item-count"]',
        '[data-testid="item-count"]',
        '[data-automation-id="search-header-title"]',
        'div[data-testid="search-results"] [data-automation-id="results-heading"]',
        'main [data-automation-id="results-count"]',
        '#maincontent [data-automation-id="results-count"]'
    ]
    for sel in category_count_selectors:
        try:
            elem = await page.query_selector(sel)
            if elem:
                txt = (await elem.inner_text()).strip()
                if txt:
                    parsed = parse_header_results_count(txt)
                    if parsed is not None:
                        return parsed
        except Exception:
            continue
    return None

async def check_explicit_terminal_evidence(
    page: Any,
    containers_count: int,
    current_page: int = 1,
    valid_items_count: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Checks for explicit source terminal or total results evidence confirming category exhaustion.
    A short page (< 24 items) alone is NOT proof of exhaustion.
    Also refuses to mark a category naturally exhausted if the page header reports N > 0 results
    while 0 valid items were extracted.
    """
    if not page:
        return False, "No page object provided"

    header_reported_total = await read_page_header_results_count(page)
    effective_yield = containers_count if valid_items_count is None else valid_items_count
    if header_reported_total is not None and header_reported_total > 0 and effective_yield <= 0:
        return False, (
            f"Header reports {header_reported_total} results but extracted valid items is {effective_yield}"
        )

    # 1. Scoped Category Pagination Next button check
    pagination_container = None
    container_selectors = [
        '[data-automation-id="pagination"]',
        'nav[aria-label*="pagination" i]',
        'nav[aria-label*="Pagination"]',
        '[data-testid="pagination"]',
        'nav.paginator',
        'ul.paginator-list',
        'div[data-testid="search-results"] nav',
        'main nav[aria-label*="pagination" i]',
        '#maincontent nav[aria-label*="pagination" i]'
    ]
    for sel in container_selectors:
        try:
            elem = await page.query_selector(sel)
            if elem:
                pagination_container = elem
                break
        except Exception as ex:
            logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying pagination container {sel}: {ex}")

    if pagination_container:
        next_selectors = [
            '[data-automation-id="pagination-next-page"]',
            '[data-testid="pagination-next-page"]',
            'a[aria-label*="Next Page" i]',
            'button[aria-label*="Next Page" i]',
            'a[aria-label*="next page" i]',
            'button[aria-label*="next page" i]',
            'a[aria-label="Next" i]',
            'button[aria-label="Next" i]',
            'li.paginator-btn-next a',
            'li.paginator-btn-next button',
            'button:has-text("Next")',
            'a:has-text("Next")'
        ]
        for sel in next_selectors:
            try:
                next_btn = await pagination_container.query_selector(sel)
                if next_btn:
                    attr_dis = await next_btn.get_attribute("disabled")
                    aria_dis = await next_btn.get_attribute("aria-disabled")
                    cls_dis = await next_btn.get_attribute("class") or ""
                    if (attr_dis is not None) or (aria_dis == "true") or ("disabled" in cls_dis.lower()):
                        return True, "Category pagination Next button explicitly present and disabled"
                    else:
                        return False, "Category pagination Next button is present and enabled (route not exhausted)"
            except Exception as ex:
                logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying next button inside pagination container: {ex}")
    else:
        try:
            dedicated_next = await page.query_selector('[data-automation-id="pagination-next-page"], [data-testid="pagination-next-page"]')
            if dedicated_next:
                attr_dis = await dedicated_next.get_attribute("disabled")
                aria_dis = await dedicated_next.get_attribute("aria-disabled")
                cls_dis = await dedicated_next.get_attribute("class") or ""
                if (attr_dis is not None) or (aria_dis == "true") or ("disabled" in cls_dis.lower()):
                    return True, "Dedicated category pagination Next button explicitly present and disabled"
                else:
                    return False, "Dedicated category pagination Next button is present and enabled"
        except Exception as ex:
            logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying dedicated pagination Next button: {ex}")

    # 2. Check for explicit exact pagination indicator
    try:
        pagination_elem = pagination_container
        if not pagination_elem:
            pagination_elem = await page.query_selector(
                '[data-automation-id="pagination"], nav[aria-label*="pagination" i], nav[aria-label*="Pagination"], [data-testid="pagination"], ul.paginator-list'
            )
        if pagination_elem:
            pag_text = (await pagination_elem.inner_text()).strip()
            m_pages = re.search(r'\b(?:page\s+)?(\d+)\s*(?:of|\/)\s*(\d+)\b', pag_text, re.IGNORECASE)
            if m_pages:
                parsed_curr = int(m_pages.group(1))
                parsed_last = int(m_pages.group(2))
                if parsed_curr == parsed_last and parsed_last >= 1:
                    if current_page is None or parsed_curr == current_page or parsed_last == 1:
                        return True, f"Explicit pagination terminal indicator confirmed (page {parsed_curr} of {parsed_last}): '{pag_text}'"
                elif parsed_curr < parsed_last:
                    return False, f"Explicit pagination confirms active non-terminal page ({parsed_curr} of {parsed_last}): '{pag_text}'"
    except Exception as ex:
        logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying pagination indicator: {ex}")

    # 3. Check for explicit source total results count matching container count
    category_count_selectors = [
        '[data-automation-id="results-count"]',
        '[data-testid="results-count"]',
        '[data-automation-id="total-results"]',
        '[data-testid="total-results"]',
        '[data-automation-id="search-header"]',
        '[data-testid="search-header"]',
        '[data-automation-id="item-count"]',
        '[data-testid="item-count"]',
        '[data-automation-id="search-header-title"]',
        'div[data-testid="search-results"] [data-automation-id="results-heading"]',
        'main [data-automation-id="results-count"]',
        '#maincontent [data-automation-id="results-count"]'
    ]

    header_text = ""
    for sel in category_count_selectors:
        try:
            elem = await page.query_selector(sel)
            if elem:
                txt = (await elem.inner_text()).strip()
                if txt:
                    header_text = txt
                    break
        except Exception:
            continue

    if not header_text:
        try:
            main_elem = await page.query_selector('main, #maincontent, [data-testid="search-results"], [role="main"]')
            if main_elem:
                header_child = await main_elem.query_selector(
                    'header, [data-automation-id="results-heading"], h1, h2'
                )
                if header_child:
                    header_text = (await header_child.inner_text()).strip()
        except Exception:
            pass

    if header_text and containers_count > 0:
        m_showing = re.search(r'\b(?:showing\s+)?(?:\d+\s*-\s*)?(\d+)\s+of\s+(\d+)\s+(?:results|items|products)\b', header_text, re.IGNORECASE)
        if m_showing:
            showing_end = int(m_showing.group(1))
            total_items = int(m_showing.group(2))
            if total_items == containers_count or (showing_end == containers_count and total_items == containers_count):
                return True, f"Category results count '{total_items}' matches container count '{containers_count}' in header: '{header_text}'"

        m_exact = re.search(r'\b(\d+)\s+(?:results|products)\b', header_text, re.IGNORECASE)
        if m_exact:
            total_items = int(m_exact.group(1))
            if total_items == containers_count:
                return True, f"Category total results '{total_items}' matches container count '{containers_count}' in header: '{header_text}'"

    return False, "No explicit terminal indicator or matching total results evidence found"

# Machine-Readable NDJSON & Structured Logger
class NDJSONFileHandler(logging.FileHandler):
    def emit(self, record):
        if "unittest" in sys.modules:
            return
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_entry.update(record.extra_fields)
        with open(self.baseFilename, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

logger = logging.getLogger("WalmartScraper")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
logger.addHandler(stream_handler)
ndjson_handler = NDJSONFileHandler("walmart_scraper_execution.ndjson", mode="a", encoding="utf-8")
logger.addHandler(ndjson_handler)


class WalmartProductionScraper:
    """
    Production-grade Walmart Scraper engineered for Microsoft Azure Container App Jobs / VMs.
    Features:
    - Direct live collection path (DOM + Next.js __NEXT_DATA__ / Apollo GraphQL responses)
    - Store affinity & in-store pickup cookie locking with strict fulfillment verification
    - Source-bound locality verification per item, page-scoped without cross-page leakage
    - Conflict reporting on price disagreement rather than presenting mixed observations
    - Preserves verified regular and sale roles separately; non-sale current prices do not populate sale_price
    - Exact recognized affirmative fulfillment rejection of NOT_PICKUP / string 'false' flags
    - Retains eligible store assortment identities with unverified prices blank
    - Structured query parameter pagination preserving existing category URL query parameters
    - Category safety caps and unknown pagination states remain incomplete without source reconciliation
    - Unresolved work persistence and exact resume from earliest failed route
    - Genuine retailer UPC extraction from item data fields (never parsed from URL digits)
    - Exact 22-field ordering with strict "" for gupc/unit_price and all four deal fields
    - Atomic package publication via single committed manifest pointer
    """

    def __init__(
        self,
        store: StoreConfig,
        settings: Optional[ScraperSettings] = None,
        resume: bool = True,
        staging_dir: Optional[str] = None,
        crawl_date: Optional[str] = None
    ):
        self.store = store
        self.settings = settings or get_settings()
        eff_staging = staging_dir or self.settings.staging_dir or ".staging"
        self.crawl_date = crawl_date or datetime.now().strftime("%Y-%m-%d")
        self.configured_routes = self._load_configured_routes()
        self.routes_signature = compute_routes_signature(self.configured_routes)
        self.run_id = self.settings.run_id or f"run_{self.store.store_number}_{self.crawl_date}_{int(time.time() * 1000)}"

        # Restore durable state from Azure Blob Storage before loading checkpoint when resuming
        self._azure_publisher = AzureBlobPublisher(
            connection_string=self.settings.azure_storage_connection_string,
            account_url=self.settings.azure_storage_account_url,
            container_name=self.settings.azure_container_name,
        )
        if resume and self._azure_publisher.is_configured():
            self._azure_publisher.sync_durable_state_down(
                self.store.store_number,
                eff_staging,
                self.settings.output_directory,
            )

        self.checkpoint_mgr = CheckpointManager(
            store_number=self.store.store_number,
            crawl_date=self.crawl_date,
            staging_dir=eff_staging,
            output_dir=self.settings.output_directory,
            routes_signature=self.routes_signature,
            run_id=self.run_id,
            store_zipcode=self.store.zipcode,
        )
        # Adopt reconciled crawl date from checkpoint manager (cross-midnight preservation)
        self.crawl_date = self.checkpoint_mgr.crawl_date
        self.resume = resume
        self.checkpoint_state = self.checkpoint_mgr.load_checkpoint(expected_routes_signature=self.routes_signature) if resume else {}
        self.scraped_records: List[Dict[str, str]] = self.checkpoint_mgr.load_staging_records() if resume else []
        # Reconcile seen signatures directly from staging records to eliminate drift
        self.seen_signatures = self.checkpoint_mgr.reconcile_signatures_from_staging() if resume else set()
        if resume and self.checkpoint_state:
            (
                self.category_yields,
                self.failed_routes,
                self.terminal_verified_routes,
                reconciled_page,
                _reconcile_warnings,
            ) = self.checkpoint_mgr.reconcile_staged_routes_on_resume(
                self.checkpoint_state,
                self.scraped_records,
                ordered_routes=self.configured_routes,
            )
            self.checkpoint_state["current_page"] = reconciled_page
        else:
            self.category_yields = {}
            self.failed_routes = []
            self.terminal_verified_routes = {}

        self.canary_results: Dict[str, bool] = {}
        self.store_fulfillment_verified: bool = False
        self.confirmed_store_number: str = str(self.checkpoint_state.get("confirmed_store_number") or "") if resume else ""
        self.observed_availability_transitions: List[Dict[str, Any]] = []

        # Current page context tracking & page-scoped intercepted network items
        self.current_page_number: int = 1
        self.current_page_url: str = ""
        self.fatal_evidence_error: bool = False
        self.current_page_intercepted_items: Dict[str, Dict[str, Any]] = {}
        self.requests_made: int = 0
        self.run_start_monotonic: float = time.monotonic()
        self.budget_stop_reason: str = ""

    def _load_configured_routes(self) -> List[Dict[str, str]]:
        csv_path = self.settings.categories_csv_path
        if not os.path.exists(csv_path):
            csv_path = os.path.join(os.path.dirname(__file__), "Walmart_Category_URLs.csv")
        routes: List[Dict[str, str]] = []
        if os.path.exists(csv_path):
            try:
                with open(csv_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        routes.append(dict(row))
            except Exception as ex:
                logger.warning(f"[ROUTES LOAD] Failed reading {csv_path}: {ex}")
        return routes

    def _check_execution_budget(self) -> Optional[str]:
        if self.settings.max_requests_per_run is not None and self.requests_made >= self.settings.max_requests_per_run:
            return f"REQUEST_LIMIT_REACHED ({self.requests_made}/{self.settings.max_requests_per_run})"
        if self.settings.max_runtime_seconds is not None:
            elapsed = time.monotonic() - self.run_start_monotonic
            if elapsed >= self.settings.max_runtime_seconds:
                return f"RUNTIME_DEADLINE_REACHED ({elapsed:.1f}s/{self.settings.max_runtime_seconds:.1f}s)"
        return None

    def _get_proxy_dict(self) -> Optional[Dict[str, str]]:
        if self.settings.proxy_server:
            proxy = {"server": self.settings.proxy_server}
            if self.settings.proxy_username:
                proxy["username"] = self.settings.proxy_username
                proxy["password"] = self.settings.proxy_password
            return proxy
        return None

    def _extract_search_payload_evidence(
        self,
        j_data: Dict[str, Any],
        endpoint_url: str,
        request_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Extracts store affinity, fulfillment mode, and strictly bound item-level price/offer/UPC
        from GraphQL XHR payloads or Next.js SSR __NEXT_DATA__ payloads, persisting
        sanitized raw evidence to disk.
        Returns True if target store_id and exact affirmative PICKUP fulfillment match.
        """
        if not isinstance(j_data, dict):
            return False

        page_props = j_data.get("props", {}).get("pageProps", {}) if isinstance(j_data.get("props"), dict) else {}
        initial_data = page_props.get("initialData", {}) if isinstance(page_props, dict) else {}
        data_root = j_data.get("data", {}) if isinstance(j_data.get("data"), dict) else {}

        search_res = (
            data_root.get("searchResult")
            or data_root.get("browse")
            or (initial_data.get("searchResult") if isinstance(initial_data, dict) else None)
            or (initial_data.get("browse") if isinstance(initial_data, dict) else None)
            or {}
        )
        if not isinstance(search_res, dict):
            search_res = {}

        stacks = search_res.get("itemStacks") or ([search_res.get("itemStack")] if search_res.get("itemStack") else [])
        if not stacks:
            stacks = []

        # Rule 1: Keep unknown context unknown! Never fill missing storeId or fulfillmentMode with target defaults
        loc_ctx = page_props.get("locationContext", {}) if isinstance(page_props, dict) else {}
        pickup_store = loc_ctx.get("pickupStore", {}) if isinstance(loc_ctx, dict) else {}

        page_store_candidates = [
            _norm_id(v)
            for v in (
                search_res.get("storeId"),
                search_res.get("pickupStoreId"),
                search_res.get("fulfillmentStoreId"),
                data_root.get("storeId"),
                pickup_store.get("storeId") if isinstance(pickup_store, dict) else None,
            )
            if _norm_id(v)
        ]
        distinct_page_stores = set(page_store_candidates)
        page_store_conflict = len(distinct_page_stores) > 1
        observed_store_id = None if page_store_conflict else (next(iter(distinct_page_stores)) if distinct_page_stores else None)

        observed_fulfillment_mode = (
            search_res.get("fulfillmentMode")
            or data_root.get("fulfillmentMode")
            or (loc_ctx.get("intent") if isinstance(loc_ctx, dict) else None)
        )

        verified = False
        if page_store_conflict:
            logger.warning(
                f"[STORE CONFLICT OBSERVED] Conflicting page store IDs returned: {sorted(distinct_page_stores)} "
                f"(expected Store #{self.store.store_number})."
            )
        elif observed_store_id and str(observed_store_id) == str(self.store.store_number):
            if is_exact_affirmative_fulfillment(observed_fulfillment_mode):
                verified = True
                self.confirmed_store_number = str(observed_store_id)
        elif observed_store_id and str(observed_store_id) != str(self.store.store_number):
            logger.warning(
                f"[STORE MISMATCH OBSERVED] Network response returned Store #{observed_store_id}, "
                f"expected Store #{self.store.store_number}."
            )

        capture_id = self.checkpoint_mgr.append_raw_evidence(
            endpoint=endpoint_url,
            request_data=request_data or {"url": endpoint_url, "method": "GET", "headers": {}},
            response_payload=j_data,
            run_id=self.run_id,
        )

        for stk in stacks:
            if not isinstance(stk, dict):
                continue
            for itm in stk.get("items", []):
                if not isinstance(itm, dict):
                    continue
                itm_id = str(itm.get("usItemId") or itm.get("id") or "").strip()
                if not itm_id:
                    continue

                bound = select_bound_pickup_offer(
                    itm=itm,
                    page_store_id=str(observed_store_id) if observed_store_id is not None else None,
                    page_fulfillment_mode=str(observed_fulfillment_mode) if observed_fulfillment_mode is not None else None,
                    target_store_id=self.store.store_number,
                )

                self.current_page_intercepted_items[itm_id] = {
                    "capture_id": capture_id,
                    "item_id": itm_id,
                    "offer_id": bound.get("offer_id", ""),
                    "variant_id": bound.get("variant_id", ""),
                    "source_upc": bound.get("source_upc", ""),
                    "seller_ok": bound.get("seller_ok", True),
                    "store_conflict": bool(bound.get("store_conflict", False) or page_store_conflict),
                    "page_number": self.current_page_number,
                    "page_url": self.current_page_url,
                    "store_id": bound.get("store_id"),
                    "fulfillment_mode": bound.get("fulfillment_mode"),
                    "pickup_available": bound.get("pickup_available"),
                    "in_store_stock": bound.get("in_store_stock"),
                    "observed_sale_price": bound.get("observed_sale_price", ""),
                }

        return verified

    async def _capture_ssr_next_data_if_present(self, page: Page, page_url: str) -> bool:
        """
        Captures SSR Next.js __NEXT_DATA__ payload when initial page navigation embeds
        catalog & store/Pickup data directly in HTML rather than an XHR response.
        """
        if not page:
            return False
        try:
            next_data_el = await page.query_selector('script#__NEXT_DATA__')
            if not next_data_el:
                return False
            raw_json = await next_data_el.inner_text()
            if not raw_json:
                return False
            j_data = json.loads(raw_json)
            return self._extract_search_payload_evidence(
                j_data=j_data,
                endpoint_url=f"{page_url}#__NEXT_DATA__",
                request_data={"url": page_url, "method": "GET", "headers": {}}
            )
        except Exception as ex:
            logger.debug(f"[SSR __NEXT_DATA__ PARSE] Skipped or failed: {ex}")
            return False

    async def initialize_store_context(self, context: BrowserContext, page: Page) -> bool:
        """
        Sets store location cookies and verifies local in-store/pickup fulfillment context.
        Locks pricing and inventory to Store #self.store.store_number.
        Requires positive verification from both cookie persistence and page fulfillment response.
        Fails if response is blocked, invalid, or mismatched.
        """
        logger.info(f"[STORE LOCK] Injecting store affinity cookies for Store #{self.store.store_number} (ZIP: {self.store.zipcode})...")

        cookies = [
            {"name": "walmart.store.id", "value": self.store.store_number, "domain": ".walmart.com", "path": "/"},
            {"name": "walmart.postalCode", "value": self.store.zipcode, "domain": ".walmart.com", "path": "/"},
            {"name": "walmart.fulfillment.type", "value": "PICKUP", "domain": ".walmart.com", "path": "/"},
            {"name": "walmart.store.pickup", "value": "true", "domain": ".walmart.com", "path": "/"},
            {"name": "hasLocation", "value": "true", "domain": ".walmart.com", "path": "/"}
        ]
        await context.add_cookies(cookies)

        price_bearing_response_verified = False

        async def on_response_received(resp):
            nonlocal price_bearing_response_verified
            try:
                target_endpoints = ["/orchestra/home/graphql", "/graphql/browse", "/graphql/search", "_next/data"]
                if any(ep in resp.url for ep in target_endpoints) and resp.status == 200:
                    text_data = await resp.text()
                    try:
                        j_data = json.loads(text_data)
                        raw_headers = dict(resp.request.headers) if hasattr(resp, "request") and hasattr(resp.request, "headers") else {}
                        captured_req = {
                            "url": resp.request.url if hasattr(resp, "request") else resp.url,
                            "method": resp.request.method if hasattr(resp, "request") else "GET",
                            "headers": raw_headers,
                            "post_data": resp.request.post_data if hasattr(resp, "request") and hasattr(resp.request, "post_data") else None
                        }
                        if self._extract_search_payload_evidence(j_data, resp.url, captured_req):
                            price_bearing_response_verified = True
                    except Exception as parse_ex:
                        logger.debug(f"[RESPONSE PARSE] Error processing payload: {parse_ex}")
            except Exception as e:
                # Do not swallow evidence errors silently; persist failure in checkpoint and flag fatal error
                self.fatal_evidence_error = True
                self.checkpoint_mgr.record_evidence_failure(str(e))
                logger.error(f"[RESPONSE LISTENER ERROR] {e}")

        page.on("response", on_response_received)

        try:
            response = await page.goto("https://www.walmart.com", timeout=self.settings.page_load_timeout_ms, wait_until="domcontentloaded")
            if not response or response.status >= 400:
                logger.error(f"[STORE VERIFICATION FAILED] HTTP status {response.status if response else 'None'} received during store lock probe.")
                self.store_fulfillment_verified = False
                return False

            await asyncio.sleep(1.5)

            if not price_bearing_response_verified:
                if await self._capture_ssr_next_data_if_present(page, "https://www.walmart.com"):
                    price_bearing_response_verified = True

            current_cookies = await context.cookies()
            cookie_map = {c["name"]: c["value"] for c in current_cookies}
            has_store = cookie_map.get("walmart.store.id") == self.store.store_number
            has_pickup = cookie_map.get("walmart.fulfillment.type") == "PICKUP" or cookie_map.get("walmart.store.pickup") == "true"

            if not has_store or not has_pickup:
                logger.error(f"[STORE VERIFICATION FAILED] Store cookies unverified. Store match: {has_store}, Pickup match: {has_pickup}")
                self.store_fulfillment_verified = False
                return False

            if not price_bearing_response_verified:
                logger.error(f"[STORE VERIFICATION FAILED] Target Store #{self.store.store_number} and exact affirmative PICKUP fulfillment mode were not observed in retailer network response.")
                self.store_fulfillment_verified = False
                return False

            self.store_fulfillment_verified = True
            logger.info(f"[FULFILLMENT CONFIRMED] Store #{self.store.store_number} ({self.store.address}) and PICKUP mode affirmatively observed in retailer network response.")
            return True
        except Exception as e:
            logger.error(f"[STORE VERIFICATION FAILED] Exception during store context verification: {e}")
            self.store_fulfillment_verified = False
            return False

    async def scrape_category(
        self,
        page: Page,
        cat_index: int,
        category: str,
        sub_category: str,
        url: str,
        canary_upc: str = ""
    ) -> int:
        """
        Harvests category items using live HTTP/DOM parsing.
        Retains unavailable store-assortment items with genuinely displayed attributes.
        Binds displayed prices to page-scoped source offers without leakage or silent substitution.
        Durably commits category completion and records failed routes.
        """
        route_name = f"{category} > {sub_category}"
        logger.info(f"[CATEGORY HARVEST] [{route_name}] starting from {url}")
        category_count = 0
        current_page = 1
        max_pages = self.settings.max_pages_per_category

        # Explicitly initialize completion and failure state before loop
        natural_completion = False
        route_failed = False
        terminal_reason = ""
        seen_page_fingerprints: Dict[Tuple[str, ...], int] = {}
        consecutive_zero_new_pages = 0

        # Resume logic (preserve prior staged unique-item yield when resuming)
        prior_staged = (
            sum(
                1 for r in self.scraped_records
                if r.get("category") == category and r.get("sub_category") == sub_category
            )
            if self.resume
            else 0
        )
        category_count = prior_staged
        if self.checkpoint_state.get("category_index") == cat_index:
            current_page = max(1, self.checkpoint_state.get("current_page", 1))
            logger.info(f"[CHECKPOINT RESUME] Resuming category '{sub_category}' from page {current_page} (prior staged items: {prior_staged})")

        # Explicit handling for resume beyond a safety cap:
        if max_pages is not None and current_page > max_pages:
            logger.error(
                f"[RESUME BEYOND SAFETY CAP] Category '{route_name}' resumed at page {current_page}, "
                f"which exceeds max_pages_per_category={max_pages} without natural completion. "
                f"Preserving unresolved route in failed_routes."
            )
            route_failed = True
            natural_completion = False
            if route_name not in self.failed_routes:
                self.failed_routes.append(route_name)

        while (max_pages is None) or (current_page <= max_pages):
            budget_reason = self._check_execution_budget()
            if budget_reason:
                self.budget_stop_reason = budget_reason
                logger.warning(
                    f"[BUDGET STOP] Stopping cleanly before loading '{route_name}' page {current_page}: {budget_reason}"
                )
                break

            paged_url = build_structured_category_url(url, current_page)

            # Track current page context
            self.current_page_number = current_page
            self.current_page_url = paged_url

            # Clear page-scoped intercepted items so earlier observations never leak to later pages!
            self.current_page_intercepted_items.clear()

            success = False
            page_response = None
            for attempt in range(1, self.settings.max_retries_per_page + 1):
                try:
                    logger.info(f"Loading page {current_page} for {sub_category} (attempt {attempt})...")
                    self.requests_made += 1
                    page_response = await page.goto(paged_url, timeout=self.settings.page_load_timeout_ms, wait_until="domcontentloaded")
                    await asyncio.sleep(self.settings.delay_between_requests_sec)

                    if page_response and page_response.status in [403, 429]:
                        logger.warning(f"Rate limited (HTTP {page_response.status}). Backoff {5 * attempt}s...")
                        await asyncio.sleep(5 * attempt)
                        continue

                    # Trigger lazy-loaded items via scroll
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3);")
                    await asyncio.sleep(0.5)
                    await page.evaluate("window.scrollTo(0, (document.body.scrollHeight / 3) * 2);")
                    await asyncio.sleep(0.5)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    await asyncio.sleep(0.6)

                    success = True
                    break
                except Exception as ex:
                    logger.warning(f"Error loading {paged_url}: {ex}. Retrying...")
                    await asyncio.sleep(2 * attempt)

            if not success:
                logger.error(f"[ROUTE FAILURE] Failed to load page {current_page} after max retries for route '{route_name}'.")
                if route_name not in self.failed_routes:
                    self.failed_routes.append(route_name)
                route_failed = True
                break

            # Verify canary barcode
            if canary_upc:
                content = await page.content()
                if canary_upc in content:
                    self.canary_results[f"{category}_{sub_category}"] = True
                    logger.info(f"[CANARY VERIFIED] Canary barcode {canary_upc} observed in {sub_category}")

            # Check for blocking or empty page hydration
            page_title = (await page.title()).lower() if page else ""
            if any(term in page_title for term in ["blocked", "robot", "verify", "access denied", "captcha"]):
                logger.error(f"[PERIMETER BLOCKED] Page {current_page} for route '{route_name}' encountered perimeter challenge.")
                if route_name not in self.failed_routes:
                    self.failed_routes.append(route_name)
                route_failed = True
                break

            product_elements = await page.query_selector_all('[data-item-id], [data-testid="item-stack"], div[data-testid="list-view"], div[data-testid="grid-view"]')
            logger.info(f"Page {current_page} found {len(product_elements)} product containers")

            header_reported_total = await read_page_header_results_count(page)

            # Check for hydration failure on any page: 0 containers without explicit zero-results confirmation is an error
            if len(product_elements) == 0:
                body_text = (await page.inner_text("body")).lower() if page else ""
                has_zero_results = any(term in body_text for term in ["0 results", "no products found", "no items found", "we found 0"])
                if not has_zero_results or (header_reported_total is not None and header_reported_total > 0):
                    logger.error(f"[HYDRATION FAILURE] Page {current_page} for '{route_name}' rendered 0 product containers without explicit zero-results confirmation.")
                    if route_name not in self.failed_routes:
                        self.failed_routes.append(route_name)
                    route_failed = True
                    break

            if not self.current_page_intercepted_items:
                await self._capture_ssr_next_data_if_present(page, paged_url)

            page_batch: List[Dict[str, str]] = []
            page_extracted_sigs: List[str] = []

            for el in product_elements:
                try:
                    # 1. Exclude Sponsored Placements
                    is_sponsored = await el.query_selector('[data-testid="sponsored-badge"], span:has-text("Sponsored")')
                    if is_sponsored:
                        continue

                    # 2. Exclude 3P Marketplace items from DOM text or seller attribute
                    raw_text = (await el.inner_text()) if el else ""
                    if re.search(r"\b(?:sold(?:\s+and\s+shipped)?\s+by|fulfilled\s+by)\b", raw_text, re.IGNORECASE) and "walmart" not in raw_text.lower():
                        continue
                    dom_seller = await el.get_attribute("data-seller-name") or ""
                    if dom_seller and "walmart" not in dom_seller.lower():
                        continue

                    # 3. Fulfillment status
                    is_pickup_unavailable = "not available for pickup" in raw_text.lower() or "shipping only" in raw_text.lower()

                    # 4. Item ID, Title & URL
                    raw_item_id = await el.get_attribute('data-item-id') or ""
                    link_elem = await el.query_selector('a[href*="/ip/"]')
                    href = await link_elem.get_attribute('href') if link_elem else ""
                    full_url = f"https://www.walmart.com{href}" if href.startswith('/') else href

                    if not raw_item_id and href:
                        m_id = re.search(r'/ip/[^/]+/(\d+)', href)
                        if m_id:
                            raw_item_id = m_id.group(1)

                    title_elem = await el.query_selector('[data-automation-id="product-title"], span.w_iUH7, a[link-identifier]')
                    title = (await title_elem.inner_text()).strip() if title_elem else ""
                    if not title:
                        continue

                    # Traceable Page-Scoped Price/Offer/Store/Seller Binding & Source Evidence
                    bound_item = self.current_page_intercepted_items.get(raw_item_id)
                    if bound_item and not bound_item.get("seller_ok", True):
                        logger.debug(f"[3P SELLER EXCLUDED] Skipping item {raw_item_id} ('{title}') bound to non-Walmart seller.")
                        continue

                    dom_store_id = (await el.get_attribute("data-store-id") or "").strip()
                    if dom_store_id and dom_store_id != str(self.store.store_number):
                        continue

                    is_verified_local_pickup = False
                    is_eligible_store_assortment = True

                    if bound_item is None or bound_item.get("page_number") != current_page:
                        is_verified_local_pickup = False
                        logger.debug(f"[UNMATCHED ITEM] No current-page intercepted network payload for item {raw_item_id} ('{title}'). Cannot qualify as verified local price.")
                    else:
                        observed_store = bound_item.get("store_id")
                        observed_fulfillment = bound_item.get("fulfillment_mode")
                        pickup_available = bound_item.get("pickup_available")
                        bound_offer_id = bound_item.get("offer_id", "")
                        bound_variant_id = bound_item.get("variant_id", "")
                        dom_offer_id = (await el.get_attribute("data-offer-id") or "").strip()
                        dom_variant_id = (await el.get_attribute("data-variant-id") or "").strip()

                        if bound_item.get("store_conflict"):
                            logger.warning(f"[STORE CONFLICT] Item {raw_item_id} has conflicting store evidence; retaining blank local money.")
                            is_verified_local_pickup = False
                        elif not observed_store or str(observed_store) != str(self.store.store_number):
                            is_verified_local_pickup = False
                            is_eligible_store_assortment = False
                        elif dom_offer_id and (not bound_offer_id or dom_offer_id != bound_offer_id):
                            logger.warning(f"[OFFER ID MISMATCH] Item {raw_item_id} DOM offer '{dom_offer_id}' != bound offer '{bound_offer_id}'. Disqualifying price.")
                            is_verified_local_pickup = False
                        elif dom_variant_id and (not bound_variant_id or dom_variant_id != bound_variant_id):
                            logger.warning(f"[VARIANT ID MISMATCH] Item {raw_item_id} DOM variant '{dom_variant_id}' != bound variant '{bound_variant_id}'. Disqualifying price.")
                            is_verified_local_pickup = False
                        elif not is_exact_affirmative_fulfillment(observed_fulfillment):
                            is_verified_local_pickup = False
                        elif not is_affirmative_availability(pickup_available):
                            is_verified_local_pickup = False
                        else:
                            is_verified_local_pickup = True

                    # DOM badge verification
                    badge_elem = await el.query_selector('[data-automation-id="fulfillment-badge"], [data-testid="fulfillment-badge"]')
                    badge_str = (await badge_elem.inner_text()).lower() if badge_elem else ""
                    if "shipping only" in badge_str or "delivery from central warehouse" in badge_str:
                        is_verified_local_pickup = False
                        is_eligible_store_assortment = False

                    # Retain eligible store assortment identities even when unverified local price is blank
                    if not is_eligible_store_assortment:
                        continue

                    # 5. Extract Weight: Preserve full pack sizes & multi-pack counts!
                    weight = ""
                    weight_elem = await el.query_selector('[data-automation-id="product-weight"], span:has-text("oz"), span:has-text("lb"), span:has-text("ct")')
                    if weight_elem:
                        weight = (await weight_elem.inner_text()).strip()

                    if not weight:
                        # Capture multi-pack counts (e.g. '16.9 fl oz, 24 Pack' or '24 Pack, 16.9 fl oz')
                        m_pack = re.search(r'\b(\d+(\.\d+)?\s*(?:fl\s*oz|oz|lb|g|kg|ct|gal)\s*,\s*\d+\s*(?:pack|count|ct|pk|bottles|cans|pouches))\b', title, re.IGNORECASE)
                        if m_pack:
                            weight = m_pack.group(1).strip()
                        else:
                            m_rev = re.search(r'\b(\d+\s*(?:pack|count|ct|pk)\s*,\s*\d+(\.\d+)?\s*(?:fl\s*oz|oz|lb|g|kg|ct|gal))\b', title, re.IGNORECASE)
                            if m_rev:
                                weight = m_rev.group(1).strip()
                            else:
                                m_single = re.search(r'\b\d+(\.\d+)?\s*(?:fl\s*oz|oz|lb|g|kg|ct|pack|count|gal)\b', title, re.IGNORECASE)
                                if m_single:
                                    weight = m_single.group(0).strip()

                    if is_approximate_weight(weight) or is_approximate_weight(title):
                        continue

                    # 6. Availability Check
                    is_out_of_stock = (
                        is_pickup_unavailable or
                        "out of stock" in raw_text.lower() or
                        "temporarily out of stock" in raw_text.lower() or
                        bool(await el.query_selector('[data-testid="out-of-stock-badge"], span:has-text("Out of stock")'))
                    )

                    # 7. Price Context & Source Offer Binding
                    # Preserve verified regular and sale roles separately; normal non-sale current prices do NOT populate sale_price
                    price_elem = await el.query_selector('[data-automation-id="product-price"], span.w_iUH7')
                    price_text = (await price_elem.inner_text()) if price_elem else ""
                    raw_current_price = format_price(price_text)

                    was_price_elem = await el.query_selector('[data-automation-id="was-price"], span.strike')
                    was_price_text = (await was_price_elem.inner_text()) if was_price_elem else ""
                    raw_was_price = format_price(was_price_text) if was_price_text else ""

                    if is_verified_local_pickup and not is_out_of_stock:
                        observed_offer_price = bound_item.get("observed_sale_price") if bound_item else ""
                        if not observed_offer_price or not raw_current_price:
                            # Missing source offer price prevents qualification as verified local price!
                            logger.warning(f"[MISSING SOURCE OFFER] Item {raw_item_id} has no observed source offer price. Disqualifying local price.")
                            sale_price = ""
                            regular_price = ""
                        else:
                            formatted_offer = format_price(str(observed_offer_price))
                            if raw_current_price != formatted_offer:
                                # Report conflict rather than presenting a mixed observation as verified!
                                logger.warning(f"[PRICE DISAGREEMENT CONFLICT] Item {raw_item_id} displayed price '{raw_current_price}' disagrees with source offer '{formatted_offer}'. Disqualifying local price.")
                                sale_price = ""
                                regular_price = ""
                            else:
                                # Successful binding branch: preserve verified regular vs sale roles separately
                                if raw_was_price and raw_was_price != formatted_offer:
                                    # Verified promotional sale discount: was_price is regular, current offer is sale
                                    regular_price = raw_was_price
                                    sale_price = formatted_offer
                                else:
                                    # Normal non-sale current price: populates regular_price; sale_price remains strictly empty
                                    regular_price = formatted_offer
                                    sale_price = ""
                    else:
                        # Retain unavailable or unverified store-assortment items with empty string prices
                        sale_price = ""
                        regular_price = ""

                    # 8. Directly Scraped PPM
                    ppm_elem = await el.query_selector('[data-automation-id="product-unit-price"], span:has-text("/oz"), span:has-text("/fl oz"), span:has-text("/lb"), span:has-text("/ct")')
                    ppm_text = ""
                    if ppm_elem and regular_price:
                        ppm_raw = (await ppm_elem.inner_text()).strip()
                        if "/" in ppm_raw and "$" in ppm_raw:
                            ppm_text = ppm_raw

                    # 9. Image URL
                    img_elem = await el.query_selector('img[data-testid="productTileImage"], img[src*="walmartimages.com"]')
                    image_url = (await img_elem.get_attribute('src')) if img_elem else ""

                    # 10. UPC Extraction (module-level re used cleanly)
                    upc = ""
                    dom_upc = (
                        await el.get_attribute('data-upc') or
                        await el.get_attribute('data-gtin') or
                        await el.get_attribute('data-product-upc') or
                        await el.get_attribute('data-item-upc')
                    )
                    if dom_upc and re.match(r'^\d{11,14}$', dom_upc.strip()):
                        upc = dom_upc.strip()

                    if not upc:
                        json_el = await el.query_selector('script[type="application/ld+json"]')
                        if json_el:
                            try:
                                j_txt = await json_el.inner_text()
                                j_obj = json.loads(j_txt)
                                gtin = j_obj.get("gtin12") or j_obj.get("gtin13") or j_obj.get("gtin")
                                if gtin and re.match(r'^\d{11,14}$', str(gtin).strip()):
                                    upc = str(gtin).strip()
                            except Exception:
                                pass

                    if not upc and bound_item and bound_item.get("source_upc"):
                        upc = str(bound_item["source_upc"]).strip()

                    # 11. Store brand detection
                    store_brand = detect_store_brand(title)

                    # Build conforming 22-field record
                    capture_id = bound_item.get("capture_id", "") if bound_item else ""
                    record = {
                        "zipcode": self.store.zipcode,
                        "store_name": self.store.name,
                        "store_location": self.store.address,
                        "store_logo": self.store.logo_url,
                        "store_brand": store_brand,
                        "category": category,
                        "sub_category": sub_category,
                        "product_title": title,
                        "weight": weight,
                        "regular_price": regular_price,
                        "sale_price": sale_price,
                        "volume_deals_description": "",
                        "volume_deals_price": "",
                        "digital_deals_description": "",
                        "digital_deals_price": "",
                        "image_url": image_url,
                        "url": full_url,
                        "upc": upc,
                        "gupc": "",
                        "ppm": ppm_text,
                        "unit_price": "",
                        "crawl_date": self.crawl_date,
                        "capture_id": capture_id
                    }

                    ordered = sanitize_and_order_record(record, self.crawl_date, preserve_meta=True)

                    sig = f"{ordered['upc'] or ordered['url']}_{ordered['zipcode']}"
                    page_extracted_sigs.append(sig)
                    if sig not in self.seen_signatures:
                        self.seen_signatures.add(sig)
                        page_batch.append(ordered)
                        category_count += 1

                except Exception as item_err:
                    logger.debug(f"[ITEM PARSE ERROR] Skipping unparseable element: {item_err}")
                    continue

            # Empty page contradiction guard: if header says "10 results" (> 0) and 0 valid items extracted
            if header_reported_total is not None and header_reported_total > 0 and len(page_extracted_sigs) == 0:
                logger.error(
                    f"[EMPTY PAGE CONTRADICTION] Page {current_page} for '{route_name}' reported "
                    f"{header_reported_total} results in header but yielded 0 valid items."
                )
                if route_name not in self.failed_routes:
                    self.failed_routes.append(route_name)
                route_failed = True
                natural_completion = False
                break

            # Repeated/stalled pagination guard: detect repeated pages returning identical item sets
            page_fp = tuple(sorted(set(page_extracted_sigs)))
            if current_page > 1 and page_fp and page_fp in seen_page_fingerprints:
                prev_pg = seen_page_fingerprints[page_fp]
                logger.error(
                    f"[REPEATED PAGE STALL] Page {current_page} for '{route_name}' repeated identical items "
                    f"from page {prev_pg}. Refusing false completion."
                )
                if route_name not in self.failed_routes:
                    self.failed_routes.append(route_name)
                route_failed = True
                natural_completion = False
                break
            if page_fp:
                seen_page_fingerprints[page_fp] = current_page

            if len(page_batch) == 0 and len(product_elements) > 0:
                consecutive_zero_new_pages += 1
                if consecutive_zero_new_pages >= 2:
                    logger.error(
                        f"[STALLED PAGINATION] {consecutive_zero_new_pages} consecutive pages yielded 0 new unique items "
                        f"for '{route_name}'. Marking route incomplete."
                    )
                    if route_name not in self.failed_routes:
                        self.failed_routes.append(route_name)
                    route_failed = True
                    natural_completion = False
                    break
            else:
                consecutive_zero_new_pages = 0

            # Flush batch via durable single page transaction
            if page_batch:
                self.scraped_records.extend(page_batch)
                logger.info(f"Page {current_page} yielded {len(page_batch)} new unique records (category total: {category_count})")
            else:
                logger.info(f"Page {current_page} yielded 0 newly deduplicated items (containers: {len(product_elements)}). Continuing.")

            # Durable single page transaction: commits staging records, reconciles signatures, and saves checkpoint
            self.checkpoint_mgr.commit_page_transaction(
                page_batch=page_batch,
                category_index=cat_index,
                current_page=current_page + 1,
                completed_categories=list(self.category_yields.keys()),
                category_yields=self.category_yields,
                failed_routes=self.failed_routes,
                status="IN_PROGRESS",
                routes_signature=self.routes_signature,
                run_id=self.run_id,
                terminal_verified_routes=self.terminal_verified_routes,
                confirmed_store_number=self.confirmed_store_number,
                requests_made=self.requests_made,
            )

            # Check next page termination & reconcile source coverage scoped to category results pagination
            pagination_container = None
            container_selectors = [
                '[data-automation-id="pagination"]',
                'nav[aria-label*="pagination" i]',
                'nav[aria-label*="Pagination"]',
                '[data-testid="pagination"]',
                'nav.paginator',
                'ul.paginator-list',
                'div[data-testid="search-results"] nav',
                'main nav[aria-label*="pagination" i]',
                '#maincontent nav[aria-label*="pagination" i]'
            ]
            for sel in container_selectors:
                try:
                    elem = await page.query_selector(sel)
                    if elem:
                        pagination_container = elem
                        break
                except Exception:
                    continue

            next_btn = None
            if pagination_container:
                next_selectors = [
                    '[data-automation-id="pagination-next-page"]',
                    '[data-testid="pagination-next-page"]',
                    'a[aria-label*="Next Page" i]',
                    'button[aria-label*="Next Page" i]',
                    'a[aria-label*="next page" i]',
                    'button[aria-label*="next page" i]',
                    'a[aria-label="Next" i]',
                    'button[aria-label="Next" i]',
                    'li.paginator-btn-next a',
                    'li.paginator-btn-next button',
                    'button:has-text("Next")',
                    'a:has-text("Next")'
                ]
                for sel in next_selectors:
                    try:
                        candidate = await pagination_container.query_selector(sel)
                        if candidate:
                            next_btn = candidate
                            break
                    except Exception:
                        continue
            else:
                try:
                    next_btn = await page.query_selector(
                        '[data-automation-id="pagination-next-page"], [data-testid="pagination-next-page"]'
                    )
                except Exception:
                    next_btn = None

            is_disabled = False
            has_next_btn = next_btn is not None
            if next_btn:
                attr_dis = await next_btn.get_attribute("disabled")
                aria_dis = await next_btn.get_attribute("aria-disabled")
                cls_dis = await next_btn.get_attribute("class") or ""
                is_disabled = (attr_dis is not None) or (aria_dis == "true") or ("disabled" in cls_dis.lower())

            # Source coverage reconciliation:
            if is_disabled:
                terminal_reason = "Category pagination Next button disabled"
                logger.info(f"[CATEGORY COMPLETE] Naturally completed at terminal page {current_page} for '{sub_category}' ({terminal_reason}). Total category yield: {category_count}")
                natural_completion = True
                break
            elif not has_next_btn:
                has_term_ev, ev_reason = await check_explicit_terminal_evidence(
                    page,
                    len(product_elements),
                    current_page=current_page,
                    valid_items_count=len(page_extracted_sigs),
                )
                if has_term_ev:
                    terminal_reason = ev_reason
                    logger.info(f"[CATEGORY COMPLETE] Naturally completed single-page category for '{sub_category}' verified by explicit source terminal evidence: {ev_reason}. Total yield: {category_count}")
                    natural_completion = True
                    break
                else:
                    logger.error(
                        f"[AMBIGUOUS PAGINATION INCOMPLETE] Next selector missing on page {current_page} "
                        f"({len(product_elements)} containers) for route '{route_name}' without explicit terminal/total evidence "
                        f"({ev_reason}). A short page is not proof of exhaustion. Route remains incomplete."
                    )
                    if route_name not in self.failed_routes:
                        self.failed_routes.append(route_name)
                    route_failed = True
                    natural_completion = False
                    break

            # 3. Safety cap check: reaching max_pages_per_category with unharvested pages must remain incomplete
            if max_pages is not None and current_page >= max_pages:
                logger.error(f"[SAFETY CAP REACHED] Category '{route_name}' reached max_pages_per_category={max_pages} while additional pages exist. Route remains incomplete.")
                if route_name not in self.failed_routes:
                    self.failed_routes.append(route_name)
                route_failed = True
                natural_completion = False
                break

            current_page += 1

        # Durable Category Completion:
        if not route_failed and natural_completion:
            self.category_yields[route_name] = category_count
            self.terminal_verified_routes[route_name] = {
                "terminal_verified": True,
                "terminal_page": current_page,
                "store_number": self.confirmed_store_number or self.store.store_number,
                "reason": terminal_reason,
            }
            if route_name in self.failed_routes:
                self.failed_routes.remove(route_name)
            completed = list(self.category_yields.keys())
            self.checkpoint_mgr.commit_page_transaction(
                page_batch=[],
                category_index=cat_index + 1,
                current_page=1,
                completed_categories=completed,
                category_yields=self.category_yields,
                failed_routes=self.failed_routes,
                status="IN_PROGRESS",
                routes_signature=self.routes_signature,
                run_id=self.run_id,
                terminal_verified_routes=self.terminal_verified_routes,
                confirmed_store_number=self.confirmed_store_number,
                requests_made=self.requests_made,
            )
        elif self.budget_stop_reason:
            self.checkpoint_mgr.commit_page_transaction(
                page_batch=[],
                category_index=cat_index,
                current_page=current_page,
                completed_categories=list(self.category_yields.keys()),
                category_yields=self.category_yields,
                failed_routes=self.failed_routes,
                status="STOPPED_AT_LIMIT",
                routes_signature=self.routes_signature,
                run_id=self.run_id,
                terminal_verified_routes=self.terminal_verified_routes,
                confirmed_store_number=self.confirmed_store_number,
                requests_made=self.requests_made,
                stop_reason=self.budget_stop_reason,
            )
            logger.info(f"[CHECKPOINT BUDGET SAVED] Preserved '{route_name}' at page {current_page} ({self.budget_stop_reason}).")
        else:
            if route_name not in self.failed_routes:
                self.failed_routes.append(route_name)
            self.checkpoint_mgr.commit_page_transaction(
                page_batch=[],
                category_index=cat_index,
                current_page=current_page,
                completed_categories=list(self.category_yields.keys()),
                category_yields=self.category_yields,
                failed_routes=self.failed_routes,
                status="IN_PROGRESS",
                routes_signature=self.routes_signature,
                run_id=self.run_id,
                terminal_verified_routes=self.terminal_verified_routes,
                confirmed_store_number=self.confirmed_store_number,
                requests_made=self.requests_made,
            )
            logger.warning(f"[ROUTE UNRESOLVED] Route '{route_name}' remained incomplete (route_failed={route_failed}, natural_completion={natural_completion}). Preserving in failed_routes.")

        return category_count

    async def run(self) -> Dict[str, Any]:
        """
        Executes full multi-category scrape pipeline with staging protection.
        Fails closed if configured Azure Key Vault credential lookup fails.
        Stops cleanly on request/runtime budget limits while preserving durable state.
        Enforces store verification and terminal verification of all required categories and child routes.
        """
        start_time = time.time()
        self.run_start_monotonic = time.monotonic()
        logger.info(
            f"Starting scraper run {self.run_id} for Store #{self.store.store_number} "
            f"({self.store.address}) on {self.crawl_date}"
        )

        # Fail closed BEFORE launching Chromium if Key Vault lookup fails
        creds_ok, creds_reason = ensure_proxy_credentials_ready(self.settings)
        if not creds_ok:
            logger.error(
                f"[AZURE KEY VAULT FAIL-CLOSED] Halting run {self.run_id} for Store #{self.store.store_number}: {creds_reason}"
            )
            return {
                "success": False,
                "status": "CREDENTIAL_LOOKUP_FAILED",
                "reason": creds_reason,
                "error": "CREDENTIAL_LOOKUP_FAILED",
                "run_id": self.run_id,
                "store": f"Walmart #{self.store.store_number}",
                "total_records": len(self.scraped_records),
                "publication_gated": True,
            }

        if async_playwright is None:
            logger.error("[DEPENDENCY ERROR] 'playwright' Python library is not installed in the current environment. To run live browser collection, install via 'pip install playwright && playwright install chromium' or run in Azure Container App using scraper/Dockerfile.")
            return {
                "success": False,
                "reason": "playwright Python library is not installed. To execute live collection, install playwright or deploy using the Azure Container App Job Dockerfile in scraper/Dockerfile.",
                "total_records": len(self.scraped_records),
                "publication_gated": True,
                "error": "PLAYWRIGHT_NOT_INSTALLED"
            }

        live_run_ndjson_handler: Optional[NDJSONFileHandler] = None
        attached_ndjson_loggers: List[logging.Logger] = []
        if "unittest" not in sys.modules:
            try:
                os.makedirs(self.settings.output_directory, exist_ok=True)
                live_ndjson_path = os.path.join(
                    self.settings.output_directory,
                    f"live_execution_{self.store.store_number}_{self.crawl_date}.ndjson",
                )
                live_run_ndjson_handler = NDJSONFileHandler(live_ndjson_path, mode="a", encoding="utf-8")
                for log_name in ("WalmartScraper", "CheckpointManager", "AzureIntegration"):
                    target_logger = logging.getLogger(log_name)
                    target_logger.addHandler(live_run_ndjson_handler)
                    attached_ndjson_loggers.append(target_logger)
            except Exception as nd_err:
                logger.debug(f"[NDJSON HANDLER] Could not attach run-scoped live NDJSON handler: {nd_err}")

        interrupted_signal: Optional[str] = None
        previous_handlers: Dict[int, Any] = {}

        def _handle_stop_signal(signum, frame):
            nonlocal interrupted_signal
            interrupted_signal = f"SIGNAL_{signum}"
            logger.warning(f"[INTERRUPTION SIGNAL] Received {interrupted_signal}; halting safely and preserving checkpoint & prior delivery.")

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, _handle_stop_signal)
        except Exception:
            previous_handlers = {}

        categories_to_scrape: List[Dict[str, str]] = list(self.configured_routes)
        required_category_names: List[str] = []
        browser = None

        try:
            async with async_playwright() as p:
                proxy = self._get_proxy_dict()
                browser = await p.chromium.launch(
                    headless=self.settings.headless,
                    proxy=proxy,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars"
                    ]
                )

                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )

                page = await context.new_page()

                # Initialize store context with strict verification
                context_ok = await self.initialize_store_context(context, page)
                if not context_ok:
                    logger.error("[ABORT RUN] Could not verify store context and fulfillment locks. Halting scraper to prevent unverified publication.")
                    await browser.close()
                    browser = None
                    return {
                        "success": False,
                        "reason": "Store context and fulfillment verification failed.",
                        "run_id": self.run_id,
                        "store": f"Walmart #{self.store.store_number}",
                        "total_records": len(self.scraped_records),
                        "publication_gated": True
                    }

                if not categories_to_scrape:
                    categories_to_scrape = self._load_configured_routes()

                logger.info(f"Loaded {len(categories_to_scrape)} category/subcategory endpoints.")
                required_category_names = [f"{c.get('category')} > {c.get('sub_category')}" for c in categories_to_scrape]

                for idx, item in enumerate(categories_to_scrape):
                    if interrupted_signal:
                        route_key = f"{item.get('category', '')} > {item.get('sub_category', '')}"
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)
                        break

                    budget_reason = self._check_execution_budget()
                    if budget_reason:
                        self.budget_stop_reason = budget_reason
                        logger.warning(f"[BUDGET STOP] Cleanly stopping run {self.run_id}: {budget_reason}")
                        break

                    cat = item.get("category", "")
                    sub_cat = item.get("sub_category", "")
                    url = (item.get("walmart_url") or "").strip()
                    canary = item.get("canary_upc", "")
                    route_key = f"{cat} > {sub_cat}"

                    # If category already durably completed and terminal-verified without failed status, skip it
                    if route_key in self.category_yields and route_key not in self.failed_routes:
                        logger.info(f"[RESUME SKIP] Route '{route_key}' already durably completed ({self.category_yields[route_key]} items).")
                        continue

                    if not url:
                        logger.error(f"[INVALID ROUTE] Required route '{route_key}' has empty walmart_url.")
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)
                        continue

                    try:
                        await self.scrape_category(page, idx, cat, sub_cat, url, canary_upc=canary)
                        if route_key in self.category_yields and route_key in self.failed_routes:
                            self.failed_routes.remove(route_key)
                        if self.budget_stop_reason:
                            break
                    except (KeyboardInterrupt, asyncio.CancelledError) as int_err:
                        interrupted_signal = type(int_err).__name__
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)
                        logger.warning(f"[RUN INTERRUPTED] Route '{route_key}' interrupted by {interrupted_signal}. Preserving checkpoint.")
                        break
                    except Exception as route_err:
                        logger.error(f"[ROUTE FAILURE] Route '{route_key}' encountered unrecovered failure: {route_err}")
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)

                if browser is not None:
                    await browser.close()
                    browser = None
        except (KeyboardInterrupt, asyncio.CancelledError) as int_err:
            interrupted_signal = interrupted_signal or type(int_err).__name__
            logger.warning(f"[RUN INTERRUPTED] Scraper run aborted by {interrupted_signal}; preserving staging checkpoint and previous delivery.")
        finally:
            try:
                for sig, prev in previous_handlers.items():
                    signal.signal(sig, prev)
            except Exception:
                pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if live_run_ndjson_handler is not None:
                try:
                    for target_logger in attached_ndjson_loggers:
                        target_logger.removeHandler(live_run_ndjson_handler)
                    live_run_ndjson_handler.close()
                except Exception:
                    pass

        # Compute resume pointer: points to earliest unresolved/failed category index
        earliest_unresolved_idx = len(categories_to_scrape)
        for i, item in enumerate(categories_to_scrape):
            rk = f"{item.get('category')} > {item.get('sub_category')}"
            if rk in self.failed_routes or rk not in self.category_yields:
                earliest_unresolved_idx = i
                break

        has_unresolved = (
            (len(self.failed_routes) > 0)
            or (earliest_unresolved_idx < len(categories_to_scrape))
            or (interrupted_signal is not None)
            or bool(self.budget_stop_reason)
        )
        final_cat_idx = earliest_unresolved_idx if has_unresolved else len(categories_to_scrape)
        if interrupted_signal:
            final_status = "INTERRUPTED"
        elif self.budget_stop_reason:
            final_status = "STOPPED_AT_LIMIT"
        elif has_unresolved:
            final_status = "PARTIAL_WITH_FAILURES"
        else:
            final_status = "COMPLETED"

        # Commit final completed or partial checkpoint state
        preserved_page = self.checkpoint_mgr.load_checkpoint(expected_routes_signature=self.routes_signature).get("current_page", 1) if has_unresolved else 1
        self.checkpoint_mgr.save_checkpoint(
            category_index=final_cat_idx,
            current_page=preserved_page,
            completed_categories=list(self.category_yields.keys()),
            flushed_count=len(self.scraped_records),
            seen_signatures=list(self.seen_signatures),
            status=final_status,
            category_yields=self.category_yields,
            failed_routes=self.failed_routes,
            routes_signature=self.routes_signature,
            run_id=self.run_id,
            terminal_verified_routes=self.terminal_verified_routes,
            confirmed_store_number=self.confirmed_store_number,
            requests_made=self.requests_made,
            stop_reason=self.budget_stop_reason,
        )

        runtime_sec = int(time.time() - start_time)
        hours, remainder = divmod(runtime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"

        # Incomplete-Run / Budget-Stop Publication Protection Gate
        if interrupted_signal:
            is_promoted = False
            logger.warning(f"[PROTECTION ACTIVE] Run interrupted ({interrupted_signal}); previous committed delivery preserved intact.")
        elif self.budget_stop_reason:
            is_promoted = False
            logger.warning(f"[PROTECTION ACTIVE] Stopped cleanly at budget limit ({self.budget_stop_reason}); staging checkpoint preserved and prior delivery untouched.")
        else:
            is_promoted = self.checkpoint_mgr.promote_staging_to_production(
                min_threshold=self.settings.min_expected_records_per_run,
                required_categories=required_category_names,
                failed_routes=self.failed_routes,
                store_fulfillment_verified=self.store_fulfillment_verified,
                terminal_verified_routes=self.terminal_verified_routes,
                confirmed_store_number=self.confirmed_store_number,
                run_id=self.run_id,
            )

        azure_pub_result: Dict[str, Any] = {"uploaded": False, "reason": "Not promoted or Azure not configured"}
        if self._azure_publisher.is_configured():
            self._azure_publisher.sync_durable_state_up(
                self.store.store_number,
                self.checkpoint_mgr.staging_dir,
                self.checkpoint_mgr.output_dir,
            )
            if is_promoted:
                active_manifest = self.checkpoint_mgr.get_active_publication()
                azure_pub_result = self._azure_publisher.publish_committed_release(active_manifest)
                if azure_pub_result.get("uploaded") and active_manifest:
                    try:
                        updated_manifest = dict(active_manifest)
                        updated_manifest["azure_container"] = azure_pub_result.get("container", self.settings.azure_container_name)
                        updated_manifest["azure_products_blob"] = azure_pub_result.get("products_blob", "")
                        updated_manifest["azure_evidence_blob"] = azure_pub_result.get("evidence_blob", "")
                        updated_manifest["azure_publication"] = azure_pub_result
                        self.checkpoint_mgr._atomic_write_json(self.checkpoint_mgr.manifest_file, updated_manifest)
                    except Exception as man_err:
                        logger.warning(f"[AZURE MANIFEST SYNC] Could not persist azure metadata to local manifest: {man_err}")

        return {
            "success": is_promoted,
            "status": final_status,
            "run_id": self.run_id,
            "total_records": len(self.scraped_records),
            "requests_made": self.requests_made,
            "stop_reason": self.budget_stop_reason,
            "runtime": runtime_str,
            "store": f"Walmart #{self.store.store_number}",
            "location": self.store.address,
            "category_yields": self.category_yields,
            "failed_routes": self.failed_routes,
            "manifest_file": self.checkpoint_mgr.manifest_file,
            "output_file": self.checkpoint_mgr.production_target_file,
            "publication_gated": not is_promoted,
            "azure_publication": azure_pub_result,
        }

if __name__ == "__main__":
    import argparse
    try:
        from config import get_store_by_target
    except ImportError:
        from scraper.config import get_store_by_target

    parser = argparse.ArgumentParser(description="Production-Ready Walmart Scraper")
    parser.add_argument("--store", default=os.getenv("STORE_TARGET", DEFAULT_STORES[0].store_number), help="Store number, state code, or ZIP code")
    parser.add_argument("--crawl-date", default=None, help="Crawl date YYYY-MM-DD")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh instead of resuming from checkpoint")
    parser.add_argument("--staging-dir", default=os.getenv("STAGING_DIR", ".staging"), help="Staging and checkpoint directory")
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "output"), help="Output directory")
    parser.add_argument("--max-requests", type=int, default=None, help="Optional maximum page requests per invocation")
    parser.add_argument("--max-runtime-sec", type=float, default=None, help="Optional maximum runtime budget in seconds")
    args = parser.parse_args()

    try:
        store = get_store_by_target(args.store)
    except ValueError as err:
        logger.error(f"[INVALID STORE CONFIG] {err}")
        print(json.dumps({"success": False, "error": "INVALID_STORE_TARGET", "reason": str(err)}, indent=2))
        sys.exit(2)

    settings = get_settings()
    settings.staging_dir = args.staging_dir
    settings.output_directory = args.output_dir
    if args.max_requests is not None:
        settings.max_requests_per_run = args.max_requests
    if args.max_runtime_sec is not None:
        settings.max_runtime_seconds = args.max_runtime_sec

    scraper = WalmartProductionScraper(
        store,
        settings=settings,
        resume=not args.no_resume,
        staging_dir=args.staging_dir,
        crawl_date=args.crawl_date,
    )
    result = asyncio.run(scraper.run())
    try:
        try:
            from verify_live_gates import scan_workspace_and_write_status
        except ImportError:
            from scraper.verify_live_gates import scan_workspace_and_write_status
        gate_status = scan_workspace_and_write_status(
            output_dir=scraper.settings.output_directory,
            staging_dir=args.staging_dir,
        )
        result["live_gate_status_file"] = os.path.join("public", "data", "live_gate_status.json")
        result["has_verified_live_updates"] = gate_status.get("has_verified_live_updates", False)
    except Exception as gate_err:
        logger.debug(f"[GATE EVALUATOR] Skipped live status refresh: {gate_err}")
    print("Scraper Execution Completed:", json.dumps(result, indent=2))
    if result.get("error") == "CREDENTIAL_LOOKUP_FAILED":
        sys.exit(1)

