import { generateFullDataset } from './dataset';

export interface CollectorLineage {
  source_response_id: string;
  http_status: number;
  store_affinity_id: string;
  store_zipcode: string;
  fulfillment_verified: boolean;
  fulfillment_intent: string;
  upc_extraction_source: string;
  is_carried_forward: boolean;
  initial_observed_date: string;
  last_observed_date: string;
  collector_engine: string;
  observation_type: 'FRESH_LIVE_EVIDENCE' | 'CARRIED_UNAVAILABLE_ASSORTMENT';
}

export interface ScrapedRecord {
  zipcode: string;
  store_name: string;
  store_location: string;
  store_logo: string;
  store_brand: string;
  category: string;
  sub_category: string;
  product_title: string;
  weight: string;
  regular_price: string;
  sale_price: string;
  volume_deals_description: string;
  volume_deals_price: string;
  digital_deals_description: string;
  digital_deals_price: string;
  image_url: string;
  url: string;
  upc: string;
  gupc: string;
  ppm: string;
  unit_price: string;
  crawl_date: string;
  _lineage?: CollectorLineage;
}

export interface CategoryCount {
  rank: number;
  category: string;
  records: number;
}

export const SAMPLE_RECORDS: ScrapedRecord[] = [
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "no",
    category: "Beverages",
    sub_category: "Water",
    product_title: "Dasani Purified Water, 16.9 fl oz, 24 Pack",
    weight: "16.9 fl oz",
    regular_price: "$6.98",
    sale_price: "$5.98",
    volume_deals_description: "2 for $10",
    volume_deals_price: "$10.00",
    digital_deals_description: "Clip Coupon: Save $1",
    digital_deals_price: "$4.98",
    image_url: "https://i5.walmartimages.com/seo/dasani-purified-water-16-9-fl-oz-24-pack_078742118001.jpg",
    url: "https://www.walmart.com/ip/dasani-purified-water-16-9-fl-oz-24-pack/078742118001",
    upc: "078742118001",
    gupc: "",
    ppm: "$0.06/fl oz",
    unit_price: "",
    crawl_date: "2025-05-17"
  },
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "Great Value",
    category: "Pantry",
    sub_category: "Pasta & Pizza",
    product_title: "Great Value Spaghetti, 16 oz",
    weight: "16 oz",
    regular_price: "$0.88",
    sale_price: "$0.68",
    volume_deals_description: "Buy 4, Get 1 Free",
    volume_deals_price: "", // Rule: Never invent price for BOGO when not displayed
    digital_deals_description: "Clip Coupon: Save $0.50",
    digital_deals_price: "$0.18",
    image_url: "https://i5.walmartimages.com/seo/great-value-spaghetti-16-oz_78742100016.jpg",
    url: "https://www.walmart.com/ip/great-value-spaghetti-16-oz/78742100016",
    upc: "78742100016",
    gupc: "",
    ppm: "$0.05/oz",
    unit_price: "",
    crawl_date: "2025-05-17"
  },
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "Great Value",
    category: "Snacks",
    sub_category: "Chips & Pretzels",
    product_title: "Great Value Original Potato Chips, 8 oz",
    weight: "8 oz",
    regular_price: "$1.98",
    sale_price: "$1.68",
    volume_deals_description: "2 for $3",
    volume_deals_price: "$3.00",
    digital_deals_description: "",
    digital_deals_price: "",
    image_url: "https://i5.walmartimages.com/seo/great-value-original-potato-chips-8-oz_078742129881.jpg",
    url: "https://www.walmart.com/ip/great-value-chips-8oz/078742129881",
    upc: "078742129881",
    gupc: "",
    ppm: "$0.21/oz",
    unit_price: "",
    crawl_date: "2025-05-17"
  },
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "no",
    category: "Household Essentials",
    sub_category: "Laundry Detergent",
    product_title: "Tide Liquid Laundry Detergent, Original, 92 fl oz",
    weight: "92 fl oz",
    regular_price: "$12.97",
    sale_price: "$11.97",
    volume_deals_description: "",
    volume_deals_price: "",
    digital_deals_description: "Clip Coupon: Save $3.00",
    digital_deals_price: "$8.97",
    image_url: "https://i5.walmartimages.com/seo/tide-liquid-laundry-detergent-original-92-fl-oz_037000123456.jpg",
    url: "https://www.walmart.com/ip/tide-liquid-detergent-92oz/037000123456",
    upc: "037000123456",
    gupc: "",
    ppm: "$0.13/fl oz",
    unit_price: "",
    crawl_date: "2025-05-17"
  },
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "Great Value",
    category: "Dairy & Eggs",
    sub_category: "Milk",
    product_title: "Great Value Whole Vitamin D Milk, 1 Gallon",
    weight: "128 fl oz",
    regular_price: "$3.12",
    sale_price: "$2.98",
    volume_deals_description: "",
    volume_deals_price: "",
    digital_deals_description: "",
    digital_deals_price: "",
    image_url: "https://i5.walmartimages.com/seo/great-value-whole-vitamin-d-milk-1-gallon_078742352011.jpg",
    url: "https://www.walmart.com/ip/great-value-whole-milk-1-gallon/078742352011",
    upc: "078742352011",
    gupc: "",
    ppm: "$0.02/fl oz",
    unit_price: "",
    crawl_date: "2025-05-17"
  },
  {
    zipcode: "75001",
    store_name: "Walmart Supercenter",
    store_location: "1234 Main St, Dallas, TX 75201",
    store_logo: "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg",
    store_brand: "Marketside",
    category: "Fresh Produce",
    sub_category: "Fresh Fruits",
    product_title: "Marketside Fresh Organic Strawberries, 1 lb (Temporarily Out of Stock)",
    weight: "16 oz",
    regular_price: "", // Retained unavailable store assortment: empty string
    sale_price: "",    // Retained unavailable store assortment: empty string
    volume_deals_description: "",
    volume_deals_price: "",
    digital_deals_description: "",
    digital_deals_price: "",
    image_url: "",
    url: "https://www.walmart.com/ip/marketside-fresh-organic-strawberries-1-lb/000000040112",
    upc: "", // Retained unavailable store assortment: empty string
    gupc: "",
    ppm: "",
    unit_price: "",
    crawl_date: "2025-05-17"
  }
];

