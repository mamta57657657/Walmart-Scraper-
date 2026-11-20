# Offline Regression Report — Reviewer Findings on Commit `216f192`

- **Target Revision Scope**: Corrective fixes for Issues 1–6 raised against commit `216f192` and the two nested pickup-offer binding findings reproduced on commit `7893e58`, preserving all prior pagination regressions (`exact_terminal_page`, `safety_cap_resume`, `run_integration`, and `unpriced_assortment_retention`).
- **Automated Test Suites Executed**:
  - **Python Suite (`python3 -m unittest scraper/test_scraper.py -v`)**: **65 / 65 passed** (`OK`, including dedicated regression tests `test_issue1_...` through `test_issue6_...`)
  - **TypeScript Suite (`npx --yes tsx --test src/utils/*.test.ts`)**: **18 / 18 passed** (`0 failed`, including cross-artifact identity linkage verification in `src/utils/gateEvaluator.test.ts`)
- **Acceptance Gate Status (`public/data/live_gate_status.json`)**:
  - `pagination` (**Pagination corrections**): **PASSED** (`Offline regression suite passing`)
  - `coverage` (**Full catalog coverage**): **PENDING** (awaiting real proxied 21-category execution)
  - `pickup_pricing` (**Live Walmart Pickup pricing**): **PENDING** (awaiting live Walmart Store PICKUP SSR/GraphQL capture)
  - `recovery` (**Interruption and recovery**): **PENDING** (awaiting live interruption/resume trace + committed manifest)
  - `azure` (**Azure operation**): **PENDING** (awaiting actual Azure Container App / Blob publication execution)
  - `hasVerifiedLiveUpdates`: `false`

---

## Summary of Fixes & Offline Regressions (Cases 1–6)

### Case 1: Strict Item/Variant/Offer/Seller/Pickup/Store Price Binding, Store Conflict Rejection, Source UPC Extraction, and Cents Conversion
- **Defect Addressed**:
  1. A pickup page for the target store could export `$99` leaked from a nested wrong-store shipping offer (`storeId != target`, `fulfillmentMode == SHIPPING`) or accept 3P marketplace offers; `"98¢"` was parsed as `"$98.00"`; source `upc`/`gtin*` from network JSON was not propagated consistently.
  2. **(Commit `7893e58` Follow-up)**: A bare nested offer with no item ID, offer ID, variant, seller, or store of its own was accepted at `$9.99` using the page store (`3891`), and an offer declaring conflicting store IDs (`storeId: "3891"` alongside `pickupStoreId: "9999"`) was accepted due to `or` short-circuiting.
- **Fixes Implemented**:
  - `scraper/walmart_scraper.py`:
    - Added `collect_distinct_store_ids()`, `extract_distinct_variant_ids()`, `extract_all_item_variant_ids()`, `has_affirmative_walmart_first_party_seller()`, `extract_source_upc()`, `_extract_offer_price_string()`, and hardened `select_bound_pickup_offer()`.
    - Nested priced offers now **fail closed** unless they provide a complete, unambiguous traceable link to: (a) matching `usItemId`/`itemId`, (b) non-empty `offerId` (matching DOM `data-offer-id` / `selectedOfferId` when present), (c) unambiguous `variantId` (matching item `variantId`/`variants` / DOM `data-variant-id` when present), (d) affirmative first-party Walmart seller (`has_affirmative_walmart_first_party_seller`), (e) affirmative `PICKUP` fulfillment mode without conflicting non-pickup modes + affirmative `pickupAvailable`, and (f) exact, non-conflicting store ID ON the offer itself matching `target_store_id` (zero page-store inheritance).
    - Conflicting store identifiers across offer or item fields (e.g., `storeId: "3891"` + `pickupStoreId: "9999"`) are detected and rejected via `collect_distinct_store_ids()`, retaining the product on the page with blank local money (`regular_price == ""`, `sale_price == ""`).
    - Top-level `priceInfo` fallback is rejected whenever nested offer containers exist without a traceable target-store 1P pickup match.
  - `scraper/validation.py`: Updated `format_price()` to convert cent-denominated strings cleanly (`"98¢"` -> `"$0.98"`, `"5¢"` -> `"$0.05"`).
