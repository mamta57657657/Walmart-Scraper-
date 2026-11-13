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
    from checkpoint_manager import CheckpointManager, sanitize_captured_request
    from azure_integration import resolve_key_vault_proxy_secrets, AzureBlobPublisher
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
    from scraper.checkpoint_manager import CheckpointManager, sanitize_captured_request
    from scraper.azure_integration import resolve_key_vault_proxy_secrets, AzureBlobPublisher

# Recognized affirmative fulfillment modes (reject substrings like NOT_PICKUP or PICKUP_UNAVAILABLE)
RECOGNIZED_AFFIRMATIVE_PICKUP_MODES = {
    "PICKUP",
    "STORE_PICKUP",
    "IN_STORE_PICKUP",
    "CURBSIDE_PICKUP",
    "GROCERY_PICKUP"
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

async def check_explicit_terminal_evidence(page: Any, containers_count: int, current_page: int = 1) -> Tuple[bool, str]:
    """
    Checks for explicit source terminal or total results evidence confirming category exhaustion.
    A short page (< 24 items) alone is NOT proof of exhaustion.
    Explicit source indicators required:
    1. Category pagination Next button present and disabled (scoped to pagination navigation,
       rejecting generic/unrelated disabled buttons from carousels, shelves, or modals).
    2. Explicit page indicator comparing current versus last page exactly (e.g. 'Page 1 of 1',
       '1 of 1', 'Page 3 of 3'), rejecting substring false-positives like 'Page 1 of 10'.
    3. Explicit source total results count matching containers_count (e.g. '5 results' for 5 items)
       strictly scoped to the category search/header area (rejecting unrelated cart counts or reviews).
    """
    if not page:
        return False, "No page object provided"

    # 1. Scoped Category Pagination Next button check
    # Locate category pagination navigation container first to avoid matching unrelated carousel/modal buttons
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

    # Search for Next control strictly inside category pagination container
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
        # Fallback only to dedicated pagination automation ID if container not wrapped in nav
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

    # 2. Check for explicit exact pagination indicator: parse current vs last page numbers exactly
    # Must NOT use substring checks like '1 of 1' in text, which incorrectly matches 'Page 1 of 10'!
    try:
        pagination_elem = pagination_container
        if not pagination_elem:
            pagination_elem = await page.query_selector(
                '[data-automation-id="pagination"], nav[aria-label*="pagination" i], nav[aria-label*="Pagination"], [data-testid="pagination"], ul.paginator-list'
            )
        if pagination_elem:
            pag_text = (await pagination_elem.inner_text()).strip()
            # Match exact patterns: "Page 1 of 10", "1 of 10", "Page 1 of 1", "1 of 1", "Page 3 / 3"
            m_pages = re.search(r'\b(?:page\s+)?(\d+)\s*(?:of|\/)\s*(\d+)\b', pag_text, re.IGNORECASE)
            if m_pages:
                parsed_curr = int(m_pages.group(1))
                parsed_last = int(m_pages.group(2))
                if parsed_curr == parsed_last and parsed_last >= 1:
                    if current_page is None or parsed_curr == current_page or parsed_last == 1:
                        return True, f"Explicit pagination terminal indicator confirmed (page {parsed_curr} of {parsed_last}): '{pag_text}'"
                elif parsed_curr < parsed_last:
                    # Explicit non-terminal evidence: current page is before last page (e.g. Page 1 of 10)
                    return False, f"Explicit pagination confirms active non-terminal page ({parsed_curr} of {parsed_last}): '{pag_text}'"
    except Exception as ex:
        logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying pagination indicator: {ex}")

    # 3. Check for explicit source total results count matching container count
    # Scoped strictly to category search header or results summary (rejecting generic body, cart, or review counts)
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
        # Match category results summary patterns, e.g.:
        # "Showing 1-5 of 5 results", "1-5 of 5 products", "5 results", "5 products"
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
        staging_dir: str = ".staging",
        crawl_date: Optional[str] = None
    ):
        self.store = store
        self.settings = settings or get_settings()
        self.crawl_date = crawl_date or datetime.now().strftime("%Y-%m-%d")
        self.checkpoint_mgr = CheckpointManager(
            store_number=self.store.store_number,
            crawl_date=self.crawl_date,
            staging_dir=staging_dir,
            output_dir=self.settings.output_directory
        )
        # Adopt reconciled crawl date from checkpoint manager (cross-midnight preservation)
        self.crawl_date = self.checkpoint_mgr.crawl_date
        self.resume = resume
        self.checkpoint_state = self.checkpoint_mgr.load_checkpoint() if resume else {}
        self.scraped_records: List[Dict[str, str]] = self.checkpoint_mgr.load_staging_records() if resume else []
        # Reconcile seen signatures directly from staging records to eliminate drift
        self.seen_signatures = self.checkpoint_mgr.reconcile_signatures_from_staging() if resume else set()
        self.category_yields: Dict[str, int] = dict(self.checkpoint_state.get("category_yields", {})) if resume else {}
        self.canary_results: Dict[str, bool] = {}
        # Restore unresolved / failed routes from checkpoint state on resume
        self.failed_routes: List[str] = list(self.checkpoint_state.get("failed_routes", [])) if resume else []
        self.store_fulfillment_verified: bool = False
        self.observed_availability_transitions: List[Dict[str, Any]] = []

        # Current page context tracking & page-scoped intercepted network items
        self.current_page_number: int = 1
        self.current_page_url: str = ""
        self.fatal_evidence_error: bool = False
        self.current_page_intercepted_items: Dict[str, Dict[str, Any]] = {}

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
        Extracts store affinity, fulfillment mode, and item-level price/availability
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

        observed_store_id = (
            search_res.get("storeId")
            or data_root.get("storeId")
            or (pickup_store.get("storeId") if isinstance(pickup_store, dict) else None)
        )
        observed_fulfillment_mode = (
            search_res.get("fulfillmentMode")
            or data_root.get("fulfillmentMode")
            or (loc_ctx.get("intent") if isinstance(loc_ctx, dict) else None)
        )

        verified = False
        if observed_store_id and str(observed_store_id) == str(self.store.store_number):
            if is_exact_affirmative_fulfillment(observed_fulfillment_mode):
                verified = True

        capture_id = self.checkpoint_mgr.append_raw_evidence(
            endpoint=endpoint_url,
            request_data=request_data or {"url": endpoint_url, "method": "GET", "headers": {}},
            response_payload=j_data
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

                f_info = itm.get("fulfillment")
                pickup_avail = None
                instore_stock = None
                if isinstance(f_info, dict):
                    pickup_avail = f_info.get("pickupAvailable")
                    instore_stock = f_info.get("inStoreStock")
                elif isinstance(itm.get("availabilityStatusV2"), dict):
                    avail_val = itm["availabilityStatusV2"].get("value")
                    if avail_val == "IN_STOCK":
                        pickup_avail = True
                        instore_stock = True
                    elif avail_val in {"OUT_OF_STOCK", "NOT_AVAILABLE"}:
                        pickup_avail = False
                        instore_stock = False

                item_store = itm.get("storeId") or observed_store_id
                item_fulfill = itm.get("fulfillmentMode") or observed_fulfillment_mode

                p_info = itm.get("priceInfo") or {}
                line_p = (
                    p_info.get("linePrice")
                    or (p_info.get("currentPrice", {}) or {}).get("priceString")
                    or itm.get("price")
                    or ""
                )

                self.current_page_intercepted_items[itm_id] = {
                    "capture_id": capture_id,
                    "page_number": self.current_page_number,
                    "page_url": self.current_page_url,
                    "store_id": str(item_store) if item_store is not None else None,
                    "fulfillment_mode": str(item_fulfill) if item_fulfill is not None else None,
                    "pickup_available": pickup_avail,
                    "in_store_stock": instore_stock,
                    "observed_sale_price": str(line_p) if line_p else "",
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

        # Resume logic (preserve prior staged unique-item yield when resuming mid-category)
        if self.checkpoint_state.get("category_index") == cat_index:
            current_page = max(1, self.checkpoint_state.get("current_page", 1))
            prior_staged = sum(
                1 for r in self.scraped_records
                if r.get("category") == category and r.get("sub_category") == sub_category
            )
            category_count = prior_staged
            logger.info(f"[CHECKPOINT RESUME] Resuming category '{sub_category}' from page {current_page} (prior staged items: {prior_staged})")

        # Explicit handling for resume beyond a safety cap:
        # If saved current_page already exceeds max_pages_per_category without natural completion,
        # preserve the unresolved route as incomplete in failed_routes and do not attempt to commit.
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

            # Check for hydration failure on any page: 0 containers without explicit zero-results confirmation is an error
            if len(product_elements) == 0:
                body_text = (await page.inner_text("body")).lower() if page else ""
                has_zero_results = any(term in body_text for term in ["0 results", "no products found", "no items found", "we found 0"])
                if not has_zero_results:
                    logger.error(f"[HYDRATION FAILURE] Page {current_page} for '{route_name}' rendered 0 product containers without explicit zero-results confirmation.")
                    if route_name not in self.failed_routes:
                        self.failed_routes.append(route_name)
                    route_failed = True
                    break

            if not self.current_page_intercepted_items:
                await self._capture_ssr_next_data_if_present(page, paged_url)

            page_batch: List[Dict[str, str]] = []

            for el in product_elements:
                try:
                    # 1. Exclude Sponsored Placements
                    is_sponsored = await el.query_selector('[data-testid="sponsored-badge"], span:has-text("Sponsored")')
                    if is_sponsored:
                        continue

                    # 2. Exclude 3P Marketplace items
                    raw_text = (await el.inner_text()) if el else ""
                    if "sold by" in raw_text.lower() and "walmart" not in raw_text.lower():
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

                    # Traceable Page-Scoped Price Binding & Source Evidence
                    # Exact recognized fulfillment and affirmative availability required
                    bound_item = self.current_page_intercepted_items.get(raw_item_id)
                    is_verified_local_pickup = False
                    is_eligible_store_assortment = True

                    if bound_item is None or bound_item.get("page_number") != current_page:
                        is_verified_local_pickup = False
                        logger.debug(f"[UNMATCHED ITEM] No current-page intercepted network payload for item {raw_item_id} ('{title}'). Cannot qualify as verified local price.")
                    else:
                        observed_store = bound_item.get("store_id")
                        observed_fulfillment = bound_item.get("fulfillment_mode")
                        pickup_available = bound_item.get("pickup_available")

                        # Item must belong to target store to be in store assortment
                        if not observed_store or str(observed_store) != str(self.store.store_number):
                            is_verified_local_pickup = False
                            is_eligible_store_assortment = False
                        # Require exact recognized affirmative fulfillment (rejects NOT_PICKUP / PICKUP_UNAVAILABLE)
                        elif not is_exact_affirmative_fulfillment(observed_fulfillment):
                            is_verified_local_pickup = False
                        # Require affirmative availability (rejects None, False, 'false', '0', 'unavailable')
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

                    # 11. Store brand detection
                    store_brand = detect_store_brand(title)

                    # Build conforming 22-field record
                    # All four Walmart deal fields are strictly empty strings per mandate
                    # Genuinely displayed source fields (title, weight, image, url) are preserved even if unavailable
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
                    if sig not in self.seen_signatures:
                        self.seen_signatures.add(sig)
                        page_batch.append(ordered)
                        category_count += 1

                except Exception as item_err:
                    logger.debug(f"[ITEM PARSE ERROR] Skipping unparseable element: {item_err}")
                    continue

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
                status="IN_PROGRESS"
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
            # 1. Next button explicitly present and disabled in category pagination -> verified natural completion
            if is_disabled:
                logger.info(f"[CATEGORY COMPLETE] Naturally completed at terminal page {current_page} for '{sub_category}' (Category pagination Next button disabled). Total category yield: {category_count}")
                natural_completion = True
                break
            # 2. Next selector missing entirely -> require explicit source terminal/total evidence
            elif not has_next_btn:
                # A short page (< 24 items) alone is NOT proof of exhaustion!
                # Require explicit source terminal/total evidence to confirm exhaustion
                has_term_ev, ev_reason = await check_explicit_terminal_evidence(page, len(product_elements), current_page=current_page)
                if has_term_ev:
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
        # Commit category completion and yields durably to disk ONLY if route succeeded naturally
        if not route_failed and natural_completion:
            self.category_yields[route_name] = category_count
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
                status="IN_PROGRESS"
            )
        else:
            if route_name not in self.failed_routes:
                self.failed_routes.append(route_name)
            # Durably record unresolved failed route to disk so checkpoint state reflects incomplete route
            self.checkpoint_mgr.commit_page_transaction(
                page_batch=[],
                category_index=cat_index,
                current_page=current_page,
                completed_categories=list(self.category_yields.keys()),
                category_yields=self.category_yields,
                failed_routes=self.failed_routes,
                status="IN_PROGRESS"
            )
            logger.warning(f"[ROUTE UNRESOLVED] Route '{route_name}' remained incomplete (route_failed={route_failed}, natural_completion={natural_completion}). Preserving in failed_routes.")

        return category_count

    async def run(self) -> Dict[str, Any]:
        """
        Executes full multi-category scrape pipeline with staging protection.
        Interruption-safe and publication-gated.
        Enforces complete category routes; failed/blocked routes remain incomplete.
        Persists unresolved work and resumes directly from earliest failed/incomplete route.
        """
        start_time = time.time()
        logger.info(f"Starting scraper run for Store #{self.store.store_number} ({self.store.address}) on {self.crawl_date}")

        if async_playwright is None:
            logger.error("[DEPENDENCY ERROR] 'playwright' Python library is not installed in the current environment. To run live browser collection, install via 'pip install playwright && playwright install chromium' or run in Azure Container App using scraper/Dockerfile.")
            return {
                "success": False,
                "reason": "playwright Python library is not installed. To execute live collection, install playwright or deploy using the Azure Container App Job Dockerfile in scraper/Dockerfile.",
                "total_records": len(self.scraped_records),
                "publication_gated": True,
                "error": "PLAYWRIGHT_NOT_INSTALLED"
            }

        # Hydrate proxy credentials from Azure Key Vault if configured
        resolve_key_vault_proxy_secrets(self.settings)

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

        categories_to_scrape: List[Dict[str, str]] = []
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
                        "total_records": len(self.scraped_records),
                        "publication_gated": True
                    }

                # Load taxonomy CSV
                csv_path = self.settings.categories_csv_path
                if not os.path.exists(csv_path):
                    csv_path = os.path.join(os.path.dirname(__file__), "Walmart_Category_URLs.csv")

                if os.path.exists(csv_path):
                    with open(csv_path, mode="r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            categories_to_scrape.append(row)

                logger.info(f"Loaded {len(categories_to_scrape)} category/subcategory endpoints.")
                required_category_names = [f"{c.get('category')} > {c.get('sub_category')}" for c in categories_to_scrape]

                # Resume execution: Iterate through categories, skipping already verified completed categories
                # and retrying any unresolved or previously failed routes
                for idx, item in enumerate(categories_to_scrape):
                    if interrupted_signal:
                        route_key = f"{item.get('category', '')} > {item.get('sub_category', '')}"
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)
                        break

                    cat = item.get("category", "")
                    sub_cat = item.get("sub_category", "")
                    url = item.get("walmart_url", "")
                    canary = item.get("canary_upc", "")
                    route_key = f"{cat} > {sub_cat}"

                    # If category already durably completed and not marked failed, skip it
                    if route_key in self.category_yields and route_key not in self.failed_routes:
                        logger.info(f"[RESUME SKIP] Route '{route_key}' already durably completed ({self.category_yields[route_key]} items).")
                        continue

                    if url:
                        try:
                            await self.scrape_category(page, idx, cat, sub_cat, url, canary_upc=canary)
                            # If route was in failed_routes and succeeded, remove from failed_routes
                            if route_key in self.category_yields and route_key in self.failed_routes:
                                self.failed_routes.remove(route_key)
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

        # Compute resume pointer: points to earliest unresolved/failed category index
        # Never advance category_index to total count when unresolved work remains!
        earliest_unresolved_idx = len(categories_to_scrape)
        for i, item in enumerate(categories_to_scrape):
            rk = f"{item.get('category')} > {item.get('sub_category')}"
            if rk in self.failed_routes or rk not in self.category_yields:
                earliest_unresolved_idx = i
                break

        has_unresolved = (len(self.failed_routes) > 0) or (earliest_unresolved_idx < len(categories_to_scrape)) or (interrupted_signal is not None)
        final_cat_idx = earliest_unresolved_idx if has_unresolved else len(categories_to_scrape)
        final_status = "INTERRUPTED" if interrupted_signal else ("PARTIAL_WITH_FAILURES" if has_unresolved else "COMPLETED")

        # Commit final completed or partial checkpoint state with failed_routes
        preserved_page = self.checkpoint_mgr.load_checkpoint().get("current_page", 1) if has_unresolved else 1
        self.checkpoint_mgr.save_checkpoint(
            category_index=final_cat_idx,
            current_page=preserved_page,
            completed_categories=list(self.category_yields.keys()),
            flushed_count=len(self.scraped_records),
            seen_signatures=list(self.seen_signatures),
            status=final_status,
            category_yields=self.category_yields,
            failed_routes=self.failed_routes
        )

        runtime_sec = int(time.time() - start_time)
        hours, remainder = divmod(runtime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"

        # Incomplete-Run Publication Protection Gate Evaluation with atomic committed pointer
        if interrupted_signal:
            is_promoted = False
            logger.warning(f"[PROTECTION ACTIVE] Run interrupted ({interrupted_signal}); previous committed delivery preserved intact.")
        else:
            is_promoted = self.checkpoint_mgr.promote_staging_to_production(
                min_threshold=self.settings.min_expected_records_per_run,
                required_categories=required_category_names,
                failed_routes=self.failed_routes,
                store_fulfillment_verified=self.store_fulfillment_verified
            )

        azure_pub_result: Dict[str, Any] = {"uploaded": False, "reason": "Not promoted or Azure not configured"}
        if is_promoted:
            publisher = AzureBlobPublisher(
                connection_string=self.settings.azure_storage_connection_string,
                account_url=self.settings.azure_storage_account_url,
                container_name=self.settings.azure_container_name,
            )
            if publisher.is_configured():
                azure_pub_result = publisher.publish_committed_release(self.checkpoint_mgr.get_active_publication())

        return {
            "success": is_promoted,
            "status": final_status,
            "total_records": len(self.scraped_records),
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
    parser.add_argument("--staging-dir", default=".staging", help="Staging and checkpoint directory")
    args = parser.parse_args()

    store = get_store_by_target(args.store)
    scraper = WalmartProductionScraper(
        store,
        resume=not args.no_resume,
        staging_dir=args.staging_dir,
        crawl_date=args.crawl_date,
    )
    result = asyncio.run(scraper.run())
    print("Scraper Execution Completed:", json.dumps(result, indent=2))