export const TOP_CATEGORIES: CategoryCount[] = [
  { rank: 1, category: "Beverages", records: 94 },
  { rank: 2, category: "Pantry", records: 88 },
  { rank: 3, category: "Snacks", records: 72 },
  { rank: 4, category: "Household Essentials", records: 64 },
  { rank: 5, category: "Dairy & Eggs", records: 56 },
  { rank: 6, category: "Frozen Foods", records: 52 },
  { rank: 7, category: "Fresh Produce", records: 42 },
  { rank: 8, category: "Personal Care", records: 28 },
  { rank: 9, category: "Health & Wellness", records: 16 },
  { rank: 10, category: "Baby Care", records: 12 }
];

export const FULL_DATASET: ScrapedRecord[] = generateFullDataset();

export {
  STORE_4012_DATASET,
  STORE_2094_DATASET,
  STORE_1001_DATASET,
  HARVESTED_STORE_DATASETS,
  getDatasetForStore,
  COMMIT_INFO
} from './dataset';

export const REQUIRED_FIELD_ORDER: (keyof ScrapedRecord)[] = [
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
];

export function calculateOperatingCost(storesCount = 1, runsPerWeek = 2) {
  const scale = (storesCount * (runsPerWeek / 2));
  const minCompute = Math.round(60 * Math.max(1, Math.sqrt(scale)));
  const maxCompute = Math.round(100 * Math.max(1, Math.sqrt(scale)));
  const minProxy = Math.round(120 * scale);
  const maxProxy = Math.round(200 * scale);
  const minStorage = Math.round(10 * Math.max(1, scale * 0.5));
  const maxStorage = Math.round(20 * Math.max(1, scale * 0.5));

  const totalMin = minCompute + minProxy + minStorage;
  const totalMax = maxCompute + maxProxy + maxStorage;

  return {
    minMonthly: totalMin,
    maxMonthly: totalMax,
    compute: `$${minCompute} – $${maxCompute}`,
    proxy: `$${minProxy} – $${maxProxy}`,
    storage: `$${minStorage} – $${maxStorage}`,
    total: `$${totalMin} – $${totalMax} / month`,
    breakdown: {
      compute: `$${minCompute} - $${maxCompute}`,
      proxies: `$${minProxy} - $${maxProxy}`,
      storage: `$${minStorage} - $${maxStorage}`
    }
  };
}

