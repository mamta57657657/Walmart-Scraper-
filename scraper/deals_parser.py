"""
deals_parser.py
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
Distinguishes Volume Deals from Digital Deals according to strict contest rules:
1. Volume Deals:
   - Does NOT require clipping or activation.
   - Examples: '2 for $5', 'Buy 1, Get 1 Free', 'Mix or Match 5 for $10', 'Must buy 4 at $1.99 each'.
   - Store exact terms in volume_deals_description.
   - Store displayed promotional price in volume_deals_price (NEVER calculate for BOGO if not displayed).
2. Digital Deals:
   - REQUIRES customer to clip, activate, save, or add a coupon.
   - Examples: 'Clip Coupon: Save $2', '$3.99 each with Digital Coupon', 'Save $1 with Digital Coupon'.
   - Store exact terms in digital_deals_description.
   - Store resulting promotional price in digital_deals_price ONLY when explicitly displayed by Walmart.
   - NEVER treat Walmart Cash or cashback as immediate price reduction.
"""

import re
from typing import Tuple, Dict, Any, Optional

DIGITAL_COUPON_KEYWORDS = [
    r'clip\s+coupon',
    r'digital\s+coupon',
    r'with\s+coupon',
    r'clipped\s+coupon',
    r'save\s+\$?\d+(\.\d{2})?\s+with\s+coupon',
    r'coupon\s+available',
    r'activate\s+offer'
]

VOLUME_DEAL_PATTERNS = [
    r'\b\d+\s+for\s+\$?\d+(\.\d{2})?\b',
    r'buy\s+\d+,\s*get\s+\d+\s+free',
    r'buy\s+\d+\s+get\s+\d+\s+free',
    r'bogo',
    r'mix\s+or\s+match\s+\d+\s+for\s+\$?\d+(\.\d{2})?',
    r'must\s+buy\s+\d+\s+at\s+\$?\d+(\.\d{2})?',
    r'save\s+\$?\d+(\.\d{2})?\s+when\s+you\s+buy\s+\d+'
]

def parse_deals(badge_text: str, promo_price_text: str = "") -> Dict[str, str]:
    """
    Parses badge text and secondary price strings into structured volume and digital deal fields.
    Does NOT invent, estimate, or calculate prices.
    Returns:
    {
        'volume_deals_description': str,
        'volume_deals_price': str,
        'digital_deals_description': str,
        'digital_deals_price': str
    }
    """
    res = {
        'volume_deals_description': '',
        'volume_deals_price': '',
        'digital_deals_description': '',
        'digital_deals_price': ''
    }

    if not badge_text:
        return res

    raw_text = badge_text.strip()
    lower_text = raw_text.lower()

    # Rule: Cashback / manufacturer rebate / Walmart Cash is NOT an immediate digital discount
    if 'walmart cash' in lower_text or 'cash back' in lower_text or 'rebate' in lower_text:
        return res

    # 1. Check for Digital Deal (Requires clip/activation)
    is_digital = any(re.search(pat, lower_text) for pat in DIGITAL_COUPON_KEYWORDS)
    if is_digital:
        res['digital_deals_description'] = raw_text
        # Only populate digital_deals_price if explicitly displayed by Walmart
        if promo_price_text and promo_price_text.strip().startswith('$'):
            res['digital_deals_price'] = promo_price_text.strip()
        else:
            # Check if badge text explicitly provides the net price e.g. "$3.99 each with Digital Coupon"
            net_match = re.search(r'(\$\d+(\.\d{2})?)\s+each\s+with', raw_text, re.IGNORECASE)
            if net_match:
                res['digital_deals_price'] = net_match.group(1)
            else:
                res['digital_deals_price'] = ''
        return res

    # 2. Check for Volume Deal (Multi-buy / BOGO without coupon)
    is_volume = any(re.search(pat, lower_text) for pat in VOLUME_DEAL_PATTERNS)
    if is_volume:
        res['volume_deals_description'] = raw_text
        if promo_price_text and promo_price_text.strip().startswith('$'):
            res['volume_deals_price'] = promo_price_text.strip()
        else:
            # Extract displayed bundled price (e.g. "2 for $10" -> "$10.00" or "$10")
            price_match = re.search(r'for\s+(\$\d+(\.\d{2})?)', raw_text, re.IGNORECASE)
            if price_match:
                p = price_match.group(1)
                res['volume_deals_price'] = f"{p}.00" if '.' not in p else p
            else:
                # E.g., BOGO with no price displayed -> keep empty! Do NOT invent a price.
                res['volume_deals_price'] = ''
        return res

    return res
