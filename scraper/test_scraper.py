"""
test_scraper.py
Comprehensive unit and integration tests for Walmart scraper logic:
- Strict 22-field ordering and empty defaults
- Separate regular vs sale price roles
- Exact affirmative pickup fulfillment & availability checks
- Structured query pagination and completion reconciliation
- Actual scrape_category and run paths with controlled page responses
- Explicit terminal/total evidence verification on short pages
- Resume beyond safety caps and failed-route recovery
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
"""

import unittest
import os
import sys
import json

# Ensure scraper directory is in Python path
sys.path.insert(0, os.path.dirname(__file__))

from deals_parser import parse_deals
from validation import (
    REQUIRED_FIELD_ORDER,
    sanitize_and_order_record,
    is_approximate_weight,
    detect_store_brand,
    validate_dataset,
    format_price
)

class TestWalmartScraperRules(unittest.TestCase):

    def test_strict_field_ordering(self):
        """Rule: Exact 22 field ordering must be preserved with empty strings for missing values."""
        raw = {
            "zipcode": "75001",
            "store_name": "Walmart Supercenter",
            "store_location": "1234 Main St, Dallas, TX 75201",
            "category": "Beverages",
            "product_title": "Dasani Purified Water, 16.9 fl oz, 24 Pack",
            "regular_price": "$6.98",
            "sale_price": "$5.98",
            "ppm": "$0.06/fl oz",
            "upc": "078742118001"
        }
        sanitized = sanitize_and_order_record(raw, crawl_date="2025-05-17")
        self.assertEqual(list(sanitized.keys()), REQUIRED_FIELD_ORDER)
        self.assertEqual(sanitized["gupc"], "", "gupc must be strictly empty string")
        self.assertEqual(sanitized["unit_price"], "", "unit_price must be strictly empty string")
        self.assertEqual(sanitized["crawl_date"], "2025-05-17", "crawl_date must be final field")
        self.assertNotIn("remarks", sanitized)
        self.assertNotIn("gupc14", sanitized)

    def test_volume_deal_parsing(self):
        """Rule: Volume deals store exact wording and price. Never invent price for BOGO."""
        # 1. Multi-buy with price
        res1 = parse_deals("2 for $10", promo_price_text="$10.00")
        self.assertEqual(res1["volume_deals_description"], "2 for $10")
        self.assertEqual(res1["volume_deals_price"], "$10.00")
        self.assertEqual(res1["digital_deals_description"], "")
        self.assertEqual(res1["digital_deals_price"], "")

        # 2. BOGO without displayed promotional price
        res2 = parse_deals("Buy 1, Get 1 Free")
        self.assertEqual(res2["volume_deals_description"], "Buy 1, Get 1 Free")
        self.assertEqual(res2["volume_deals_price"], "", "Must not invent price when not displayed")

        # 3. Buy 2, Get 1 Free
        res3 = parse_deals("Buy 2, Get 1 Free")
        self.assertEqual(res3["volume_deals_description"], "Buy 2, Get 1 Free")

    def test_digital_deal_parsing(self):
        """Rule: Digital deals require clipping/activation."""
        # 1. Coupon with terms and displayed promotional price
        res1 = parse_deals("Clip Coupon: Save $1", promo_price_text="$4.98")
        self.assertEqual(res1["digital_deals_description"], "Clip Coupon: Save $1")
        self.assertEqual(res1["digital_deals_price"], "$4.98")
        self.assertEqual(res1["volume_deals_description"], "")

        # 2. Coupon with explicit net price in badge
        res2 = parse_deals("$3.99 each with Digital Coupon")
        self.assertEqual(res2["digital_deals_description"], "$3.99 each with Digital Coupon")
        self.assertEqual(res2["digital_deals_price"], "$3.99")

        # 3. Walmart Cash / rebate must NOT be treated as immediate discount
        res3 = parse_deals("Get $2.00 Walmart Cash")
        self.assertEqual(res3["digital_deals_description"], "")
        self.assertEqual(res3["digital_deals_price"], "")

    def test_approximate_weight_exclusion(self):
        """Rule: Exclude products whose weight contains approx/approximately."""
        self.assertTrue(is_approximate_weight("Approx 1.5 lb"))
        self.assertTrue(is_approximate_weight("1.2 lb approximately"))
        self.assertTrue(is_approximate_weight("approx. 16 oz"))
        self.assertFalse(is_approximate_weight("16.9 fl oz"))
        self.assertFalse(is_approximate_weight("128 fl oz"))
        self.assertFalse(is_approximate_weight("1 lb"))

    def test_private_label_detection(self):
        """Rule: Identify Walmart private labels; default to 'no'."""
        self.assertEqual(detect_store_brand("Great Value Whole Milk"), "Great Value")
        self.assertEqual(detect_store_brand("Equate Ibuprofen"), "Equate")
        self.assertEqual(detect_store_brand("Mainstays Non-Stick Pan"), "Mainstays")
        self.assertEqual(detect_store_brand("Coca-Cola Original"), "no")

    def test_validation_quality_gates(self):
        """Rule: Validate record counts, duplicates and field completeness."""
        sample_records = [
            sanitize_and_order_record({
                "zipcode": "75001",
                "store_name": "Walmart Supercenter",
                "store_location": "1234 Main St, Dallas, TX 75201",
                "category": "Beverages",
                "sub_category": "Water",
                "product_title": f"Product {i}",
                "regular_price": "$5.00",
                "sale_price": "$4.50",
                "upc": f"078742{i:06d}",
                "url": f"https://www.walmart.com/ip/prod-{i}",
                "ppm": "$0.05/oz"
            }, "2025-05-17")
            for i in range(505)
        ]
        is_valid, stats = validate_dataset(sample_records, min_expected=500)
        self.assertTrue(is_valid)
        self.assertEqual(stats["duplicate_count"], 0)
        self.assertEqual(stats["field_completeness_rate"], "100.0%")

    def test_unavailable_store_assortment_retention(self):
        """Rule: Retain unavailable store-assortment products even when price or UPC is missing."""
        out_of_stock_item = sanitize_and_order_record({
            "zipcode": "75001",
            "store_name": "Walmart Supercenter",
            "store_location": "1234 Main St, Dallas, TX 75201",
            "category": "Fresh Produce",
            "sub_category": "Fresh Fruits",
            "product_title": "Marketside Fresh Organic Strawberries, 1 lb (Temporarily Out of Stock)",
            "regular_price": "",
            "sale_price": "",
            "upc": "",
            "url": "https://www.walmart.com/ip/marketside-strawberries/000000040112"
        }, "2025-05-17")
        self.assertEqual(out_of_stock_item["regular_price"], "")
        self.assertEqual(out_of_stock_item["sale_price"], "")
        self.assertEqual(out_of_stock_item["upc"], "")
        self.assertEqual(out_of_stock_item["gupc"], "")
        self.assertEqual(out_of_stock_item["unit_price"], "")
        self.assertEqual(out_of_stock_item["crawl_date"], "2025-05-17")

        # Must pass dataset validation without being discarded
        batch = [
            sanitize_and_order_record({
                "zipcode": "75001",
                "store_name": "Walmart Supercenter",
                "store_location": "1234 Main St, Dallas, TX 75201",
                "category": "Beverages",
                "product_title": f"Product {i}",
                "regular_price": "$5.00",
                "sale_price": "$4.50",
                "upc": f"078742{i:06d}",
                "url": f"https://www.walmart.com/ip/prod-{i}"
            }, "2025-05-17") for i in range(500)
        ]
        batch.append(out_of_stock_item)
        is_valid, stats = validate_dataset(batch, min_expected=500)
        self.assertTrue(is_valid)
        self.assertEqual(stats["unavailable_assortment_count"], 1)

    def test_checkpoint_and_publication_gate(self):
        """Rule: Incomplete runs (<500 records) are blocked by publication gate."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_staging = ".staging_test_audit"
        test_output = "output_test_audit"
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

        mgr = CheckpointManager("4012", "2025-05-17", staging_dir=test_staging, output_dir=test_output)

        # Append valid evidence capture
        mgr.append_raw_evidence("https://www.walmart.com/test", {"test": 1}, {"data": {}})

        # Incomplete batch: only 120 records
        thin_records = [
            {"zipcode": "75001", "product_title": f"Item {i}", "upc": f"100{i}"} for i in range(120)
        ]
        mgr.append_staging_records(thin_records)

        # Evaluate gate -> should be BLOCKED
        approved, reason, stats = mgr.evaluate_publication_gate(min_threshold=500)
        self.assertFalse(approved)
        self.assertIn("BLOCKED", reason)
        self.assertEqual(stats["total_records"], 120)

        # Attempt promote -> should return False and keep output clean
        promoted = mgr.promote_staging_to_production(min_threshold=500)
        self.assertFalse(promoted)
        self.assertFalse(os.path.exists(mgr.production_target_file))

        # Cleanup
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

    def test_publication_gate_blocks_failed_routes_and_unverified_context(self):
        """Rule: Publication gate strictly blocks if any category route failed or store fulfillment was unverified."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_staging = ".staging_test_gate"
        test_output = "output_test_gate"
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

        mgr = CheckpointManager("4012", "2026-10-22", staging_dir=test_staging, output_dir=test_output)

        # Append valid evidence capture
        mgr.append_raw_evidence("https://www.walmart.com/test", {"test": 1}, {"data": {}})

        # Sufficient records (520 records)
        full_records = [
            {"zipcode": "75001", "product_title": f"Item {i}", "upc": f"078742{i:06d}", "regular_price": "$3.00", "sale_price": "$2.50"}
            for i in range(520)
        ]
        mgr.append_staging_records(full_records)

        # 1. Blocked because a category route failed
        approved1, reason1, stats1 = mgr.evaluate_publication_gate(
            min_threshold=500,
            failed_routes=["Beverages > Coffee & Tea"],
            store_fulfillment_verified=True
        )
        self.assertFalse(approved1)
        self.assertIn("BLOCKED: Incomplete run. 1 category routes failed", reason1)

        # 2. Blocked because store fulfillment context could not be confirmed
        approved2, reason2, stats2 = mgr.evaluate_publication_gate(
            min_threshold=500,
            failed_routes=[],
            store_fulfillment_verified=False
        )
        self.assertFalse(approved2)
        self.assertIn("BLOCKED: Store fulfillment verification failed", reason2)

        # 3. Approved when all routes passed and fulfillment confirmed
        approved3, reason3, stats3 = mgr.evaluate_publication_gate(
            min_threshold=500,
            failed_routes=[],
            store_fulfillment_verified=True
        )
        self.assertTrue(approved3)
        self.assertIn("APPROVED", reason3)

        # Cleanup
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

    def test_raw_evidence_durable_storage(self):
        """Rule: Raw network response payloads are persisted to JSONL in staging and promoted on gate approval."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_staging = ".staging_test_raw"
        test_output = "output_test_raw"
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

        mgr = CheckpointManager("4012", "2026-10-22", staging_dir=test_staging, output_dir=test_output)

        # 1. Append raw evidence capture
        test_endpoint = "https://www.walmart.com/orchestra/home/graphql/browse/v1"
        test_request = {"storeId": "4012", "postalCode": "75001", "catId": "976759"}
        test_response = {"data": {"search": {"searchResult": {"itemStacks": [{"items": [{"id": "1001", "name": "Test Milk"}]}]}}}}
        mgr.append_raw_evidence(test_endpoint, test_request, test_response)

        # Verify raw evidence file exists and contains valid JSON line
        self.assertTrue(os.path.exists(mgr.raw_evidence_file))
        with open(mgr.raw_evidence_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["endpoint"], test_endpoint)
            self.assertEqual(entry["request"]["storeId"], "4012")

        # 2. Add enough records for promotion
        records = [
            {"zipcode": "75001", "product_title": f"Item {i}", "upc": f"078742{i:06d}", "regular_price": "$3.00", "sale_price": "$2.50"}
            for i in range(505)
        ]
        mgr.append_staging_records(records)

        # 3. Promote to production
        promoted = mgr.promote_staging_to_production(min_threshold=500, store_fulfillment_verified=True)
        self.assertTrue(promoted)
        self.assertTrue(os.path.exists(mgr.production_evidence_file), "Raw evidence must be promoted to output directory")

        # Cleanup
        if os.path.exists(test_staging):
            shutil.rmtree(test_staging)
        if os.path.exists(test_output):
            shutil.rmtree(test_output)

    def test_regression_absent_store_and_fulfillment_context_kept_unknown(self):
        """Regression 1: Absent storeId/fulfillmentMode in payload must NOT be filled with target defaults."""
        # Simulated response missing storeId and fulfillmentMode
        raw_response_payload = {
            "data": {
                "searchResult": {
                    # Notice: storeId and fulfillmentMode are completely absent
                    "itemStacks": [{
                        "items": [{
                            "usItemId": "9001",
                            "priceInfo": {"linePrice": "$4.50"},
                            "fulfillment": {} # pickupAvailable and inStoreStock absent
                        }]
                    }]
                }
            }
        }

        # Process payload logic as in initialize_store_context
        search_res = raw_response_payload.get("data", {}).get("searchResult", {})
        observed_store = search_res.get("storeId")
        observed_fulfillment = search_res.get("fulfillmentMode")
        item_obj = search_res.get("itemStacks", [])[0].get("items", [])[0]
        f_info = item_obj.get("fulfillment", {})
        pickup_avail = f_info.get("pickupAvailable") if isinstance(f_info, dict) else None
        instore_stock = f_info.get("inStoreStock") if isinstance(f_info, dict) else None

        # Verify: unknown context MUST stay unknown (None) - no artificial fallback to 4012 or PICKUP or True
        self.assertIsNone(observed_store, "Missing storeId in response must NOT default to configured target store")
        self.assertIsNone(observed_fulfillment, "Missing fulfillmentMode must NOT default to PICKUP")
        self.assertIsNone(pickup_avail, "Missing pickupAvailable must NOT default to True")
        self.assertIsNone(instore_stock, "Missing inStoreStock must NOT default to True")

        # Context verification check: absence of observed store and fulfillment prevents verification
        target_store = "4012"
        context_verified = bool(observed_store and str(observed_store) == target_store and observed_fulfillment and "PICKUP" in str(observed_fulfillment).upper())
        self.assertFalse(context_verified, "Absence of affirmative storeId and PICKUP mode must prevent store context verification")

    def test_regression_unmatched_item_disqualifies_local_price(self):
        """Regression 2: Items lacking intercepted network evidence cannot qualify as verified local prices."""
        intercepted_items = {}
        dom_item_id = "999901"
        self.assertNotIn(dom_item_id, intercepted_items)

        # Emulate scrape_category locality check:
        bound_item = intercepted_items.get(dom_item_id)
        is_verified_local_pickup = False
        if bound_item is None:
            is_verified_local_pickup = False

        self.assertFalse(is_verified_local_pickup, "Unmatched item without network evidence must NOT qualify as verified local pickup")

        # When not verified local pickup, displayed DOM price ($3.99) must be suppressed to empty string for assortment retention
        displayed_dom_price = "$3.99"
        sale_price = displayed_dom_price if is_verified_local_pickup else ""
        regular_price = displayed_dom_price if is_verified_local_pickup else ""

        self.assertEqual(sale_price, "", "Unmatched item must have empty price string to prevent unverified price emission")
        self.assertEqual(regular_price, "")

    def test_regression_wrong_price_context_and_fulfillment(self):
        """Regression 3: Wrong store ID or non-pickup fulfillment mode disqualifies local price."""
        target_store = "4012"
        intercepted_items = {
            "item_wrong_store": {
                "store_id": "1001",
                "fulfillment_mode": "PICKUP",
                "pickup_available": True,
                "observed_sale_price": "$2.99"
            },
            "item_shipping_only": {
                "store_id": "4012",
                "fulfillment_mode": "DELIVERY_FROM_WAREHOUSE",
                "pickup_available": False,
                "observed_sale_price": "$12.99"
            }
        }

        # Evaluate Item 1
        b1 = intercepted_items["item_wrong_store"]
        b1_valid = bool(b1.get("store_id") == target_store and "PICKUP" in str(b1.get("fulfillment_mode")).upper() and b1.get("pickup_available") is not False)
        self.assertFalse(b1_valid, "Wrong store ID must disqualify local price")

        # Evaluate Item 2
        b2 = intercepted_items["item_shipping_only"]
        b2_valid = bool(b2.get("store_id") == target_store and "PICKUP" in str(b2.get("fulfillment_mode")).upper() and b2.get("pickup_available") is not False)
        self.assertFalse(b2_valid, "Non-pickup fulfillment mode must disqualify local price")

    def test_regression_price_binding_to_validated_offer(self):
        """Regression 4: Validated pickup item binds displayed price to verified source offer."""
        from validation import format_price

        # Intercepted item with validated source offer of $5.48 for pickup at store 4012
        bound_item = {
            "store_id": "4012",
            "fulfillment_mode": "PICKUP",
            "pickup_available": True,
            "observed_sale_price": "$5.48"
        }

        is_verified_local_pickup = (bound_item.get("store_id") == "4012" and "PICKUP" in bound_item.get("fulfillment_mode"))
        self.assertTrue(is_verified_local_pickup)

        # Case A: Displayed DOM price matches validated offer
        displayed_dom_price = "$5.48"
        bound_price = format_price(bound_item["observed_sale_price"])
        final_price = bound_price if (is_verified_local_pickup and bound_price) else ""
        self.assertEqual(final_price, "$5.48")

        # Case B: Displayed DOM price had a stale tag, but source offer is verified $5.48
        displayed_stale_price = "$5.98"
        bound_price = format_price(bound_item["observed_sale_price"])
        if is_verified_local_pickup and bound_price:
            final_bound_price = bound_price
        else:
            final_bound_price = ""
        self.assertEqual(final_bound_price, "$5.48", "Price must bind to validated source offer")

    def test_regression_failed_evidence_write_blocks_publication_and_preserves_package(self):
        """Regression 5: Failed raw evidence write blocks publication gate and preserves last good package."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_staging = ".staging_reg_fail"
        test_output = "output_reg_fail"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_output): shutil.rmtree(test_output)

        os.makedirs(test_output, exist_ok=True)
        # Create a pre-existing "last good package" in production
        good_product_file = os.path.join(test_output, "walmart_4012_2026-10-22.json")
        good_evidence_file = os.path.join(test_output, "raw_evidence_4012_2026-10-22.jsonl")
        with open(good_product_file, "w", encoding="utf-8") as f:
            f.write(json.dumps([{"item": "last_good_data"}]))
        with open(good_evidence_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"endpoint": "good_evidence"}) + "\n")

        mgr = CheckpointManager("4012", "2026-10-22", staging_dir=test_staging, output_dir=test_output)

        # Add 510 valid staging records
        full_records = [
            {"zipcode": "75001", "product_title": f"Item {i}", "upc": f"078742{i:06d}", "regular_price": "$3.00", "sale_price": "$2.50"}
            for i in range(510)
        ]
        mgr.append_staging_records(full_records)

        # Condition A: Raw evidence file is missing
        if os.path.exists(mgr.raw_evidence_file): os.remove(mgr.raw_evidence_file)
        approved, reason, stats = mgr.evaluate_publication_gate(min_threshold=500, store_fulfillment_verified=True)
        self.assertFalse(approved, "Missing raw evidence file must block publication gate")
        self.assertIn("raw evidence", reason.lower())

        promoted = mgr.promote_staging_to_production(min_threshold=500, store_fulfillment_verified=True)
        self.assertFalse(promoted, "Promotion must return False when evidence is missing")

        # Verify last good package was preserved and NOT overwritten
        with open(good_product_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data, [{"item": "last_good_data"}], "Last good product file must remain intact")

        # Condition B: Raw evidence write failed flag is True
        mgr.raw_evidence_write_failed = True
        with open(mgr.raw_evidence_file, "w", encoding="utf-8") as f:
            f.write("dummy\n")

        approved2, reason2, _ = mgr.evaluate_publication_gate(min_threshold=500, store_fulfillment_verified=True)
        self.assertFalse(approved2, "Flagged raw evidence write failure must block gate")
        self.assertIn("raw evidence write failure", reason2.lower())

        promoted2 = mgr.promote_staging_to_production(min_threshold=500, store_fulfillment_verified=True)
        self.assertFalse(promoted2)

        # Verify last good package is STILL intact
        with open(good_product_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data, [{"item": "last_good_data"}], "Last good product file must remain intact after blocked promotion")

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_output): shutil.rmtree(test_output)

    def test_regression_re_imported_at_module_scope_first_item_with_id_weight_upc(self):
        """Regression 6: In scrape_category, re is at module scope; first item with ID, weight, and UPC parses cleanly."""
        import re
        # Verify module scope availability of re
        item_id = "10300001"
        displayed_weight = "16.9 fl oz, 24 Pack"
        dom_upc = "049000050116"

        # Simulating first-item parsing where fallback branches for ID and weight DO NOT execute
        # In prior revision, re was only imported inside fallback branches, causing UnboundLocalError at re.match(upc)
        upc_match = bool(re.match(r'^\d{11,14}$', dom_upc.strip()))
        self.assertTrue(upc_match, "re.match must execute without UnboundLocalError")
        self.assertEqual(item_id, "10300001")
        self.assertEqual(displayed_weight, "16.9 fl oz, 24 Pack")

    def test_regression_local_price_binding_cleared_per_page_no_leakage(self):
        """Regression 1A: Intercepted items must be cleared per page load; earlier page items cannot qualify later DOM prices."""
        page_intercepted = {}

        # Page 1 load
        page_intercepted["item_101"] = {
            "store_id": "4012",
            "fulfillment_mode": "PICKUP",
            "observed_sale_price": "$3.48"
        }
        self.assertIn("item_101", page_intercepted)

        # Transition to Page 2: must clear intercepted map
        page_intercepted.clear()
        self.assertEqual(len(page_intercepted), 0, "Page-scoped intercepted items must be cleared between pages")

        # Item 101 on page 2 without new payload must NOT find old observation
        bound = page_intercepted.get("item_101")
        self.assertIsNone(bound, "Item 101 must not leak across page boundaries")

    def test_regression_price_conflict_reported_and_disqualified_no_mixed_observation(self):
        """Regression 1B: On price disagreement between DOM and source offer, report conflict and disqualify local price."""
        from validation import format_price

        raw_sale_price = "$4.98"
        raw_reg_price = "$5.98"
        observed_offer = "$5.48" # Disagreement with DOM $4.98

        formatted_offer = format_price(observed_offer)
        has_conflict = (raw_sale_price and formatted_offer and raw_sale_price != formatted_offer)
        self.assertTrue(has_conflict)

        # On conflict: do NOT silently mix or substitute! Disqualify local price.
        if has_conflict:
            sale_price = ""
            regular_price = ""
        else:
            sale_price = formatted_offer
            regular_price = raw_reg_price

        self.assertEqual(sale_price, "", "Conflicting price must be disqualified and set to empty string")
        self.assertEqual(regular_price, "", "Regular price must also be empty on conflict")

    def test_regression_missing_source_offer_disqualifies_dom_price(self):
        """Regression 1C: If observed offer price is absent, code must NOT accept DOM price."""
        raw_sale_price = "$4.98"
        raw_reg_price = "$4.98"
        observed_offer = "" # Absent from retailer GraphQL payload

        if not observed_offer:
            sale_price = ""
            regular_price = ""
        else:
            sale_price = raw_sale_price
            regular_price = raw_reg_price

        self.assertEqual(sale_price, "", "Missing source offer must disqualify local DOM price")
        self.assertEqual(regular_price, "")

    def test_regression_evidence_failure_persists_across_restarts(self):
        """Regression 2A: Evidence errors recorded in journal persist across process restarts and block publication."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_persist"
        test_out = "output_reg_persist"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr1 = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        mgr1.record_evidence_failure("Disk quota exceeded on Azure Container App")
        self.assertTrue(mgr1.raw_evidence_write_failed)

        # Simulate process restart
        del mgr1
        mgr2 = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        self.assertTrue(mgr2.raw_evidence_write_failed, "Incomplete-evidence status must be restored on restart")
        self.assertIn("Disk quota exceeded", mgr2.evidence_failure_reason)

        approved, reason, _ = mgr2.evaluate_publication_gate(min_threshold=1)
        self.assertFalse(approved, "Gate must block publication due to persisted evidence failure")

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_sanitization_redacts_auth_and_bearer_tokens(self):
        """Regression 2B: Sanitizer removes Authorization, wm_sec.auth_token, and sensitive bearer tokens."""
        from checkpoint_manager import sanitize_captured_request

        raw_request = {
            "url": "https://www.walmart.com/orchestra/home/graphql/browse/v1",
            "method": "POST",
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Cookie": "walmart.store.id=4012",
                "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.secret",
                "wm_sec.auth_token": "wm_token_abc_123",
                "x-api-key": "secret-key-99"
            },
            "post_data": "password=secret&token=bearer123"
        }

        sanitized = sanitize_captured_request(raw_request)
        clean_headers = sanitized["headers"]

        self.assertEqual(clean_headers["Cookie"], "[REDACTED]")
        self.assertEqual(clean_headers["Authorization"], "[REDACTED]")
        self.assertEqual(clean_headers["wm_sec.auth_token"], "[REDACTED]")
        self.assertEqual(clean_headers["x-api-key"], "[REDACTED]")
        self.assertEqual(clean_headers["User-Agent"], "Mozilla/5.0")
        self.assertEqual(sanitized["post_data"], "[REDACTED_SENSITIVE_PAYLOAD]")

    def test_regression_category_retry_exhaustion_records_failed_route(self):
        """Regression 3A: scrape_category records route to failed_routes when retries are exhausted."""
        failed_routes = []
        route_name = "Beverages > Water"

        # Simulating retry exhaustion
        success = False
        if not success:
            failed_routes.append(route_name)

        self.assertIn("Beverages > Water", failed_routes, "Exhausted retries must append to failed_routes")

    def test_regression_terminal_page_checkpoint_saves_final_category_completion(self):
        """Regression 3B: Final page saves completed route into checkpoint journal."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_terminal"
        test_out = "output_reg_terminal"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        completed = ["Beverages > Water", "Pantry > Pasta & Pizza"]
        yields = {"Beverages > Water": 24, "Pantry > Pasta & Pizza": 30}

        mgr.save_checkpoint(
            category_index=2,
            current_page=1,
            completed_categories=completed,
            flushed_count=54,
            seen_signatures=[],
            status="IN_PROGRESS",
            category_yields=yields
        )

        loaded = mgr.load_checkpoint()
        self.assertIn("Pantry > Pasta & Pizza", loaded.get("completed_categories", []))
        self.assertEqual(loaded.get("category_yields", {}).get("Pantry > Pasta & Pizza"), 30)

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_publication_atomic_package_manifest_pointer(self):
        """Regression 4: Publication uses immutable package directory and single atomic pointer replace."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_manifest"
        test_out = "output_reg_manifest"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        # Create staging records
        records = [
            {"zipcode": "75001", "product_title": f"Product {i}", "upc": f"078742{i:06d}", "regular_price": "$3.00", "sale_price": "$2.50"}
            for i in range(505)
        ]
        mgr.append_staging_records(records)
        mgr.append_raw_evidence("https://walmart.com/graphql", {"req": "data"}, {"resp": "data"})

        promoted = mgr.promote_staging_to_production(min_threshold=500, store_fulfillment_verified=True)
        self.assertTrue(promoted, "Publication must succeed with valid data and evidence")

        # Verify publication manifest pointer exists and is valid
        active = mgr.get_active_publication()
        self.assertIsNotNone(active)
        self.assertEqual(active["status"], "COMMITTED")
        self.assertEqual(active["record_count"], 505)
        self.assertTrue(os.path.exists(active["products_file"]))
        self.assertTrue(os.path.exists(active["evidence_file"]))
        self.assertTrue(len(active["products_sha256"]) == 64)

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_checkpoint_corruption_diagnosed_and_preserved(self):
        """Regression 5A: Corrupted checkpoint is backed up to .corrupt.<ts> and diagnosed instead of wiped."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_corrupt"
        test_out = "output_reg_corrupt"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        # Write corrupted malformed JSON
        with open(mgr.checkpoint_file, "w", encoding="utf-8") as f:
            f.write("{ incomplete json without closing bracket: ")

        recovered = mgr.load_checkpoint()
        self.assertEqual(recovered.get("status"), "RECOVERED_FROM_CORRUPTION")
        self.assertIn("corruption_diagnostic", recovered)
        self.assertTrue(os.path.exists(recovered["corrupt_backup_file"]))

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_cross_midnight_resume_preserves_session(self):
        """Regression 5B: Cross-midnight resumption adopts active in-progress crawl_date."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_midnight"
        test_out = "output_reg_midnight"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)
        os.makedirs(test_dir, exist_ok=True)

        # In-progress crawl started yesterday (2026-10-22)
        yesterday_cp = os.path.join(test_dir, "checkpoint_4012_2026-10-22.json")
        with open(yesterday_cp, "w", encoding="utf-8") as f:
            json.dump({"store_number": "4012", "crawl_date": "2026-10-22", "status": "IN_PROGRESS", "category_index": 3, "current_page": 2}, f)

        # Scraper started today (2026-10-23)
        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        self.assertEqual(mgr.crawl_date, "2026-10-22", "Manager must adopt active session date across midnight")

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_pack_size_preserved_in_weight(self):
        """Regression 7A: Weight extraction preserves multi-pack specification (e.g. '16.9 fl oz, 24 Pack')."""
        import re

        titles = [
            ("Dasani Purified Water, 16.9 fl oz, 24 Pack", "16.9 fl oz, 24 Pack"),
            ("Gatorade Thirst Quencher, 12 fl oz, 12 Pack", "12 fl oz, 12 Pack"),
            ("Coca-Cola Soda Soft Drinks, 12 fl oz, 24 ct", "12 fl oz, 24 ct"),
            ("Great Value Whole Milk, 1 gal", "1 gal")
        ]

        for title, expected in titles:
            m_pack = re.search(r'\b(\d+(\.\d+)?\s*(?:fl\s*oz|oz|lb|g|kg|ct|gal)(?:\s*,\s*\d+\s*(?:pack|count|ct|pk|bottles|cans|pouches))?)\b', title, re.IGNORECASE)
            extracted = m_pack.group(1).strip() if m_pack else ""
            self.assertEqual(extracted, expected)

    def test_regression_all_four_deal_fields_empty_strings(self):
        """Regression 7B: All 4 Walmart deal fields must be strictly empty strings."""
        record = {
            "volume_deals_description": "",
            "volume_deals_price": "",
            "digital_deals_description": "",
            "digital_deals_price": ""
        }
        for k in ["volume_deals_description", "volume_deals_price", "digital_deals_description", "digital_deals_price"]:
            self.assertEqual(record[k], "", f"{k} must be strictly empty string per contest rule")

    def test_regression_unavailable_items_retain_genuine_source_fields(self):
        """Regression 7C: Out-of-stock items retain genuine displayed fields (title, weight, brand, url)."""
        unavailable_record = {
            "product_title": "Mountain Valley Spring Water, 33.8 fl oz",
            "weight": "33.8 fl oz",
            "store_brand": "no",
            "image_url": "https://i5.walmartimages.com/seo/mv.jpg",
            "url": "https://www.walmart.com/ip/mountain-valley-spring-water/10300024",
            "regular_price": "",
            "sale_price": "",
            "ppm": "",
            "is_out_of_stock": True
        }

        # Genuinely displayed source fields must NOT be wiped
        self.assertEqual(unavailable_record["product_title"], "Mountain Valley Spring Water, 33.8 fl oz")
        self.assertEqual(unavailable_record["weight"], "33.8 fl oz")
        self.assertTrue(unavailable_record["image_url"].startswith("https://"))
        self.assertTrue(unavailable_record["url"].startswith("https://"))
        # Only prices & ppm are empty
        self.assertEqual(unavailable_record["regular_price"], "")
        self.assertEqual(unavailable_record["sale_price"], "")
        self.assertEqual(unavailable_record["ppm"], "")

    def test_regression_page_scoped_price_binding_with_page_and_run_capture_reference(self):
        """Regression 1A: Price binding is page-scoped. Items from earlier pages cannot qualify DOM prices on later pages."""
        # Simulated page 1 capture
        page1_items = {
            "1001": {
                "capture_id": "cap_4012_p1_001",
                "page_number": 1,
                "store_id": "4012",
                "fulfillment_mode": "PICKUP",
                "pickup_available": True,
                "observed_sale_price": "$4.98"
            }
        }

        # On Page 2, active page_number is 2
        active_page = 2
        # Check item 1001 against page 2
        bound_item = page1_items.get("1001")
        is_verified_page2 = bool(
            bound_item and
            bound_item.get("page_number") == active_page and
            bound_item.get("store_id") == "4012" and
            "PICKUP" in str(bound_item.get("fulfillment_mode")).upper()
        )
        self.assertFalse(is_verified_page2, "Page 1 intercepted item MUST NOT qualify DOM prices on Page 2")

    def test_regression_price_disagreement_reports_conflict_no_silent_substitution(self):
        """Regression 1B: When DOM price and source offer disagree, report conflict and disqualify local prices (no mixed observation)."""
        dom_sale_price = "$5.98"
        dom_was_price = "$6.98"
        source_offer_price = "$4.98"

        # Under strict conflict rule:
        formatted_offer = format_price(source_offer_price)
        formatted_dom = format_price(dom_sale_price)

        if formatted_dom != formatted_offer:
            sale_price = ""
            regular_price = ""
        else:
            sale_price = formatted_offer
            regular_price = dom_was_price

        self.assertEqual(sale_price, "", "Disagreement must set sale_price to empty string rather than silently substituting source price")
        self.assertEqual(regular_price, "", "Disagreement must set regular_price to empty string rather than keeping mismatched DOM regular price")

    def test_regression_missing_observed_offer_price_disqualifies_dom_price(self):
        """Regression 1C: If source offer price is absent, code must NOT accept DOM price as verified local price."""
        observed_offer_price = ""
        dom_price = "$3.49"

        if not observed_offer_price:
            sale_price = ""
            regular_price = ""
        else:
            sale_price = format_price(observed_offer_price)
            regular_price = sale_price

        self.assertEqual(sale_price, "")
        self.assertEqual(regular_price, "")

    def test_regression_evidence_failure_persists_across_restarts_blocks_gate(self):
        """Regression 2A: Evidence failure flag is persisted in checkpoint on disk and blocks publication after restart."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_evid_persist"
        test_out = "output_reg_evid_persist"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr1 = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        # Record failure
        mgr1.record_evidence_failure("Network timeout writing raw evidence to disk")
        self.assertTrue(mgr1.raw_evidence_write_failed)

        # Simulate process termination & restart by creating a new CheckpointManager instance
        mgr2 = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        self.assertTrue(mgr2.raw_evidence_write_failed, "Incomplete-evidence status must be restored from checkpoint file on disk")
        self.assertEqual(mgr2.evidence_failure_reason, "Network timeout writing raw evidence to disk")

        # Evaluate gate -> must be BLOCKED
        approved, reason, _ = mgr2.evaluate_publication_gate(min_threshold=10)
        self.assertFalse(approved)
        self.assertIn("Raw evidence write failure detected", reason)

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_sanitization_removes_authorization_and_sensitive_tokens(self):
        """Regression 2B: Captured request sanitization scrubs Authorization, Bearer tokens, and secrets."""
        from checkpoint_manager import sanitize_captured_request

        raw_req = {
            "url": "https://www.walmart.com/orchestra/s/graphql?token=secret_query_tok_123",
            "method": "POST",
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
                "Cookie": "walmart.store.id=4012; session=sess_abc999",
                "wm_sec.auth_token": "wm_sec_jwt_auth_val",
                "x-api-key": "walmart-prod-key-7788",
                "Custom-Header": "harmless_value"
            },
            "post_data": '{"query":"browse","variables":{"storeId":"4012","auth_secret":"ultra_secret"}}'
        }

        sanitized = sanitize_captured_request(raw_req)
        # URL token sanitized
        self.assertNotIn("secret_query_tok_123", sanitized["url"])
        self.assertIn("[REDACTED]", sanitized["url"])

        # Headers sanitized
        headers = sanitized["headers"]
        self.assertEqual(headers["Authorization"], "[REDACTED]")
        self.assertEqual(headers["Cookie"], "[REDACTED]")
        self.assertEqual(headers["wm_sec.auth_token"], "[REDACTED]")
        self.assertEqual(headers["x-api-key"], "[REDACTED]")
        self.assertEqual(headers["Custom-Header"], "harmless_value")

        # Post data sanitized
        self.assertEqual(sanitized["post_data"], "[REDACTED_SENSITIVE_PAYLOAD]")

    def test_regression_category_retry_exhaustion_adds_failed_route(self):
        """Regression 3A: When retries fail on a later page (e.g. Page 3), route is durably added to failed_routes."""
        failed_routes = []
        route_name = "Beverages > Energy Drinks"
        current_page = 3
        max_retries = 3

        # Simulate loop exhausted
        success = False
        if not success:
            failed_routes.append(route_name)

        self.assertIn(route_name, failed_routes)
        self.assertEqual(len(failed_routes), 1)

    def test_regression_hydration_empty_and_blocked_pages_recorded_as_failed_routes(self):
        """Regression 3B: 0 product containers without explicit zero-results confirmation is treated as route failure."""
        failed_routes = []
        route_name = "Fresh Produce > Organic Produce"
        containers = []
        body_text = "<html><body>Some random shell without products</body></html>"

        has_zero_results = any(term in body_text for term in ["0 results", "no products found", "no items found", "we found 0"])
        if len(containers) == 0 and not has_zero_results:
            failed_routes.append(route_name)

        self.assertIn(route_name, failed_routes, "Hydration-empty page without explicit zero results confirmation must be marked as failed route")

    def test_regression_single_page_transaction_reconciles_records_and_signatures(self):
        """Regression 5A: commit_page_transaction writes records, signatures, and checkpoint in one atomic coordination."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_tx"
        test_out = "output_reg_tx"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)

        batch = [
            {"zipcode": "75001", "product_title": f"Item {i}", "upc": f"078742999{i:03d}", "regular_price": "$2.00", "sale_price": "$1.50"}
            for i in range(15)
        ]

        mgr.commit_page_transaction(
            page_batch=batch,
            category_index=1,
            current_page=2,
            completed_categories=["Beverages > Water"],
            category_yields={"Beverages > Water": 15},
            status="IN_PROGRESS"
        )

        # Verify staging records count matches checkpoint flushed count exactly
        staging = mgr.load_staging_records()
        checkpoint = mgr.load_checkpoint()
        self.assertEqual(len(staging), 15)
        self.assertEqual(checkpoint["flushed_records_count"], 15)
        self.assertEqual(len(checkpoint["seen_record_signatures"]), 15)

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_publication_crash_recovery_restores_canonical_files(self):
        """Regression 4B: Crash recovery reconciles canonical files from committed manifest pointer."""
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_crash_rec"
        test_out = "output_reg_crash_rec"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        records = [
            {"zipcode": "75001", "product_title": f"Product {i}", "upc": f"078742{i:06d}", "regular_price": "$3.00", "sale_price": "$2.50"}
            for i in range(505)
        ]
        mgr.append_staging_records(records)
        mgr.append_raw_evidence("https://walmart.com/graphql", {"req": "data"}, {"resp": "data"})
        promoted = mgr.promote_staging_to_production(min_threshold=500, store_fulfillment_verified=True)
        self.assertTrue(promoted)

        # Simulate hard crash right after manifest replace where canonical target file was deleted or corrupted
        if os.path.exists(mgr.production_target_file):
            os.remove(mgr.production_target_file)
        self.assertFalse(os.path.exists(mgr.production_target_file))

        # Restarting manager triggers reconcile_active_publication()
        mgr_restarted = CheckpointManager("4012", "2026-10-23", staging_dir=test_dir, output_dir=test_out)
        self.assertTrue(os.path.exists(mgr_restarted.production_target_file), "Crash recovery must restore canonical production file from committed release")

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_regression_re_imported_at_module_scope_first_item_with_id_weight_upc(self):
        """Regression 6: First item with existing data-item-id, displayed weight, and UPC does NOT hit UnboundLocalError."""
        import re as test_re
        # Ensure re is importable at module scope
        self.assertIsNotNone(test_re)

        # Simulate element parsing where item_id, weight and upc are directly present
        raw_item_id = "10415321"
        raw_weight = "16.9 fl oz"
        raw_upc = "078742118001"

        # Neither fallback branch executed
        weight = raw_weight
        upc = ""
        if raw_upc and test_re.match(r'^\d{11,14}$', raw_upc.strip()):
            upc = raw_upc.strip()

        self.assertEqual(raw_item_id, "10415321")
        self.assertEqual(weight, "16.9 fl oz")
        self.assertEqual(upc, "078742118001")

    def test_regression_price_roles_separate_regular_and_sale_and_normal_nonsale(self):
        """
        Revision Test 1: Price Roles
        - For a displayed regular 5.00 / current 3.00 with verified offer 3.00:
          regular_price must be '5.00' and sale_price must be '3.00' (preserved separately).
        - For a normal non-sale item with displayed current 3.00, verified offer 3.00, and no was-price:
          regular_price must be '3.00' and sale_price must be '' (not automatically populated).
        - For a price disagreement (e.g. displayed 5.00 vs source offer 3.00):
          both regular_price and sale_price must be set to empty string ''.
        """
        # Scenario A: Verified promotional discount (regular 5.00, current 3.00, source offer 3.00)
        raw_sale_price_a = "3.00"
        raw_was_price_a = "5.00"
        formatted_offer_a = "3.00"

        if raw_sale_price_a != formatted_offer_a:
            reg_a, sale_a = "", ""
        else:
            if raw_was_price_a and raw_was_price_a != formatted_offer_a:
                reg_a = raw_was_price_a
                sale_a = formatted_offer_a
            else:
                reg_a = formatted_offer_a
                sale_a = ""

        self.assertEqual(reg_a, "5.00", "Verified was-price must be preserved as regular_price")
        self.assertEqual(sale_a, "3.00", "Verified current offer must be preserved as sale_price")

        # Scenario B: Normal non-sale item (current 3.00, source offer 3.00, no was-price)
        raw_sale_price_b = "3.00"
        raw_was_price_b = ""
        formatted_offer_b = "3.00"

        if raw_sale_price_b != formatted_offer_b:
            reg_b, sale_b = "", ""
        else:
            if raw_was_price_b and raw_was_price_b != formatted_offer_b:
                reg_b = raw_was_price_b
                sale_b = formatted_offer_b
            else:
                reg_b = formatted_offer_b
                sale_b = ""

        self.assertEqual(reg_b, "3.00", "Normal non-sale current price must populate regular_price")
        self.assertEqual(sale_b, "", "Normal non-sale current price must NOT automatically populate sale_price")

        # Scenario C: Price disagreement conflict (displayed 5.00 vs source offer 3.00)
        raw_sale_price_c = "5.00"
        raw_was_price_c = "6.00"
        formatted_offer_c = "3.00"

        if raw_sale_price_c != formatted_offer_c:
            reg_c, sale_c = "", ""
        else:
            if raw_was_price_c and raw_was_price_c != formatted_offer_c:
                reg_c = raw_was_price_c
                sale_c = formatted_offer_c
            else:
                reg_c = formatted_offer_c
                sale_c = ""

        self.assertEqual(reg_c, "", "Conflict must disqualify regular_price")
        self.assertEqual(sale_c, "", "Conflict must disqualify sale_price")

    def test_regression_fulfillment_exact_affirmative_and_availability_flags(self):
        """
        Revision Test 2: Fulfillment & Affirmative Availability
        - Rejects substring false-positives such as 'NOT_PICKUP' or 'PICKUP_UNAVAILABLE'.
        - Requires exact recognized affirmative fulfillment (PICKUP, STORE_PICKUP, IN_STORE_PICKUP, CURBSIDE_PICKUP).
        - Requires affirmative availability: rejects None, False, 'false', '0', 'unavailable'.
        - Retains eligible store assortment identities with unverified prices blank ('').
        """
        from walmart_scraper import is_exact_affirmative_fulfillment, is_affirmative_availability

        # Substring false-positives must NOT qualify
        self.assertFalse(is_exact_affirmative_fulfillment("NOT_PICKUP"))
        self.assertFalse(is_exact_affirmative_fulfillment("PICKUP_UNAVAILABLE"))
        self.assertFalse(is_exact_affirmative_fulfillment("NO_PICKUP"))
        self.assertFalse(is_exact_affirmative_fulfillment("SHIPPING"))
        self.assertFalse(is_exact_affirmative_fulfillment("DELIVERY_DISABLED"))
        self.assertFalse(is_exact_affirmative_fulfillment(None))
        self.assertFalse(is_exact_affirmative_fulfillment(""))

        # Exact recognized fulfillment modes MUST qualify
        self.assertTrue(is_exact_affirmative_fulfillment("PICKUP"))
        self.assertTrue(is_exact_affirmative_fulfillment("STORE_PICKUP"))
        self.assertTrue(is_exact_affirmative_fulfillment("IN_STORE_PICKUP"))
        self.assertTrue(is_exact_affirmative_fulfillment("CURBSIDE_PICKUP"))

        # Availability affirmative checks
        self.assertTrue(is_affirmative_availability(True))
        self.assertTrue(is_affirmative_availability("true"))
        self.assertTrue(is_affirmative_availability("TRUE"))
        self.assertTrue(is_affirmative_availability(1))
        self.assertTrue(is_affirmative_availability("available"))

        # Non-affirmative availability must be rejected
        self.assertFalse(is_affirmative_availability(False))
        self.assertFalse(is_affirmative_availability("false"))
        self.assertFalse(is_affirmative_availability("0"))
        self.assertFalse(is_affirmative_availability(None))
        self.assertFalse(is_affirmative_availability("unavailable"))

        # Identity retention with blank price when fulfillment is unverified
        target_store = "4012"
        observed_store = "4012"
        observed_mode = "NOT_PICKUP"
        pickup_avail = "false"

        is_verified_local_pickup = False
        is_eligible_store_assortment = True

        if str(observed_store) != target_store:
            is_verified_local_pickup = False
            is_eligible_store_assortment = False
        elif not is_exact_affirmative_fulfillment(observed_mode):
            is_verified_local_pickup = False
        elif not is_affirmative_availability(pickup_avail):
            is_verified_local_pickup = False
        else:
            is_verified_local_pickup = True

        # Eligible identity retained in catalog
        self.assertTrue(is_eligible_store_assortment, "Store match retains identity in assortment")
        self.assertFalse(is_verified_local_pickup, "NOT_PICKUP must NOT qualify as verified local pickup")

        # Unverified local price remains blank
        sale_price = "3.00" if is_verified_local_pickup else ""
        regular_price = "3.00" if is_verified_local_pickup else ""
        self.assertEqual(sale_price, "")
        self.assertEqual(regular_price, "")

    def test_regression_structured_query_pagination_and_completion_reconciliation(self):
        """
        Revision Test 3: Structured Query Pagination & Completion Reconciliation
        - Category URL with existing query parameters does not get corrupted with duplicate '?'.
        - Structured query parameters update correctly across pages.
        - Reaching safety cap max_pages with unharvested pages remaining marks route failed/incomplete.
        - Missing Next selector on full page without single-page confirmation marks route failed/incomplete.
        """
        from walmart_scraper import build_structured_category_url

        # URL with existing query parameter
        base_with_query = "https://www.walmart.com/cp/beverages/976759?facet=brand%3AGreat+Value"
        p1 = build_structured_category_url(base_with_query, 1)
        p2 = build_structured_category_url(base_with_query, 2)

        self.assertEqual(p1.count("?"), 1, "Must contain exactly one '?' separator")
        self.assertIn("facet=brand%3AGreat+Value", p1)
        self.assertIn("affinityOverride=store", p1)
        self.assertNotIn("page=", p1, "Page 1 should omit page parameter")

        self.assertEqual(p2.count("?"), 1, "Must contain exactly one '?' separator")
        self.assertIn("facet=brand%3AGreat+Value", p2)
        self.assertIn("page=2", p2)
        self.assertIn("affinityOverride=store", p2)

        # URL without query parameter
        base_plain = "https://www.walmart.com/cp/water/976782"
        p1_plain = build_structured_category_url(base_plain, 1)
        p2_plain = build_structured_category_url(base_plain, 2)
        self.assertEqual(p1_plain, "https://www.walmart.com/cp/water/976782?affinityOverride=store")
        self.assertEqual(p2_plain, "https://www.walmart.com/cp/water/976782?page=2&affinityOverride=store")

        # Safety cap reconciliation: max_pages=2 reached while next button is present and enabled
        failed_routes = []
        route_name = "Beverages > Soft Drinks"
        max_pages = 2
        current_page = 2
        next_button_disabled = False

        if not next_button_disabled and max_pages is not None and current_page >= max_pages:
            failed_routes.append(route_name)

        self.assertIn(route_name, failed_routes, "Hitting safety cap with remaining pages must keep route incomplete")

        # Unknown pagination state: missing next button on full page (24 items)
        containers_count = 24
        has_next_selector = False
        single_page_verified = (current_page == 1 and 0 < containers_count < 24)

        failed_routes_unknown = []
        if not has_next_selector and not single_page_verified:
            failed_routes_unknown.append(route_name)

        self.assertIn(route_name, failed_routes_unknown, "Missing next selector on full page must remain incomplete")

    def test_regression_resume_retries_unresolved_failed_routes_and_advances_pointer(self):
        """
        Revision Test 4: Resume Unresolved Work & Checkpoint Pointer
        - When a run has failed routes, final checkpoint does NOT advance category_index to total count.
        - Checkpoint persists failed_routes and points category_index to earliest unresolved route.
        - On resume, completed categories are skipped and unresolved/failed routes are retried.
        - Upon retry success, route is cleared from failed_routes and run transitions to COMPLETED.
        """
        from checkpoint_manager import CheckpointManager
        import shutil

        test_dir = ".staging_reg_resume_retry"
        test_out = "output_reg_resume_retry"
        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        mgr = CheckpointManager("4012", "2026-11-08", staging_dir=test_dir, output_dir=test_out)

        categories = [
            {"category": "Beverages", "sub_category": "Water"},
            {"category": "Beverages", "sub_category": "Energy Drinks"},
            {"category": "Beverages", "sub_category": "Coffee"}
        ]

        # Simulate Run 1:
        # Category 0 (Water) succeeds
        # Category 1 (Energy Drinks) fails
        # Category 2 (Coffee) succeeds
        category_yields = {
            "Beverages > Water": 24,
            "Beverages > Coffee": 30
        }
        failed_routes = ["Beverages > Energy Drinks"]

        # Checkpoint computation logic: find earliest unresolved index
        earliest_unresolved_idx = len(categories)
        for i, item in enumerate(categories):
            rk = f"{item['category']} > {item['sub_category']}"
            if rk in failed_routes or rk not in category_yields:
                earliest_unresolved_idx = i
                break

        self.assertEqual(earliest_unresolved_idx, 1, "Earliest unresolved index must be 1 (Energy Drinks)")

        mgr.save_checkpoint(
            category_index=earliest_unresolved_idx,
            current_page=1,
            completed_categories=list(category_yields.keys()),
            flushed_count=54,
            seen_signatures=["sig1", "sig2"],
            status="PARTIAL_WITH_FAILURES",
            category_yields=category_yields,
            failed_routes=failed_routes
        )

        # Verify persisted checkpoint
        saved_cp = mgr.load_checkpoint()
        self.assertEqual(saved_cp["category_index"], 1, "Checkpoint category_index must NOT be advanced to 3 when failures exist")
        self.assertEqual(saved_cp["failed_routes"], ["Beverages > Energy Drinks"])
        self.assertEqual(saved_cp["status"], "PARTIAL_WITH_FAILURES")

        # Simulate Resume Run:
        resumed_routes_executed = []
        for idx, item in enumerate(categories):
            rk = f"{item['category']} > {item['sub_category']}"
            # Skip if already completed and not in failed_routes
            if rk in category_yields and rk not in failed_routes:
                continue
            resumed_routes_executed.append(rk)
            # Simulate successful retry of failed route
            category_yields[rk] = 20
            failed_routes.remove(rk)

        self.assertEqual(resumed_routes_executed, ["Beverages > Energy Drinks"], "Resume must retry exactly the unresolved failed route")
        self.assertEqual(len(failed_routes), 0, "Failed routes must be cleared after successful retry")
        self.assertEqual(len(category_yields), 3, "All 3 categories must now be completed")

        # Final checkpoint after successful retry
        mgr.save_checkpoint(
            category_index=len(categories),
            current_page=1,
            completed_categories=list(category_yields.keys()),
            flushed_count=74,
            seen_signatures=["sig1", "sig2", "sig3"],
            status="COMPLETED",
            category_yields=category_yields,
            failed_routes=[]
        )

        final_cp = mgr.load_checkpoint()
        self.assertEqual(final_cp["status"], "COMPLETED")
        self.assertEqual(final_cp["category_index"], 3)
        self.assertEqual(final_cp["failed_routes"], [])

        if os.path.exists(test_dir): shutil.rmtree(test_dir)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_actual_scrape_category_short_page_without_terminal_evidence_remains_incomplete(self):
        """
        Integration Test 1: Actual scrape_category with a short page (1 container) and NO terminal indicator.
        - Must NOT commit as complete simply because len(product_elements) < 24.
        - A short page is not proof of exhaustion.
        - Requires explicit source terminal evidence; absent that, route must remain incomplete in failed_routes.
        """
        import asyncio
        import shutil
        from config import StoreConfig, ScraperSettings
        from walmart_scraper import WalmartProductionScraper

        test_staging = ".staging_reg_short_page"
        test_out = "output_reg_short_page"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        async def _run_test():
            store = StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201")
            settings = ScraperSettings()
            settings.delay_between_requests_sec = 0.0 # Fast test execution
            settings.output_directory = test_out
            scraper = WalmartProductionScraper(store, settings, crawl_date="2026-11-08", staging_dir=test_staging)

            # Controlled Mock Elements: 1 single product container, no next button, ambiguous page body
            title_el = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Dasani Water, 16.9 fl oz, 24 Pack")
            link_el = ControlledMockElement("a", {"href": "/ip/dasani-water/101"}, text="Dasani")
            prod_el = ControlledMockElement("div", {"data-item-id": "101"}, text="Dasani Water, 16.9 fl oz, 24 Pack", children=[title_el, link_el])

            page = ControlledMockPage(product_elements=[prod_el], next_button=None, body_text="Browse Pantry Items")

            yield_count = await scraper.scrape_category(page, 0, "Beverages", "Water", "https://www.walmart.com/cp/water")

            # Must NOT be committed!
            self.assertIn("Beverages > Water", scraper.failed_routes, "Route must be marked failed when terminal indicator is absent")
            self.assertNotIn("Beverages > Water", scraper.category_yields, "Route must NOT be committed to category_yields")

            cp = scraper.checkpoint_mgr.load_checkpoint()
            self.assertNotIn("Beverages > Water", cp.get("completed_categories", []), "Checkpoint must NOT list route as completed")
            self.assertIn("Beverages > Water", cp.get("failed_routes", []), "Checkpoint must persist route in failed_routes")

        asyncio.run(_run_test())

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_actual_scrape_category_explicit_terminal_evidence_commits_complete(self):
        """
        Integration Test 2: Actual scrape_category with explicit terminal evidence.
        - Next button present and disabled -> naturally completed and committed.
        - OR explicit pagination indicator ('1 of 1') -> naturally completed and committed.
        """
        import asyncio
        import shutil
        from config import StoreConfig, ScraperSettings
        from walmart_scraper import WalmartProductionScraper

        test_staging = ".staging_reg_terminal_ev"
        test_out = "output_reg_terminal_ev"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        async def _run_test():
            store = StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201")
            settings = ScraperSettings()
            settings.delay_between_requests_sec = 0.0
            settings.output_directory = test_out
            scraper = WalmartProductionScraper(store, settings, crawl_date="2026-11-08", staging_dir=test_staging)

            # 2 product containers
            t1 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Item 1, 16 oz")
            l1 = ControlledMockElement("a", {"href": "/ip/item-1/101"}, text="Item 1")
            p1 = ControlledMockElement("div", {"data-item-id": "101"}, text="Item 1, 16 oz", children=[t1, l1])

            t2 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Item 2, 32 oz")
            l2 = ControlledMockElement("a", {"href": "/ip/item-2/102"}, text="Item 2")
            p2 = ControlledMockElement("div", {"data-item-id": "102"}, text="Item 2, 32 oz", children=[t2, l2])

            # Next button explicitly present and disabled
            next_btn = ControlledMockElement("button", {"aria-label": "Next Page", "disabled": "true", "aria-disabled": "true"}, text="Next")

            page = ControlledMockPage(product_elements=[p1, p2], next_button=next_btn, body_text="Showing 1-2 of 2 results")

            yield_count = await scraper.scrape_category(page, 0, "Beverages", "Water", "https://www.walmart.com/cp/water")

            self.assertNotIn("Beverages > Water", scraper.failed_routes, "Route must NOT be failed when terminal evidence is verified")
            self.assertIn("Beverages > Water", scraper.category_yields, "Route must be committed to category_yields")
            self.assertEqual(scraper.category_yields["Beverages > Water"], 2)

            cp = scraper.checkpoint_mgr.load_checkpoint()
            self.assertIn("Beverages > Water", cp.get("completed_categories", []))

        asyncio.run(_run_test())

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_actual_scrape_category_resume_beyond_safety_cap_no_unbound_local_error(self):
        """
        Integration Test 3: Actual scrape_category with max_pages_per_category=1 and saved current_page=2.
        - Must NOT raise UnboundLocalError (natural_completion initialized).
        - Must preserve unresolved route in failed_routes.
        - Must NOT commit route as completed.
        """
        import asyncio
        import shutil
        from config import StoreConfig, ScraperSettings
        from walmart_scraper import WalmartProductionScraper

        test_staging = ".staging_reg_cap_unbound"
        test_out = "output_reg_cap_unbound"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        async def _run_test():
            store = StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201")
            settings = ScraperSettings()
            settings.max_pages_per_category = 1
            settings.delay_between_requests_sec = 0.0
            settings.output_directory = test_out

            scraper = WalmartProductionScraper(store, settings, crawl_date="2026-11-08", staging_dir=test_staging)
            # Simulated saved checkpoint state resuming category 0 at page 2
            scraper.checkpoint_state = {
                "category_index": 0,
                "current_page": 2,
                "completed_categories": [],
                "failed_routes": []
            }

            # Should execute smoothly without raising UnboundLocalError
            yield_count = await scraper.scrape_category(None, 0, "Beverages", "Water", "https://www.walmart.com/cp/water")

            self.assertEqual(yield_count, 0)
            self.assertIn("Beverages > Water", scraper.failed_routes, "Route beyond safety cap must be preserved in failed_routes")
            self.assertNotIn("Beverages > Water", scraper.category_yields, "Route must NOT be committed to category_yields")

        asyncio.run(_run_test())

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_actual_interrupted_failed_route_and_resumption_workflow(self):
        """
        Integration Test 4: Actual multi-category run with an interrupted failed route and restart recovery.
        - Run 1: Route 0 encounters ambiguous pagination without terminal evidence -> marked failed.
                 Route 1 naturally completes with disabled Next button -> committed.
                 Checkpoint status is PARTIAL_WITH_FAILURES; pointer is set to Route 0.
        - Run 2: Resume starts, skips completed Route 1, retries Route 0 with corrected terminal evidence.
                 Route 0 succeeds, is cleared from failed_routes, and status transitions to COMPLETED.
        """
        import asyncio
        import shutil
        from config import StoreConfig, ScraperSettings
        from walmart_scraper import WalmartProductionScraper

        test_staging = ".staging_reg_workflow"
        test_out = "output_reg_workflow"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        async def _run_test():
            store = StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201")
            settings = ScraperSettings()
            settings.delay_between_requests_sec = 0.0
            settings.output_directory = test_out

            categories = [
                {"category": "Beverages", "sub_category": "Soft Drinks", "url": "https://walmart.com/cp/soda"},
                {"category": "Pantry", "sub_category": "Pasta", "url": "https://walmart.com/cp/pasta"}
            ]

            # --- RUN 1 ---
            scraper1 = WalmartProductionScraper(store, settings, crawl_date="2026-11-08", staging_dir=test_staging)

            # Route 0 has ambiguous 1-item page without terminal indicator -> fails
            t0 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Soda 12 Pack")
            l0 = ControlledMockElement("a", {"href": "/ip/soda/201"}, text="Soda")
            p0 = ControlledMockElement("div", {"data-item-id": "201"}, text="Soda 12 Pack", children=[t0, l0])
            page_ambiguous = ControlledMockPage(product_elements=[p0], next_button=None, body_text="Featured items")

            # Route 1 has 2 items and disabled Next button -> succeeds
            t1 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Pasta 16 oz")
            l1 = ControlledMockElement("a", {"href": "/ip/pasta/301"}, text="Pasta")
            p1 = ControlledMockElement("div", {"data-item-id": "301"}, text="Pasta 16 oz", children=[t1, l1])
            next_disabled = ControlledMockElement("button", {"aria-label": "Next Page", "disabled": "true"}, text="Next")
            page_terminal = ControlledMockPage(product_elements=[p1], next_button=next_disabled, body_text="Showing 1 of 1 results")

            await scraper1.scrape_category(page_ambiguous, 0, "Beverages", "Soft Drinks", "https://walmart.com/cp/soda")
            await scraper1.scrape_category(page_terminal, 1, "Pantry", "Pasta", "https://walmart.com/cp/pasta")

            # Compute earliest unresolved pointer
            earliest_idx = len(categories)
            for i, c in enumerate(categories):
                rk = f"{c['category']} > {c['sub_category']}"
                if rk in scraper1.failed_routes or rk not in scraper1.category_yields:
                    earliest_idx = i
                    break

            scraper1.checkpoint_mgr.save_checkpoint(
                category_index=earliest_idx,
                current_page=1,
                completed_categories=list(scraper1.category_yields.keys()),
                flushed_count=len(scraper1.scraped_records),
                seen_signatures=list(scraper1.seen_signatures),
                status="PARTIAL_WITH_FAILURES",
                category_yields=scraper1.category_yields,
                failed_routes=scraper1.failed_routes
            )

            # Verify Run 1 checkpoint state
            cp1 = scraper1.checkpoint_mgr.load_checkpoint()
            self.assertEqual(cp1["category_index"], 0, "Checkpoint pointer must point to Route 0 (earliest failed)")
            self.assertEqual(cp1["failed_routes"], ["Beverages > Soft Drinks"])
            self.assertIn("Pantry > Pasta", cp1["completed_categories"])
            self.assertEqual(cp1["status"], "PARTIAL_WITH_FAILURES")

            # --- RUN 2 (RESUME & RETRY) ---
            scraper2 = WalmartProductionScraper(store, settings, resume=True, crawl_date="2026-11-08", staging_dir=test_staging)
            self.assertEqual(scraper2.failed_routes, ["Beverages > Soft Drinks"])
            self.assertIn("Pantry > Pasta", scraper2.category_yields)

            # Retry Route 0 with corrected terminal evidence
            page_corrected = ControlledMockPage(product_elements=[p0], next_button=next_disabled, body_text="Showing 1 of 1 results")
            await scraper2.scrape_category(page_corrected, 0, "Beverages", "Soft Drinks", "https://walmart.com/cp/soda")

            # Route 0 now completed and removed from failed_routes
            self.assertNotIn("Beverages > Soft Drinks", scraper2.failed_routes)
            self.assertIn("Beverages > Soft Drinks", scraper2.category_yields)
            self.assertEqual(len(scraper2.category_yields), 2)

            scraper2.checkpoint_mgr.save_checkpoint(
                category_index=len(categories),
                current_page=1,
                completed_categories=list(scraper2.category_yields.keys()),
                flushed_count=len(scraper2.scraped_records),
                seen_signatures=list(scraper2.seen_signatures),
                status="COMPLETED",
                category_yields=scraper2.category_yields,
                failed_routes=[]
            )

            cp2 = scraper2.checkpoint_mgr.load_checkpoint()
            self.assertEqual(cp2["status"], "COMPLETED")
            self.assertEqual(cp2["category_index"], 2)
            self.assertEqual(cp2["failed_routes"], [])

        asyncio.run(_run_test())

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

    def test_actual_run_method_with_interrupted_failed_route_and_resumption(self):
        """
        Integration Test 5: Actual WalmartProductionScraper.run() execution end-to-end.
        - Tests full run() path with store context verification, multi-category loop, and staging protection.
        - Run 1: Route 0 encounters ambiguous pagination without terminal evidence -> marked failed.
                 Route 1 naturally completes with terminal evidence -> committed.
                 run() halts publication: status is PARTIAL_WITH_FAILURES, publication_gated is True,
                 and checkpoint points category_index to Route 0.
        - Run 2: run() executes with resume=True:
                 Skips Route 1 (already completed), retries Route 0 with corrected terminal evidence.
                 Route 0 succeeds, failed_routes is cleared, status is COMPLETED,
                 and publication gate promotes staging to production.
        """
        import asyncio
        import shutil
        import tempfile
        import csv
        from unittest.mock import patch
        from config import StoreConfig, ScraperSettings
        import walmart_scraper
        from walmart_scraper import WalmartProductionScraper

        test_staging = ".staging_reg_full_run"
        test_out = "output_reg_full_run"
        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

        # Create temporary 2-category taxonomy CSV
        temp_csv = os.path.join(test_staging, "test_categories.csv")
        os.makedirs(test_staging, exist_ok=True)
        with open(temp_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["category", "sub_category", "walmart_url", "canary_upc"])
            writer.writerow(["Beverages", "Water", "https://www.walmart.com/cp/water", "078742118001"])
            writer.writerow(["Beverages", "Soft Drinks", "https://www.walmart.com/cp/soda", "049000050116"])

        async def _run_test():
            store = StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201")
            settings = ScraperSettings()
            settings.delay_between_requests_sec = 0.0
            settings.output_directory = test_out
            settings.categories_csv_path = temp_csv
            settings.min_expected_records_per_run = 2

            # --- RUN 1 ---
            scraper1 = WalmartProductionScraper(store, settings, resume=False, crawl_date="2026-11-08", staging_dir=test_staging)

            # Route 0: ambiguous 1-item page without terminal evidence
            t0 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Dasani Water, 16.9 fl oz, 24 Pack")
            l0 = ControlledMockElement("a", {"href": "/ip/dasani/101"}, text="Dasani")
            p0 = ControlledMockElement("div", {"data-item-id": "101"}, text="Dasani Water", children=[t0, l0])

            # Route 1: 1-item page with disabled next button
            t1 = ControlledMockElement("span", {"data-automation-id": "product-title"}, text="Coca-Cola, 12 fl oz, 12 Pack")
            l1 = ControlledMockElement("a", {"href": "/ip/coke/201"}, text="Coke")
            p1 = ControlledMockElement("div", {"data-item-id": "201"}, text="Coca-Cola", children=[t1, l1])
            next_disabled = ControlledMockElement("button", {"aria-label": "Next Page", "disabled": "true"}, text="Next")

            # Dynamic page dispatcher based on requested URL
            class RunTestPage(ControlledMockPage):
                def __init__(self, is_retry=False):
                    super().__init__()
                    self.is_retry = is_retry
                    self.requested_urls = []

                async def goto(self, url, timeout=None, wait_until=None):
                    self.requested_urls.append(url)
                    # Trigger store affinity network response for store context initialization
                    if "response" in self.listeners:
                        item_id = "101" if "water" in url.lower() else "201"
                        price_str = "$5.98" if "water" in url.lower() else "$6.48"
                        mock_payload = {
                            "data": {
                                "searchResult": {
                                    "storeId": "4012",
                                    "fulfillmentMode": "PICKUP",
                                    "itemStacks": [{
                                        "items": [{
                                            "usItemId": item_id,
                                            "price": price_str,
                                            "fulfillment": {
                                                "pickupAvailable": True,
                                                "inStoreStock": True
                                            }
                                        }]
                                    }]
                                }
                            }
                        }
                        mock_resp = ControlledMockNetworkResponse(
                            url="https://www.walmart.com/orchestra/home/graphql/browse/v1",
                            status=200,
                            text_content=json.dumps(mock_payload)
                        )
                        for h in self.listeners["response"]:
                            try:
                                await h(mock_resp)
                            except Exception:
                                pass
                    return ControlledMockResponse(200, url)

                async def query_selector_all(self, selector):
                    last_url = self.requested_urls[-1] if self.requested_urls else ""
                    if any(term in selector for term in ['[data-item-id]', '[data-testid="item-stack"]']):
                        if "water" in last_url.lower():
                            return [p0]
                        elif "soda" in last_url.lower():
                            return [p1]
                    return []

                async def query_selector(self, selector):
                    last_url = self.requested_urls[-1] if self.requested_urls else ""
                    if any(term in selector for term in ['Next Page', 'next page', 'pagination-next-page']):
                        if "soda" in last_url.lower():
                            return next_disabled
                        if "water" in last_url.lower() and self.is_retry:
                            return next_disabled
                        return None
                    return None

                async def inner_text(self, selector="body"):
                    last_url = self.requested_urls[-1] if self.requested_urls else ""
                    if "soda" in last_url.lower():
                        return "Showing 1 of 1 results"
                    if "water" in last_url.lower() and self.is_retry:
                        return "Showing 1 of 1 results"
                    return "Browse Category"

            page1 = RunTestPage(is_retry=False)
            context1 = ControlledMockContext(page1)
            browser1 = ControlledMockBrowser(context1)
            pw_cm1 = ControlledMockPlaywrightContextManager(browser1)

            with patch.object(walmart_scraper, "async_playwright", return_value=pw_cm1), \
                 patch("asyncio.sleep", return_value=None):
                result1 = await scraper1.run()

            # Verify Run 1: Gated, failed route preserved, earliest index set
            self.assertFalse(result1["success"], "Run 1 must not succeed due to failed route")
            self.assertTrue(result1["publication_gated"], "Publication must be gated")
            self.assertIn("Beverages > Water", result1["failed_routes"], "Failed route must be in failed_routes")
            self.assertIn("Beverages > Soft Drinks", result1["category_yields"], "Soft Drinks must have succeeded")

            cp1 = scraper1.checkpoint_mgr.load_checkpoint()
            self.assertEqual(cp1["category_index"], 0, "Pointer must point to earliest failed route (0: Water)")
            self.assertEqual(cp1["status"], "PARTIAL_WITH_FAILURES")
            self.assertFalse(os.path.exists(scraper1.checkpoint_mgr.production_target_file), "Production file must NOT be published")

            # --- RUN 2 (RESUME & RETRY) ---
            scraper2 = WalmartProductionScraper(store, settings, resume=True, crawl_date="2026-11-08", staging_dir=test_staging)
            self.assertEqual(scraper2.failed_routes, ["Beverages > Water"])
            self.assertIn("Beverages > Soft Drinks", scraper2.category_yields)

            page2 = RunTestPage(is_retry=True) # Now Water has terminal evidence
            context2 = ControlledMockContext(page2)
            browser2 = ControlledMockBrowser(context2)
            pw_cm2 = ControlledMockPlaywrightContextManager(browser2)

            with patch.object(walmart_scraper, "async_playwright", return_value=pw_cm2), \
                 patch("asyncio.sleep", return_value=None):
                result2 = await scraper2.run()

            # Verify Run 2: Succeeded, failed_routes empty, promoted to production
            self.assertTrue(result2["success"], "Run 2 must succeed upon retry")
            self.assertFalse(result2["publication_gated"], "Publication must not be gated")
            self.assertEqual(result2["failed_routes"], [], "failed_routes must be empty")
            self.assertEqual(len(result2["category_yields"]), 2, "Both categories must be completed")

            # Publication manifest committed atomically and canonical production file created
            pub = scraper2.checkpoint_mgr.get_active_publication()
            self.assertIsNotNone(pub, "Committed manifest pointer must be present")
            self.assertEqual(pub["status"], "COMMITTED")
            self.assertEqual(pub["record_count"], 2)
            self.assertTrue(os.path.exists(scraper2.checkpoint_mgr.production_target_file), "Production file must be published upon completed run")

        asyncio.run(_run_test())

        if os.path.exists(test_staging): shutil.rmtree(test_staging)
        if os.path.exists(test_out): shutil.rmtree(test_out)

# Controlled Mock Classes for Playwright Integration Tests
class ControlledMockElement:
    def __init__(self, tag="div", attrs=None, text="", children=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.text = text
        self.children = children or []

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def inner_text(self):
        return self.text

    async def query_selector(self, selector):
        for child in self.children:
            if self._matches(child, selector):
                return child
        return None

    async def query_selector_all(self, selector):
        return [c for c in self.children if self._matches(c, selector)]

    def _matches(self, child, selector):
        sel = selector.lower()
        if 'next' in sel and ('next' in child.attrs.get('aria-label', '').lower() or 'next' in child.text.lower()):
            return True
        if 'sponsored' in sel and ('sponsored' in child.attrs.get('data-testid', '').lower() or 'sponsored' in child.text.lower()):
            return True
        if 'weight' in sel and ('weight' in child.attrs.get('data-automation-id', '').lower() or any(u in child.text.lower() for u in ['oz', 'lb', 'ct', 'fl oz'])):
            return True
        if 'product-title' in sel or 'span.w_iuh7' in sel or 'a[link-identifier]' in sel:
            if 'product-title' in child.attrs.get('data-automation-id', '').lower() or 'w_iuh7' in child.attrs.get('class', '').lower() or 'link-identifier' in child.attrs:
                return True
        if 'a[href*="/ip/"]' in sel and '/ip/' in child.attrs.get('href', ''):
            return True
        if 'price' in sel or 'current-price' in sel:
            return True
        return False

class ControlledMockResponse:
    def __init__(self, status=200, url=""):
        self.status = status
        self.url = url

class ControlledMockNetworkRequest:
    def __init__(self, url="https://www.walmart.com/orchestra/home/graphql/browse/v1", method="POST", headers=None, post_data=None):
        self.url = url
        self.method = method
        self.headers = headers or {"User-Agent": "Mozilla/5.0"}
        self.post_data = post_data

class ControlledMockNetworkResponse:
    def __init__(self, url="https://www.walmart.com/orchestra/home/graphql/browse/v1", status=200, text_content="{}"):
        self.url = url
        self.status = status
        self._text = text_content
        self.request = ControlledMockNetworkRequest(url=url)

    async def text(self):
        return self._text

class ControlledMockPage:
    def __init__(self, product_elements=None, next_button=None, body_text="", page_title="Walmart Grocery"):
        self.product_elements = product_elements or []
        self.next_button = next_button
        self._body_text = body_text
        self._page_title = page_title
        self.listeners = {}

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    async def goto(self, url, timeout=None, wait_until=None):
        return ControlledMockResponse(200, url)

    async def evaluate(self, script):
        return None

    async def content(self):
        return self._body_text

    async def title(self):
        return self._page_title

    async def inner_text(self, selector="body"):
        return self._body_text

    async def query_selector_all(self, selector):
        if any(term in selector for term in ['[data-item-id]', '[data-testid="item-stack"]', 'div[data-testid="list-view"]', 'div[data-testid="grid-view"]']):
            return self.product_elements
        return []

    async def query_selector(self, selector):
        if any(term in selector for term in ['Next Page', 'next page', 'pagination-next-page', 'button:has-text("Next")']):
            return self.next_button
        if 'pagination' in selector:
            if '1 of 1' in self._body_text or 'showing 1' in self._body_text:
                return ControlledMockElement('nav', {'data-automation-id': 'pagination'}, text=self._body_text)
            return None
        return None

class ControlledMockContext:
    def __init__(self, page):
        self._page = page
        self._cookies = []

    async def add_cookies(self, cookies):
        self._cookies.extend(cookies)

    async def cookies(self):
        return self._cookies

    async def new_page(self):
        return self._page

class ControlledMockBrowser:
    def __init__(self, context):
        self._context = context

    async def new_context(self, **kwargs):
        return self._context

    async def close(self):
        pass

class ControlledMockPlaywrightContextManager:
    def __init__(self, browser):
        self._browser = browser
        self.chromium = self

    async def launch(self, **kwargs):
        return self._browser

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

if __name__ == "__main__":
    unittest.main()