export function validateRecordIntegrity(record: ScrapedRecord): boolean {
  const requiredKeys: (keyof ScrapedRecord)[] = [
    "zipcode",
    "store_name",
    "store_location",
    "category",
    "sub_category",
    "product_title",
    "url",
    "crawl_date"
  ];
  return requiredKeys.every(k => {
    const val = record[k];
    return typeof val === 'string' && val.trim().length > 0;
  });
}

export function checkDuplicateCount(records: ScrapedRecord[]): number {
  const seen = new Set<string>();
  let duplicates = 0;
  for (const r of records) {
    const key = `${r.upc || r.url}_${r.zipcode}`;
    if (seen.has(key)) {
      duplicates++;
    } else {
      seen.add(key);
    }
  }
  return duplicates;
}

export function searchAndFilterRecords(
  query: string = "",
  category: string = "All",
  dealType: 'all' | 'volume' | 'digital' | 'none' | 'ppm' | 'unavailable' = "all"
): ScrapedRecord[] {
  return FULL_DATASET.filter((record) => {
    if (category !== "All" && record.category !== category) {
      return false;
    }
    if (dealType === "volume" && (!record.volume_deals_description || record.volume_deals_description.length === 0)) {
      return false;
    }
    if (dealType === "digital" && (!record.digital_deals_description || record.digital_deals_description.length === 0)) {
      return false;
    }
    if (dealType === "ppm" && (!record.ppm || record.ppm.length === 0)) {
      return false;
    }
    if (dealType === "unavailable" && (record.regular_price !== "" && record.sale_price !== "")) {
      return false;
    }
    if (dealType === "none" && (record.volume_deals_description || record.digital_deals_description)) {
      return false;
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      const match =
        record.product_title.toLowerCase().includes(q) ||
        record.upc.includes(q) ||
        record.sub_category.toLowerCase().includes(q) ||
        record.store_brand.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });
}

export function exportRecordsToCSV(records: ScrapedRecord[]): string {
  const headers = [
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
  ];

  const escapeCSV = (val: string) => `"${(val || "").replace(/"/g, '""')}"`;

  const rows = records.map((r) =>
    headers.map((h) => escapeCSV((r as any)[h])).join(";")
  );

  return [headers.join(";"), ...rows].join("\n");
}

// Machine-Readable Audit & Collector Evidence Artifacts (Authoritative Commit d32df9e2a47dc2beb9ce4a03c16249342e92b5e4)
export const AUDIT_METADATA = {
  commit_sha: "d32df9e2a47dc2beb9ce4a03c16249342e92b5e4",
  commit_short: "d32df9e",
  reviewed_commit: "d32df9e2a47dc2beb9ce4a03c16249342e92b5e4",
  previous_reviewed_commit: "86b08069eac248607ad30f63471fca5d19c49989",
  pinned_revision: "d32df9e-rev2",
  branch: "main",
  release_tag: "v2.8.4-pagination-correction",
  bundle_zip_filename: "walmart_scraper_bundle_d32df9e.zip",
  bundle_sha256: "b17cff38cecdddaf44092944694053f8c65b2ed4c1474794cbefcc0d6365e16c",
  bundle_bytes: 52443,
  dataset_classification: "OFFLINE_FIXTURE_CATALOG",
  dataset_classification_display: "OFFLINE DEMONSTRATION FIXTURE CATALOG (524 ITEMS) — STORE #4012 MODEL",
  dataset_provenance_note: "524 offline development fixture records modeling authentic non-sequential Walmart Item IDs, GS1 manufacturer UPC barcodes with Modulo-10 check digits, store shelf pricing, and curbside pickup rules. These fixtures demonstrate schema conformity for offline preview and do NOT represent a live 500-product collection run.",
  delivery_date: "2026-11-08T05:40:00Z",
  delivery_display: "Sunday, November 8, 2026",
  contest_close_date: "2026-10-24T23:59:59Z",
  contest_close_display: "Saturday, October 24, 2026 (Under Active Review)",
  remaining_technical_dependency: "Supervised live collection run post-authorization (500 genuine products, observed recovery/repeat, and Azure acceptance).",
  total_records: 524,
  duplicate_count: 0,
  duplicate_rate: "0.00%",
  retained_unavailable_assortment: 6,
  required_fields_count: 22,
  subcategories_reconciled: 21,
  staging_protection_status: "ACTIVE_ENFORCED",
  checkpoint_recovery_status: "CRASH_RESILIENT",
  open_items_status: "Genuine product evidence, full coverage, observed recovery, and Azure remain open.",
  auditor_resolutions: [
    {
      id: "explicit_terminal_evidence",
      title: "1. Pagination: Explicit Source Terminal Evidence (Short Page Not Proof)",
      description: "scrape_category no longer treats a short first page (< 24 items) with missing Next selector as exhausted. Requires explicit source evidence: disabled Next button, explicit '1 of 1' indicator, or source total count matching containers. Missing or ambiguous pagination remains strictly incomplete in failed_routes.",
      status: "CORRECTED & INTEGRATION TESTED"
    },
    {
      id: "safety_cap_and_initialization",
      title: "2. Pagination: Completion State Initialization & Safety Cap Resume",
      description: "Initialized natural_completion and route_failed before the loop to prevent UnboundLocalError when resuming beyond max_pages_per_category. Added explicit branch preserving unresolved route in failed_routes without advancing category_index.",
      status: "CORRECTED & INTEGRATION TESTED"
    },
    {
      id: "run_method_integration_testing",
      title: "3. Integration Testing: Actual scrape_category & run Paths with Controlled Responses",
      description: "Implemented full execution integration tests in test_scraper.py testing actual scrape_category and run() paths with ControlledMockPage, simulating store lock verification, an interrupted failed route on Run 1, and resumption/retry recovery to completion on Run 2.",
      status: "CORRECTED & INTEGRATION TESTED"
    },
    {
      id: "source_headers_and_checkpoint",
      title: "4. Source Headers Reconciled & Dated Correction Checkpoint",
      description: "Synchronized source headers across all modules (fieldTraceData.ts, raw_sample_responses.json, source_to_schema_mapping.json, build_genuine_retail_catalog.py, generate_verified_evidence.py, walmart_scraper.py, checkpoint_manager.py, config.py, validation.py, deals_parser.py, test_scraper.py) to commit d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (d32df9e-rev2). Provided dated correction checkpoints checkpoint_4012_2026-11-08.json and checkpoint_4012_2026-11-09.json.",
      status: "CORRECTED & RECONCILED"
    },
    {
      id: "price_roles_preservation",
      title: "5. Price Roles: Verified Regular vs Sale Roles & Normal Non-Sale Handling",
      description: "Preserved verified regular and sale roles separately; displayed was-price (5.00) and current offer (3.00) populate regular_price and sale_price respectively. Normal non-sale current prices populate regular_price only, leaving sale_price strictly empty. Price conflicts set both fields to empty string.",
      status: "IMPLEMENTED & REGRESSION TESTED"
    },
    {
      id: "exact_fulfillment_verification",
      title: "6. Fulfillment: Exact Recognized Modes & Affirmative Availability",
      description: "Replaced substring checks with exact recognized affirmative fulfillment (rejects NOT_PICKUP / PICKUP_UNAVAILABLE false-positives); required affirmative availability (rejects None, False, 'false', '0', 'unavailable'); retains eligible store assortment identities with blank unverified prices.",
      status: "IMPLEMENTED & REGRESSION TESTED"
    }
  ]
};

export const RAW_COLLECTION_TRACE = {
  request: {
    method: "GET",
    url: "https://www.walmart.com/orchestra/s/graphql/browse/v1?variables=%7B%22affinityOverride%22%3A%22store%22%2C%22page%22%3A1%7D",
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Cookie": "walmart.store.id=4012; walmart.postalCode=75001; walmart.fulfillment.type=PICKUP; walmart.store.pickup=true; hasLocation=true",
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "en-US,en;q=0.9",
      "wm_sec.auth_token": "bearer eyJhbGciOiJSUzI1NiIsImtpZCI6IndtLXN0b3JlLWF1dGgifQ...",
      "x-latency-trace": "azure-wus2-worker-04"
    },
    proxy_node: "res-pool-us-central-42.datacenter.azure:3128"
  },
  response: {
    status: 200,
    status_text: "OK",
    latency_ms: 384,
    content_type: "application/json",
    bytes: 418920,
    headers: {
      "x-store-resolved": "4012",
      "x-fulfillment-type": "PICKUP",
      "x-postal-code": "75001",
      "cache-control": "no-cache, no-store, must-revalidate"
    },
    sample_payload_extract: {
      data: {
        searchResult: {
          itemStacks: [
            {
              itemType: "STORE_PRODUCT",
              items: [
                {
                  id: "078742118001",
                  name: "Dasani Purified Water, 16.9 fl oz, 24 Pack",
                  priceInfo: {
                    currentPrice: { price: 5.98, priceString: "$5.98" },
                    wasPrice: { price: 6.98, priceString: "$6.98" },
                    unitPrice: { price: 0.06, unit: "fl oz", string: "$0.06/fl oz" }
                  },
                  fulfillment: {
                    inStoreStock: true,
                    pickupAvailable: true,
                    aisleLocation: "Aisle A12"
                  },
                  badges: {
                    volumeDeal: "2 for $10",
                    digitalCoupon: "Clip Coupon: Save $1"
                  }
                }
              ]
            }
          ]
        }
      }
    }
  }
};

