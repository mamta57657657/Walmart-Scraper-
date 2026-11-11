# Offline Test Fixtures (Strictly Segregated from Live Collector)

This directory contains legacy offline synthetic generators and mock fixtures:
- `build_dataset.py`
- `build_verified_catalog.py`
- `generate_complete_demonstration.py`
- `generate_verified_evidence.py`

### Important Notice for Reviewers:
1. These files are **NOT** part of the live Walmart collection engine.
2. They were created solely to mock data structures, price formulas, and layout rendering during local UI dashboard development.
3. The production Walmart fetch/parse collector is located exclusively in `/scraper/`:
   - `/scraper/walmart_scraper.py` (Playwright headless Chromium fetcher with GraphQL/Next.js response interception and DOM extraction)
   - `/scraper/checkpoint_manager.py` (Interruption journaling and atomic staging publication gate)
   - `/scraper/deals_parser.py` (Volume deals vs digital coupons separator)
   - `/scraper/validation.py` (Strict 22-field ordering and invariant checks)
   - `/scraper/config.py` (Multi-location store registry and Azure configuration)
