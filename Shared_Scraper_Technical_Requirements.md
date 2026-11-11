# Shared Scraper Technical Requirements: Microsoft Azure Deployment

## 1. Executive Summary & Objective
This specification outlines the technical, data, and compliance standards for the Production-Ready Walmart Scraper running on Microsoft Azure. The scraper is engineered to collect high-fidelity, location-specific product records across configurable categories, accurately isolating deals, measurements, and fulfillment contexts.

---

## 2. Scope & Scheduling
- **Schedule**: Scrapes each configured location twice per week (cron: `0 2 * * 2,5` UTC). Daily scraping is not required.
- **Multi-Location**: Supports dynamic location targeting via store number, address, or ZIP code without code modifications (`config.py`).
- **Category Coverage**: Fully processes all categories and subcategories defined in `Walmart_Category_URLs.csv`.
- **Comprehensive Catalog**: Captures the complete available catalog through automated pagination and lazy-loading DOM triggers.

---

## 3. Strict 22-Field Output Schema
Output records MUST conform to the exact field sequence below. Missing fields return empty strings `""`, never `null`.

1. `zipcode` (string, e.g. "75001")
2. `store_name` (string, e.g. "Walmart Supercenter")
3. `store_location` (string, e.g. "1234 Main St, Dallas, TX 75201")
4. `store_logo` (string URL)
5. `store_brand` (Walmart private label name: "Great Value", "Equate", etc., or "no")
6. `category` (string, e.g. "Beverages")
7. `sub_category` (string, e.g. "Water")
8. `product_title` (string)
9. `weight` (string, e.g. "16.9 fl oz")
10. `regular_price` (string, e.g. "$6.98")
11. `sale_price` (string, e.g. "$5.98")
12. `volume_deals_description` (string, e.g. "2 for $10", "Buy 1, Get 1 Free")
13. `volume_deals_price` (string, e.g. "$10.00", or "" for BOGO when price is not displayed)
14. `digital_deals_description` (string, e.g. "Clip Coupon: Save $1")
15. `digital_deals_price` (string, e.g. "$4.98", only when explicitly displayed)
16. `image_url` (string URL)
17. `url` (string product URL)
18. `upc` (string numeric barcode)
19. `gupc` (strictly empty string `""`)
20. `ppm` (Price Per Measure, e.g. "$0.06/fl oz", scraped directly from Walmart)
21. `unit_price` (strictly empty string `""`, calculated downstream)
22. `crawl_date` (string "YYYY-MM-DD", collection date, final field)

---

## 4. Business & Data Rules
- **PPM (Price Per Measure)**: Must be scraped directly from Walmart with displayed unit (`$0.25/oz`, `$0.18/fl oz`, `$3.99/lb`). Do not calculate or estimate.
- **GUPC & Unit Price**: Must be returned as `""`. Original UPC preserved in `upc`.
- **Approximate Weight Exclusion**: Products containing `approx`, `approximately`, `about`, or `est.` in their weight are excluded.
- **Deals Separation**:
  - Volume deals (no clipping required): stored in `volume_deals_description` and `volume_deals_price`.
  - Digital coupons (require clipping/activation): stored in `digital_deals_description` and `digital_deals_price`.
  - Walmart Cash and rebates are not immediate price reductions.
- **Fulfillment & Pricing Context**:
  - Context locked via cookies (`walmart.store.id`, `walmart.fulfillment.type=PICKUP`).
  - Third-party marketplace items ("Sold by [Seller]") excluded.
  - Shipping-only items excluded.
  - Sponsored placements excluded.

---

## 5. Architectural Reliability & Azure Integration
- **Engine**: Python 3.11 + Playwright headless Chromium.
- **Cloud Execution**: Azure Container App Job / Azure VM.
- **Pacing & Retries**: Exponential backoff with rate-limit detection (HTTP 429/403).
- **Silent Blocking Safeguards**: Canary product checks (`canary_upc` in CSV), yield drop detection.
- **Atomic Commits**: Output written to `.tmp`, validated against quality gates (minimum 500 records, 0 duplicates, 100% field completeness), then atomically promoted. Failed runs preserve previous `.bak` dataset.
- **Security**: Zero hardcoded credentials; proxy and storage keys managed via Azure Key Vault.