- **Offline Regression Verification**:
  - `test_issue1_nested_shipping_offer_99_rejected_and_offer_seller_store_upc_cents_bound` (**PASSED**):
    - Verifies item `201` (top-level `$99.00` + nested store `9999` `SHIPPING` offer) exports `regular_price == ""` and preserves source `"upc": "078742000201"`.
    - Verifies item `202` (leaked `$99.00` shipping offer alongside valid traceable Store `#4012` 1P `PICKUP` offer at `"98¢"`) exports `regular_price == "$0.98"` and `"upc": "078742000202"`.
    - Verifies 3P seller item `203` is excluded.
  - `test_issue1_nested_offer_traceability_store_conflict_and_exported_row_control` (**PASSED**, Store `#3891` end-to-end through exported JSON row):
    - Verifies bare nested offers (`301` without offer/item/variant/seller/store fields and `304` with only `PICKUP` + `pickupAvailable` and no item/offer/variant/seller/store) are retained in `walmart_3891_2026-11-19.json` with `regular_price == ""` and `sale_price == ""`.
    - Verifies conflicting-store nested offer (`302`, `storeId: "3891"` + `pickupStoreId: "9999"`, `$9.99`) is rejected and retained in `walmart_3891_2026-11-19.json` with `regular_price == ""` and `sale_price == ""`.
    - Verifies matching positive control (`303`, full traceable `usItemId`/`offerId`/`variantId`/1P Walmart seller/`PICKUP`/consistent `storeId: "3891"` & `pickupStoreId: "3891"`) exports `regular_price == "$9.99"`, `sale_price == ""`, valid 22-field schema.

### Case 2: Fail-Closed Store Lookup, Empty `"10 results"` Detection, Repeated-Page Stall Rejection, and Per-Route Terminal Verification
- **Defect Addressed**: Unknown or empty store targets silently fell back to Store `#4012`; a page displaying `"10 results"` could complete with 0 extracted items; three repeated pages yielding only 1 unique item could complete instead of failing; publication did not verify terminal pages per required category and child route for the configured store.
- **Fixes Implemented**:
  - `scraper/config.py`: `get_store_by_target()` now raises `ValueError` on empty or unknown targets instead of falling back to `"TX"` / `#4012`. `walmart_scraper.py` exits non-zero when an unknown `--store` target is supplied.
  - `scraper/walmart_scraper.py`: Added `parse_header_results_count()`, `read_page_header_results_count()`, per-page item fingerprint stall detection (repeated non-empty page fingerprint or 2 consecutive pages adding 0 new items), and `valid_items_count` enforcement inside `check_explicit_terminal_evidence()`.
  - `scraper/checkpoint_manager.py`: `evaluate_publication_gate()` verifies `terminal_verified_routes` for every required category and child route (`terminal_verified == True` and matching `store_number` when recorded), as well as confirmed store lock.
- **Offline Regression Verification**:
  - `test_issue2_unknown_store_empty_ten_results_repeated_pages_and_child_terminal` (**PASSED**):
    - Asserts `ValueError` for `"UNKNOWN_99999"` and `""`.
    - Verifies `"10 results"` page with 0 valid non-sponsored items routes into `failed_routes` (excluded from `category_yields`).
    - Verifies 3 repeated pages returning identical item `701` trip repeated-page stall detection and mark `Dairy > Milk` in `failed_routes`.
    - Verifies `evaluate_publication_gate()` blocks publication when `Dairy > Cheese` lacks terminal page verification.

### Case 3: Restart Reconciliation, Checkpoint Store/Route Binding, Historical `crawl_date` Preservation, and Per-Row Evidence Linkage
- **Defect Addressed**: On resume, missing staged rows could be discarded while their routes remained marked completed; checkpoints were not bound to `store_number` and `routes_signature`; carry-forward overwrote original observation dates; exported rows were not checked against `raw_evidence` entries for the configured store.
- **Fixes Implemented**:
  - `scraper/checkpoint_manager.py`: Added `compute_routes_signature()`, `reconcile_staged_routes_on_resume()`, and `load_evidence_capture_map()`.
  - `load_checkpoint()` binds strictly to both `store_number` and `expected_routes_signature`, resetting cleanly (`CHECKPOINT_MISMATCH_RESET`) on mismatch.
  - On resume, `WalmartProductionScraper` reconciles staged category/sub-category counts against `category_yields` and automatically re-queues any route missing staged rows into `failed_routes`.
  - `carry_forward_master_assortment()` preserves each un-reobserved item's historical `crawl_date`.
  - `evaluate_publication_gate()` enforces per-row `capture_id` verification against `raw_evidence_<store>_<date>.jsonl` for the configured store.
- **Offline Regression Verification**:
  - `test_issue3_restart_reconciliation_store_routes_date_and_per_row_evidence` (**PASSED**):
    - Verifies missing staged rows for `Beverages > Water` strip its stale yield/terminal status and re-queue it into `failed_routes` without discarding `Bakery > Bread`.
    - Verifies mismatched `routes_signature` returns `CHECKPOINT_MISMATCH_RESET`.
    - Verifies historical item retains `crawl_date == "2026-10-10"` with blanked prices during carry-forward.

### Case 4: Collision-Free Release Directories, Pre-Switch Package Verification, and Output Schema Enforcement
- **Defect Addressed**: Same-second releases could collide on release directory names, and a failed second release could clean up/overwrite the first directory; manifest pointer switching needed pre-switch verification of JSON syntax, record counts, store IDs, 22-field ordering, and SHA-256 checksums.
- **Fixes Implemented**:
  - `scraper/checkpoint_manager.py`: Updated `promote_staging_to_production()` to generate microsecond + UUID release directories (`rel_<date>_<ms>_<uuid8>`) with `os.makedirs(..., exist_ok=False)` and a `dir_created_by_this_call` guard so a failed second publication never deletes an earlier release directory.
  - Added `verify_release_package()` executing pre-switch validation of JSON parseability, record count thresholds, matching `store_location`/store metadata, exact 22-field `REQUIRED_FIELD_ORDER`, and SHA-256 verification before updating `release_manifest_<store>_<date>.json` via `_atomic_write_json()`.
