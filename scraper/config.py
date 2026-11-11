"""
config.py
Externalized configuration for Microsoft Azure deployment:
- Credentials, proxies, and secrets loaded from environment or Azure Key Vault
- Nationwide 50-State multi-location registry
- Pacing, concurrency, retries, and canary thresholds
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class StoreConfig:
    store_number: str
    zipcode: str
    name: str
    address: str
    state_code: str = ""
    city: str = ""
    logo_url: str = "https://i5.walmartimages.com/dfw/63fd9f59-b3e1/7a569e53-f29a-4c3d-bfaf-6f7a158bfadd/v1/walmartLogo.svg"

# Pre-configured multi-location registry across all USA states
DEFAULT_STORES: List[StoreConfig] = [
    StoreConfig(store_number="4012", zipcode="75001", name="Walmart Supercenter #4012", address="1234 Main St, Dallas, TX 75201", state_code="TX", city="Dallas"),
    StoreConfig(store_number="1129", zipcode="78701", name="Walmart Supercenter #1129", address="2525 E Anderson Ln, Austin, TX 78752", state_code="TX", city="Austin"),
    StoreConfig(store_number="3782", zipcode="32801", name="Walmart Supercenter #3782", address="5991 S Goldenrod Rd, Orlando, FL 32822", state_code="FL", city="Orlando"),
    StoreConfig(store_number="100",  zipcode="72712", name="Walmart Supercenter #100",  address="406 S Walton Blvd, Bentonville, AR 72712", state_code="AR", city="Bentonville"),
    StoreConfig(store_number="5154", zipcode="91770", name="Walmart Supercenter #5154", address="1827 Walnut Grove Ave, Rosemead, CA 91770", state_code="CA", city="Rosemead"),
    StoreConfig(store_number="5293", zipcode="11581", name="Walmart Supercenter #5293", address="77 Green Acres Rd S, Valley Stream, NY 11581", state_code="NY", city="Valley Stream"),
    StoreConfig(store_number="5402", zipcode="60639", name="Walmart Supercenter #5402", address="4650 W North Ave, Chicago, IL 60639", state_code="IL", city="Chicago"),
    StoreConfig(store_number="2599", zipcode="98057", name="Walmart Supercenter #2599", address="743 Rainier Ave S, Renton, WA 98057", state_code="WA", city="Renton")
]

# Nationwide directory of stores covering all 50 states + DC
ALL_USA_STORES: Dict[str, StoreConfig] = {
    "AL": StoreConfig("1481", "35215", "Walmart Supercenter #1481", "1600 Montclair Rd, Birmingham, AL 35215", "AL", "Birmingham"),
    "AK": StoreConfig("2070", "99507", "Walmart Supercenter #2070", "3101 A St, Anchorage, AK 99507", "AK", "Anchorage"),
    "AZ": StoreConfig("2512", "85032", "Walmart Supercenter #2512", "4747 E Bell Rd, Phoenix, AZ 85032", "AZ", "Phoenix"),
    "AR": StoreConfig("100",  "72712", "Walmart Supercenter #100",  "406 S Walton Blvd, Bentonville, AR 72712", "AR", "Bentonville"),
    "CA": StoreConfig("5154", "91770", "Walmart Supercenter #5154", "1827 Walnut Grove Ave, Rosemead, CA 91770", "CA", "Rosemead"),
    "CO": StoreConfig("1492", "80014", "Walmart Supercenter #1492", "14000 E Exposition Ave, Aurora, CO 80014", "CO", "Denver"),
    "CT": StoreConfig("1891", "06042", "Walmart Supercenter #1891", "420 Buckland Hills Dr, Manchester, CT 06042", "CT", "Manchester"),
    "DE": StoreConfig("2555", "19720", "Walmart Supercenter #2555", "117 Wilton Blvd, New Castle, DE 19720", "DE", "New Castle"),
    "DC": StoreConfig("5968", "20011", "Walmart Supercenter #5968", "5929 Georgia Ave NW, Washington, DC 20011", "DC", "Washington"),
    "FL": StoreConfig("3782", "32801", "Walmart Supercenter #3782", "5991 S Goldenrod Rd, Orlando, FL 32822", "FL", "Orlando"),
    "GA": StoreConfig("1338", "30318", "Walmart Supercenter #1338", "1801 Howell Mill Rd NW, Atlanta, GA 30318", "GA", "Atlanta"),
    "HI": StoreConfig("3478", "96814", "Walmart Supercenter #3478", "700 Keeaumoku St, Honolulu, HI 96814", "HI", "Honolulu"),
    "ID": StoreConfig("2508", "83704", "Walmart Supercenter #2508", "8300 W Overland Rd, Boise, ID 83704", "ID", "Boise"),
    "IL": StoreConfig("5402", "60639", "Walmart Supercenter #5402", "4650 W North Ave, Chicago, IL 60639", "IL", "Chicago"),
    "IN": StoreConfig("1459", "46254", "Walmart Supercenter #1459", "7245 US 31 S, Indianapolis, IN 46254", "IN", "Indianapolis"),
    "IA": StoreConfig("1723", "50317", "Walmart Supercenter #1723", "5101 SE 14th St, Des Moines, IA 50317", "IA", "Des Moines"),
    "KS": StoreConfig("1221", "67209", "Walmart Supercenter #1221", "10600 W 21st St N, Wichita, KS 67209", "KS", "Wichita"),
    "KY": StoreConfig("1310", "40229", "Walmart Supercenter #1310", "11901 Standiford Plaza Dr, Louisville, KY 40229", "KY", "Louisville"),
    "LA": StoreConfig("1353", "70123", "Walmart Supercenter #1353", "5110 Jefferson Hwy, Harahan, LA 70123", "LA", "New Orleans"),
    "ME": StoreConfig("1997", "04074", "Walmart Supercenter #1997", "500 Gallery Blvd, Scarborough, ME 04074", "ME", "Scarborough"),
    "MD": StoreConfig("2244", "21227", "Walmart Supercenter #2244", "3601 Washington Blvd, Halethorpe, MD 21227", "MD", "Baltimore"),
    "MA": StoreConfig("2341", "02169", "Walmart Supercenter #2341", "301 Falls Blvd, Quincy, MA 02169", "MA", "Quincy"),
    "MI": StoreConfig("2558", "48310", "Walmart Supercenter #2558", "33201 Van Dyke Ave, Sterling Heights, MI 48310", "MI", "Detroit"),
    "MN": StoreConfig("2199", "55431", "Walmart Supercenter #2199", "1300 E 78th St, Bloomington, MN 55431", "MN", "Minneapolis"),
    "MS": StoreConfig("1126", "39212", "Walmart Supercenter #1126", "2711 Greenway Dr, Jackson, MS 39212", "MS", "Jackson"),
    "MO": StoreConfig("1343", "64133", "Walmart Supercenter #1343", "11601 E US Hwy 40, Kansas City, MO 64133", "MO", "Kansas City"),
    "MT": StoreConfig("1956", "59102", "Walmart Supercenter #1956", "2525 King Ave W, Billings, MT 59102", "MT", "Billings"),
    "NE": StoreConfig("1637", "68137", "Walmart Supercenter #1637", "16960 W Maple Rd, Omaha, NE 68137", "NE", "Omaha"),
    "NV": StoreConfig("1560", "89119", "Walmart Supercenter #1560", "6005 S Eastern Ave, Las Vegas, NV 89119", "NV", "Las Vegas"),
    "NH": StoreConfig("1749", "03103", "Walmart Supercenter #1749", "3 Commerce Dr, Bedford, NH 03103", "NH", "Manchester"),
    "NJ": StoreConfig("3456", "07032", "Walmart Supercenter #3456", "150 Harrison Ave, Kearny, NJ 07032", "NJ", "Kearny"),
    "NM": StoreConfig("1397", "87109", "Walmart Supercenter #1397", "400 Eubank Blvd NE, Albuquerque, NM 87109", "NM", "Albuquerque"),
    "NY": StoreConfig("5293", "11581", "Walmart Supercenter #5293", "77 Green Acres Rd S, Valley Stream, NY 11581", "NY", "Valley Stream"),
    "NC": StoreConfig("1666", "28212", "Walmart Supercenter #1666", "8180 E Independence Blvd, Charlotte, NC 28212", "NC", "Charlotte"),
    "ND": StoreConfig("1581", "58103", "Walmart Supercenter #1581", "4731 13th Ave S, Fargo, ND 58103", "ND", "Fargo"),
    "OH": StoreConfig("2098", "43228", "Walmart Supercenter #2098", "3900 Gantz Rd, Grove City, OH 43228", "OH", "Columbus"),
    "OK": StoreConfig("1626", "73132", "Walmart Supercenter #1626", "6100 W Reno Ave, Oklahoma City, OK 73132", "OK", "Oklahoma City"),
    "OR": StoreConfig("2927", "97060", "Walmart Supercenter #2927", "23500 NE Sandy Blvd, Wood Village, OR 97060", "OR", "Portland"),
    "PA": StoreConfig("2141", "19148", "Walmart Supercenter #2141", "1675 S Christopher Columbus Blvd, Philadelphia, PA 19148", "PA", "Philadelphia"),
    "RI": StoreConfig("2283", "02816", "Walmart Supercenter #2283", "650 Centre of New England Blvd, Coventry, RI 02816", "RI", "Coventry"),
    "SC": StoreConfig("1333", "29209", "Walmart Supercenter #1333", "1326 Bush River Rd, Columbia, SC 29209", "SC", "Columbia"),
    "SD": StoreConfig("1545", "57106", "Walmart Supercenter #1545", "5521 W Arrowhead Pkwy, Sioux Falls, SD 57106", "SD", "Sioux Falls"),
    "TN": StoreConfig("0659", "37211", "Walmart Supercenter #0659", "4040 Nolensville Pike, Nashville, TN 37211", "TN", "Nashville"),
    "TX": StoreConfig("4012", "75001", "Walmart Supercenter #4012", "1234 Main St, Dallas, TX 75201", "TX", "Dallas"),
    "UT": StoreConfig("2217", "84115", "Walmart Supercenter #2217", "4627 S 900 E, Salt Lake City, UT 84115", "UT", "Salt Lake City"),
    "VT": StoreConfig("2380", "05495", "Walmart Supercenter #2380", "863 Harvest Ln, Williston, VT 05495", "VT", "Williston"),
    "VA": StoreConfig("1523", "23228", "Walmart Supercenter #1523", "7901 Brook Rd, Richmond, VA 23228", "VA", "Richmond"),
    "WA": StoreConfig("2599", "98057", "Walmart Supercenter #2599", "743 Rainier Ave S, Renton, WA 98057", "WA", "Seattle"),
    "WV": StoreConfig("2036", "25309", "Walmart Supercenter #2036", "1001 RHL Blvd, Charleston, WV 25309", "WV", "Charleston"),
    "WI": StoreConfig("1551", "53224", "Walmart Supercenter #1551", "4015 N 76th St, Milwaukee, WI 53224", "WI", "Milwaukee"),
    "WY": StoreConfig("1315", "82009", "Walmart Supercenter #1315", "580 Livingston Ave, Cheyenne, WY 82009", "WY", "Cheyenne")
}

def get_store_by_target(target: str) -> StoreConfig:
    """
    Dynamically resolves store by 2-letter state code, store number, or zip code.
    Defaults to Dallas Supercenter #4012 if not matched.
    """
    clean = target.upper().strip()
    if clean in ALL_USA_STORES:
        return ALL_USA_STORES[clean]
    for s in ALL_USA_STORES.values():
        if s.store_number == clean or s.zipcode == clean:
            return s
    return ALL_USA_STORES["TX"]

@dataclass
class ScraperSettings:
    # Azure Environment & Storage
    azure_storage_connection_string: str = field(
        default_factory=lambda: os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    )
    azure_container_name: str = field(
        default_factory=lambda: os.getenv("AZURE_CONTAINER_NAME", "walmart-scraper-data")
    )
    azure_key_vault_url: str = field(
        default_factory=lambda: os.getenv("AZURE_KEY_VAULT_URL", "")
    )

    # Residential / Datacenter Proxies
    proxy_server: str = field(default_factory=lambda: os.getenv("PROXY_SERVER", ""))
    proxy_username: str = field(default_factory=lambda: os.getenv("PROXY_USERNAME", ""))
    proxy_password: str = field(default_factory=lambda: os.getenv("PROXY_PASSWORD", ""))

    # Scraping Pacing & Reliability Safeguards
    headless: bool = True
    page_load_timeout_ms: int = 30000
    action_timeout_ms: int = 15000
    delay_between_requests_sec: float = 1.5
    max_retries_per_page: int = 3
    backoff_multiplier: float = 2.0
    min_expected_records_per_run: int = 500
    # Production pagination: None or large integer allows full pagination to EOF without artificial demo cap
    max_pages_per_category: Optional[int] = None
    verify_store_fulfillment: bool = True
    require_full_category_completion: bool = True

    # Exact Affirmative Fulfillment & Availability Verification
    recognized_fulfillment_modes: List[str] = field(
        default_factory=lambda: ["PICKUP", "STORE_PICKUP", "IN_STORE_PICKUP", "CURBSIDE_PICKUP", "GROCERY_PICKUP"]
    )
    enforce_affirmative_pickup_availability: bool = True

    # Price Roles Separation & Integrity
    enforce_strict_price_roles: bool = True  # Verified was-price -> regular_price; current offer -> sale_price; normal non-sale -> regular only

    # Structured Pagination & Completion Coverage
    enforce_structured_pagination: bool = True
    require_confirmed_terminal_page: bool = True

    # Resume & Interruption Recovery
    retry_unresolved_routes_on_resume: bool = True

    # Paths
    categories_csv_path: str = field(
        default_factory=lambda: os.getenv("CATEGORIES_CSV_PATH", "Walmart_Category_URLs.csv")
    )
    output_directory: str = "output"

def get_settings() -> ScraperSettings:
    return ScraperSettings()
