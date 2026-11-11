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

async def check_explicit_terminal_evidence(page: Any, containers_count: int) -> Tuple[bool, str]:
    """
    Checks for explicit source terminal or total results evidence confirming category exhaustion.
    A short page (< 24 items) alone is NOT proof of exhaustion.
    Explicit source indicators required:
    1. Next button present and disabled (disabled attribute or aria-disabled="true")
    2. Explicit 1-of-1 pagination indicator (e.g. '1 of 1' / 'Page 1 of 1')
    3. Explicit source total results count matching containers_count (e.g. '5 results' for 5 items)
    """
    if not page:
        return False, "No page object provided"

    # 1. Check for Next button explicitly present and disabled
    try:
        next_btn = await page.query_selector(
            '[aria-label="Next Page"], a[aria-label="next page"], [data-automation-id="pagination-next-page"], button:has-text("Next")'
        )
        if next_btn:
            attr_dis = await next_btn.get_attribute("disabled")
            aria_dis = await next_btn.get_attribute("aria-disabled")
            if (attr_dis is not None) or (aria_dis == "true"):
                return True, "Next button explicitly present and disabled"
    except Exception as ex:
        logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying next button: {ex}")

    # 2. Check for explicit 1-of-1 pagination indicator
    try:
        pagination_elem = await page.query_selector(
            '[data-automation-id="pagination"], nav[aria-label*="pagination"], nav[aria-label*="Pagination"], ul.paginator-list'
        )
        if pagination_elem:
            pag_text = (await pagination_elem.inner_text()).lower()
            if "1 of 1" in pag_text or "page 1 of 1" in pag_text:
                return True, f"Explicit pagination indicator '1 of 1' confirmed: '{pag_text.strip()}'"
    except Exception as ex:
        logger.debug(f"[TERMINAL EVIDENCE CHECK] Error querying pagination indicator: {ex}")

    # 3. Check for explicit source total results count matching container count
    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    if body_text and containers_count > 0:
        # Match "showing 1-5 of 5 results" or "5 results" or "5 products"
        m_showing = re.search(r'(?:showing\s+)?(?:\d+\s*-\s*)?(\d+)\s+of\s+(\d+)\s+(?:results|items|products)', body_text, re.IGNORECASE)
        if m_showing:
            showing_end = int(m_showing.group(1))
            total_items = int(m_showing.group(2))
            if total_items == containers_count or (showing_end == containers_count and total_items == containers_count):
                return True, f"Explicit source total count '{total_items}' matches container count '{containers_count}'"

        m_exact = re.search(r'\b(\d+)\s+(?:results|items|products)\b', body_text, re.IGNORECASE)
        if m_exact:
            total_items = int(m_exact.group(1))
            if total_items == containers_count:
                return True, f"Explicit source total results '{total_items}' matches container count '{containers_count}'"

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
                        search_res = j_data.get("data", {}).get("searchResult", {}) or j_data.get("data", {}).get("browse", {})
                        stacks = search_res.get("itemStacks", []) or [search_res.get("itemStack", {})]

                        # Rule 1: Keep unknown context unknown! Never fill missing storeId or fulfillmentMode with target defaults
                        observed_store_id = search_res.get("storeId")
                        if observed_store_id is None:
                            observed_store_id = j_data.get("data", {}).get("storeId")

                        observed_fulfillment_mode = search_res.get("fulfillmentMode")
                        if observed_fulfillment_mode is None:
                            observed_fulfillment_mode = j_data.get("data", {}).get("fulfillmentMode")

                        # Observed store and exact affirmative fulfillment verification:
                        # Requires exact store ID match and exact recognized affirmative fulfillment (rejects NOT_PICKUP / PICKUP_UNAVAILABLE)
                        if observed_store_id and str(observed_store_id) == str(self.store.store_number):
                            if is_exact_affirmative_fulfillment(observed_fulfillment_mode):
                                price_bearing_response_verified = True

                        # Sanitize captured request including Authorization tokens and cookies
                        raw_headers = dict(resp.request.headers) if hasattr(resp, "request") and hasattr(resp.request, "headers") else {}
                        captured_req = {
                            "url": resp.request.url if hasattr(resp, "request") else resp.url,
                            "method": resp.request.method if hasattr(resp, "request") else "GET",
                            "headers": raw_headers,
                            "post_data": resp.request.post_data if hasattr(resp, "request") and hasattr(resp.request, "post_data") else None
                        }

                        # Append raw evidence and obtain traceable capture ID
                        capture_id = self.checkpoint_mgr.append_raw_evidence(
                            endpoint=resp.url,
                            request_data=captured_req,
                            response_payload=j_data
                        )

                        for stk in stacks:
                            for itm in stk.get("items", []):
                                itm_id = str(itm.get("usItemId") or itm.get("id") or "").strip()
                                if itm_id:
                                    f_info = itm.get("fulfillment")
                                    pickup_avail = None
                                    instore_stock = None
                                    if isinstance(f_info, dict):
                                        pickup_avail = f_info.get("pickupAvailable")
                                        instore_stock = f_info.get("inStoreStock")

                                    p_info = itm.get("priceInfo") or {}
                                    line_p = p_info.get("linePrice") or p_info.get("currentPrice", {}).get("priceString") or itm.get("price") or ""

                                    self.current_page_intercepted_items[itm_id] = {
                                        "capture_id": capture_id,
                                        "page_number": self.current_page_number,
                                        "page_url": self.current_page_url,
                                        "store_id": str(observed_store_id) if observed_store_id is not None else None,
                                        "fulfillment_mode": str(observed_fulfillment_mode) if observed_fulfillment_mode is not None else None,
                                        "pickup_available": pickup_avail,
                                        "in_store_stock": instore_stock,
                                        "observed_sale_price": str(line_p) if line_p else "",
                                    }

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

        # Resume logic
        if self.checkpoint_state.get("category_index") == cat_index:
            current_page = max(1, self.checkpoint_state.get("current_page", 1))
            logger.info(f"[CHECKPOINT RESUME] Resuming category '{sub_category}' from page {current_page}")

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

            # Check next page termination & reconcile source coverage
            next_btn = await page.query_selector('[aria-label="Next Page"], a[aria-label="next page"], [data-automation-id="pagination-next-page"]')
            is_disabled = False
            has_next_btn = next_btn is not None
            if next_btn:
                attr_dis = await next_btn.get_attribute("disabled")
                aria_dis = await next_btn.get_attribute("aria-disabled")
                is_disabled = (attr_dis is not None) or (aria_dis == "true")

            # Source coverage reconciliation:
            # 1. Next button explicitly present and disabled -> verified natural completion
            if is_disabled:
                logger.info(f"[CATEGORY COMPLETE] Naturally completed at terminal page {current_page} for '{sub_category}' (Next button disabled). Total category yield: {category_count}")
                natural_completion = True
                break
            # 2. Next selector missing entirely -> require explicit source terminal/total evidence
            elif not has_next_btn:
                # A short page (< 24 items) alone is NOT proof of exhaustion!
                # Require explicit source terminal/total evidence to confirm exhaustion
                has_term_ev, ev_reason = await check_explicit_terminal_evidence(page, len(product_elements))
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

            categories_to_scrape = []
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
                    except Exception as route_err:
                        logger.error(f"[ROUTE FAILURE] Route '{route_key}' encountered unrecovered failure: {route_err}")
                        if route_key not in self.failed_routes:
                            self.failed_routes.append(route_key)

            await browser.close()

        # Compute resume pointer: points to earliest unresolved/failed category index
        # Never advance category_index to total count when unresolved work remains!
        earliest_unresolved_idx = len(categories_to_scrape)
        for i, item in enumerate(categories_to_scrape):
            rk = f"{item.get('category')} > {item.get('sub_category')}"
            if rk in self.failed_routes or rk not in self.category_yields:
                earliest_unresolved_idx = i
                break

        final_cat_idx = earliest_unresolved_idx if len(self.failed_routes) > 0 else len(categories_to_scrape)
        final_status = "COMPLETED" if len(self.failed_routes) == 0 else "PARTIAL_WITH_FAILURES"

        # Commit final completed or partial checkpoint state with failed_routes
        self.checkpoint_mgr.save_checkpoint(
            category_index=final_cat_idx,
            current_page=1,
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
        is_promoted = self.checkpoint_mgr.promote_staging_to_production(
            min_threshold=self.settings.min_expected_records_per_run,
            required_categories=required_category_names,
            failed_routes=self.failed_routes,
            store_fulfillment_verified=self.store_fulfillment_verified
        )

        return {
            "success": is_promoted,
            "total_records": len(self.scraped_records),
            "runtime": runtime_str,
            "store": f"Walmart #{self.store.store_number}",
            "location": self.store.address,
            "category_yields": self.category_yields,
            "failed_routes": self.failed_routes,
            "manifest_file": self.checkpoint_mgr.manifest_file,
            "output_file": self.checkpoint_mgr.production_target_file,
            "publication_gated": not is_promoted
        }

if __name__ == "__main__":
    store = DEFAULT_STORES[0]
    scraper = WalmartProductionScraper(store)
    result = asyncio.run(scraper.run())
    print("Scraper Execution Completed:", json.dumps(result, indent=2))