- **Offline Regression Verification**:
  - `test_issue4_unique_release_dirs_safe_failure_and_schema_verification` (**PASSED**):
    - Verifies two sequential releases in the same second get distinct `release_id`s and `release_dir`s.
    - Verifies a blocked/failed second publication leaves Release #1's directory, files, and manifest pointer intact and unmodified.
    - Verifies invalid JSON or schema violations reject inside `verify_release_package()` before pointer updates.

### Case 5: Scheduled Azure Job Durable State, Request/Deadline Limits, and Fail-Closed Key Vault Check
- **Defect Addressed**: Scheduled Azure Container App runs needed durable staging/output state across invocations, clean stops on request budget or wall-clock deadline exhaustion, and fail-closed Key Vault credential validation prior to browser launch.
- **Fixes Implemented**:
  - `scraper/config.py`: Added `STAGING_DIR`, `OUTPUT_DIR`, `MAX_REQUESTS_PER_RUN`, `MAX_RUNTIME_SECONDS`, `RUN_ID`, and fail-closed Key Vault lookup handling (`key_vault_lookup_error`).
  - `scraper/azure_integration.py`: Added `ensure_proxy_credentials_ready()` and `AzureBlobPublisher.sync_durable_state_down()` / `sync_durable_state_up()`.
  - `scraper/walmart_scraper.py`: Enforces Key Vault readiness before launching Chromium (`CREDENTIAL_LOOKUP_FAILED`, `publication_gated=True`); stops cleanly at `max_requests_per_run` or `max_runtime_seconds` with checkpoint persistence and `STOPPED_AT_LIMIT` status without premature promotion.
- **Offline Regression Verification**:
  - `test_issue5_azure_durable_state_limits_and_fail_closed_key_vault` (**PASSED**):
    - Verifies missing Key Vault credentials exit immediately with `CREDENTIAL_LOOKUP_FAILED`, `publication_gated=True`, without launching Playwright.
    - Verifies `max_requests_per_run=1` stops cleanly at `STOPPED_AT_LIMIT` with durable checkpoint preserved and production promotion gated.
    - Verifies durable state download/upload round-trip via `AzureBlobPublisher`.

### Case 6: Dashboard Offline Fixture Labeling and Cross-Artifact Live Evidence Linkage
- **Defect Addressed**: Dashboard examples must stay explicitly labeled as offline fixtures, and live gate verification must reject evidence unless NDJSON logs, raw evidence captures, committed manifests, and Azure publication logs share the same `store_number`, `run_id`, and `release_id`.
- **Fixes Implemented**:
  - `scraper/verify_live_gates.py` & `src/utils/gateEvaluator.ts`: Added strict cross-artifact identity extraction (`_extract_artifact_identities` / `extractArtifactIdentities`) requiring intersecting `store_number`, `run_id`, and `release_id` values across all provided live artifacts before promoting any pending live/Azure gate. Updated `pagination.evidenceNote` to `"Offline regression suite passing"`.
  - `src/App.tsx`, `src/components/AuditEvidenceTab.tsx`, `src/components/SectionInteractions.tsx`: Verified all dashboard labels, record cards, traces, and fixture notices explicitly state offline fixture classification and updated embedded `CONFIG_CODE` snippet to reflect `get_store_by_target` raising `ValueError`.
- **Offline Regression Verification**:
  - `test_issue6_cross_artifact_identity_linkage_and_fixture_labeling` (`scraper/test_scraper.py`, **PASSED**): Confirms mismatched `run_id` / `release_id` / `store_number` keeps live/Azure gates `PENDING` and only matching non-fixture evidence promotes them.
  - `mismatched store, run_id, or release_id across artifacts are rejected and keep gates PENDING` (`src/utils/gateEvaluator.test.ts`, **PASSED**): Confirms frontend evaluator rejects cross-artifact identity mismatches identically.

---

## Remaining Open Gates (Live Execution & Azure Deployment)
No synthetic or fixture artifacts were promoted. The following remain `PENDING` until an actual authorized residential-proxy & Azure Container App execution produces matching real artifacts:
1. `coverage` — Live 21-category execution producing full store data.
2. `pickup_pricing` — Live Walmart Store `#4012` (or configured store) Pickup SSR/GraphQL capture in `.staging/raw_evidence_<store>_<date>.jsonl`.
3. `recovery` — Live interruption + resume trace ending in committed `output/release_manifest_<store>_<date>.json`.
4. `azure` — Executed Azure Container App Job + Blob Storage state sync & release publication log sharing the same `store_number`, `run_id`, and `release_id`.