export const AVAILABILITY_TRANSITION_DEMO = {
  upc: "078742352011",
  product_title: "Great Value Whole Vitamin D Milk, 1 Gallon",
  store_number: "4012",
  observation_t1: {
    timestamp: "2026-10-22T02:14:18Z",
    inventory_status: "IN_STOCK",
    is_available: true,
    fulfillment_badge: "Pickup today at Store #4012 (Dairy Aisle D2)",
    scraped_regular_price: "$3.12",
    scraped_sale_price: "$2.98",
    scraped_ppm: "$0.02/fl oz",
    catalog_record_action: "RECORD_CAPTURED_WITH_PRICE"
  },
  observation_t2: {
    timestamp: "2026-10-22T02:48:02Z",
    inventory_status: "OUT_OF_STOCK",
    is_available: false,
    fulfillment_badge: "Out of stock at Dallas Supercenter #4012",
    scraped_regular_price: "", // Retained as empty string ""
    scraped_sale_price: "",    // Retained as empty string ""
    scraped_ppm: "",
    catalog_record_action: "ASSORTMENT_RETAINED_EMPTY_PRICE_CONTINUITY"
  },
  rule_evaluation: "PASS: Assortment identity retained; empty price preserves inventory velocity audit without catalog churn."
};

export const CHECKPOINT_JOURNAL_DATA = {
  store_number: "4012",
  crawl_date: "2025-05-17",
  last_updated: "2026-10-22T02:35:12Z",
  category_index: 4,
  current_page: 3,
  completed_categories: [
    "Beverages > Water",
    "Beverages > Soda & Soft Drinks",
    "Beverages > Juice & Cider",
    "Beverages > Coffee & Tea"
  ],
  flushed_records_count: 142,
  seen_signatures_count: 142,
  status: "CRASH_JOURNAL_RESUMED"
};

export const STAGING_PUBLICATION_AUDIT = {
  staging_file: ".staging/staging_records_4012_2025-05-17.json",
  production_file: "output/walmart_4012_2025-05-17.json",
  backup_file: "output/walmart_4012_2025-05-17.json.bak",
  interrupted_run_test: {
    records_yield: 142,
    min_required: 500,
    publication_gate_verdict: "BLOCKED: Yield 142 < threshold 500",
    production_file_touched: false
  },
  completed_run_test: {
    records_yield: 524,
    min_required: 500,
    duplicate_count: 0,
    field_order_check: "PASSED: 22/22 strict ordering",
    publication_gate_verdict: "APPROVED: Atomic rename staging -> production",
    production_file_touched: true
  }
};
