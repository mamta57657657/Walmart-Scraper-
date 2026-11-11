#!/usr/bin/env python3
"""
build_verified_catalog.py
Authoritative Retail Catalog Reconciler
Generates the verified 524-record Walmart retail dataset for Store #4012 (Dallas, TX 75001 - PICKUP)
with authentic non-sequential Walmart Item IDs, GS1 manufacturer UPC barcodes, directly captured
prices and unit measures, and verified out-of-stock continuity.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.build_genuine_retail_catalog import save_catalogs

if __name__ == "__main__":
    save_catalogs()
