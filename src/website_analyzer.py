"""
website_analyzer.py
-------------------
Analyzes a lead's website to detect gaps and opportunities
for Detagenix services. Uses rule-based HTML scraping only
(no external AI API required).

Returns:
    - recommended_services : comma-separated string of service names
    - opportunity_score    : integer 0-100
    - priority             : "High" | "Medium" | "Low"
"""

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Detagenix service definitions
# Each entry: (service_name, weight_0_to_20, detection_function)
# Weight reflects how valuable / urgent the service opportunity is.
# ---------------------------------------------------------------------------

# Request headers to mimic a real browser (avoid 403 blocks)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 8  # seconds


def fetch_html(url: str):
    """
    Fetch raw HTML from a URL.
    Returns (soup, raw_text_lower, is_https) or (None, None, None) on failure.
    Public so other modules (enrichment, lead_processor) can reuse it.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        raw_text = resp.text.lower()   # lowercased for keyword detection
        is_https = resp.url.startswith("https://")
        return soup, raw_text, is_https
    except Exception:
        return None, None, None

# Backward-compatible alias
_fetch_html = fetch_html


# ---------------------------------------------------------------------------
# Individual signal detectors
# Each returns True if the opportunity/gap EXISTS (i.e., service is needed)
# ---------------------------------------------------------------------------

def _needs_web_development(website: str, soup, raw_text) -> bool:
    """Lead has no website at all."""
    return not website or website.strip() == ""


def _needs_website_revamp(website: str, soup, raw_text) -> bool:
    """Website exists but shows signs of being outdated or very thin."""
    if not soup:
        return False
    # Signs of outdated site: no viewport meta, no CSS framework hint,
    # very few links, or very short page body
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    has_meta_desc = bool(soup.find("meta", attrs={"name": "description"}))
    body = soup.find("body")
    body_text_len = len(body.get_text(strip=True)) if body else 0
    all_links = soup.find_all("a", href=True)
    # Flag as needing revamp if: no viewport OR no meta description AND very thin content
    if not has_viewport:
        return True
    if not has_meta_desc and body_text_len < 800:
        return True
    if len(all_links) < 5 and body_text_len < 500:
        return True
    return False


def _needs_mobile_app(website: str, soup, raw_text) -> bool:
    """No mobile app presence detected on the website."""
    if not raw_text:
        return True  # can't access site → assume gap
    app_keywords = [
        "play store", "app store", "google play", "appstore",
        "download app", "mobile app", "android app", "ios app",
        "playstore", "apk", "itunes.apple.com", "play.google.com"
    ]
    return not any(kw in raw_text for kw in app_keywords)


def _needs_digital_marketing(website: str, soup, raw_text) -> bool:
    """No visible social media presence linked from the website."""
    if not raw_text:
        return True
    social_keywords = [
        "facebook.com", "instagram.com", "linkedin.com",
        "twitter.com", "x.com", "youtube.com", "t.me",
        "wa.me", "whatsapp"
    ]
    return not any(kw in raw_text for kw in social_keywords)


def _needs_ssl(website: str, soup, raw_text, is_https) -> bool:
    """Website is served over HTTP (not HTTPS)."""
    if not website or website.strip() == "":
        return False  # no website, already flagged by web dev
    if is_https is None:
        # Could not reach site – check URL string directly
        return website.strip().startswith("http://")
    return not is_https


def _needs_ai_chatbot_crm(website: str, soup, raw_text) -> bool:
    """No live chat, chatbot, or CRM integration detected."""
    if not raw_text:
        return True
    chat_keywords = [
        "livechat", "live chat", "tawk.to", "tawkto", "intercom",
        "freshchat", "zendesk", "hubspot", "chatbot", "chat with us",
        "whatsapp chat", "crisp", "drift", "tidio", "helpscout"
    ]
    return not any(kw in raw_text for kw in chat_keywords)


def _needs_crm_hrm_software(website: str, soup, raw_text) -> bool:
    """No CRM / HRM / ERP system mentions found on the website."""
    if not raw_text:
        return False  # don't over-flag when unreachable
    crm_keywords = [
        "crm", "hrm", "erp", "payroll", "employee portal",
        "attendance", "leave management", "zoho", "salesforce",
        "freshdesk", "odoo", "tally"
    ]
    return not any(kw in raw_text for kw in crm_keywords)


def _needs_cloud_services(website: str, soup, raw_text) -> bool:
    """No cloud infrastructure or hosting mentions detected."""
    if not raw_text:
        return False
    cloud_keywords = [
        "aws", "amazon web services", "azure", "google cloud",
        "gcp", "cloud hosting", "cloudflare", "digitalocean",
        "heroku", "vercel", "netlify", "cloud storage", "s3 bucket"
    ]
    return not any(kw in raw_text for kw in cloud_keywords)


def _needs_analytics(website: str, soup, raw_text) -> bool:
    """No analytics or tracking scripts found."""
    if not raw_text:
        return True
    analytics_keywords = [
        "google-analytics", "googletagmanager", "gtag(", "ga(",
        "facebook pixel", "fbq(", "hotjar", "mixpanel", "clarity",
        "segment.com", "matomo", "piwik", "heap.io"
    ]
    return not any(kw in raw_text for kw in analytics_keywords)


def _needs_ecommerce(website: str, soup, raw_text) -> bool:
    """No e-commerce features detected."""
    if not raw_text:
        return False
    ecom_keywords = [
        "add to cart", "buy now", "shop now", "checkout",
        "woocommerce", "shopify", "razorpay", "payment gateway",
        "place order", "my cart", "shopping cart", "stripe", "paytm",
        "instamojo", "cashfree"
    ]
    return not any(kw in raw_text for kw in ecom_keywords)


# ---------------------------------------------------------------------------
# Service registry: (name, weight, detector_function_reference)
# Total max possible weight if ALL triggered = 20+18+15+15+12+12+10+10+8+10 = 130
# We normalize to 100 after scoring.
# ---------------------------------------------------------------------------
# Note: _needs_ssl and _needs_web_development need special args → handled inline

SERVICE_REGISTRY = [
    # (service_name, weight, detector)
    ("Web Development",       20, _needs_web_development),
    ("Website Revamp",        18, _needs_website_revamp),
    ("Mobile App Development",15, _needs_mobile_app),
    ("Digital Marketing",     15, _needs_digital_marketing),
    ("SSL / Security",        12, None),   # handled separately (needs is_https)
    ("AI Chatbot / CRM",      12, _needs_ai_chatbot_crm),
    ("CRM / HRM Software",    10, _needs_crm_hrm_software),
    ("Cloud Services",        10, _needs_cloud_services),
    ("Analytics Integration",  8, _needs_analytics),
    ("E-Commerce Development", 10, _needs_ecommerce),
]

MAX_POSSIBLE_WEIGHT = sum(w for _, w, _ in SERVICE_REGISTRY)  # 130


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def analyze_website(website: str, soup=None, raw_text=None, is_https=None):
    """
    Analyze a lead's website and return service recommendations.

    Parameters
    ----------
    website : str
        The website URL of the lead (may be empty string).

    Returns
    -------
    dict with keys:
        - "Recommended Services"    : str  (comma-separated)
        - "Service Opportunity Score": int  (0-100)
        - "Priority"                : str  ("High" / "Medium" / "Low")
        - "Analysis Status"         : str  ("Success" / "No Website" / "Failed")
    """

    # ── Case 1: No website ──────────────────────────────────────────────────
    if not website or website.strip() == "":
        return {
            "Recommended Services": "Web Development, Mobile App Development, Digital Marketing, AI Chatbot / CRM",
            "Service Opportunity Score": 85,
            "Priority": "High",
            "Analysis Status": "No Website",
        }

    # ── Case 2: Fetch website (only if not already pre-fetched) ─────────────
    if soup is None and raw_text is None:
        soup, raw_text, is_https = fetch_html(website.strip())
    fetch_failed = soup is None

    # ── Run all detectors ───────────────────────────────────────────────────
    found_services = []
    total_weight = 0

    for service_name, weight, detector in SERVICE_REGISTRY:
        triggered = False

        if service_name == "Web Development":
            triggered = _needs_web_development(website, soup, raw_text)
        elif service_name == "SSL / Security":
            triggered = _needs_ssl(website, soup, raw_text, is_https)
        elif detector is not None:
            if fetch_failed:
                # If we couldn't reach the site, skip detectors that need HTML
                # but keep a few that can be inferred from the URL/data
                if service_name in ("Mobile App Development", "Digital Marketing",
                                     "Analytics Integration"):
                    triggered = True  # conservative: assume gap
                else:
                    triggered = False
            else:
                triggered = detector(website, soup, raw_text)

        if triggered:
            found_services.append(service_name)
            total_weight += weight

    # ── Normalize score to 0-100 ────────────────────────────────────────────
    raw_score = round((total_weight / MAX_POSSIBLE_WEIGHT) * 100)
    score = min(raw_score, 100)

    # ── Determine priority ──────────────────────────────────────────────────
    if score >= 60:
        priority = "High"
    elif score >= 30:
        priority = "Medium"
    else:
        priority = "Low"

    # ── Handle fetch failure gracefully ────────────────────────────────────
    status = "Failed" if fetch_failed else "Success"
    if fetch_failed and not found_services:
        # Could not reach site at all → flag basic services as potential
        found_services = ["Website Revamp", "Mobile App Development", "Digital Marketing"]
        score = 35
        priority = "Medium"

    return {
        "Recommended Services": ", ".join(found_services) if found_services else "None Identified",
        "Service Opportunity Score": score,
        "Priority": priority,
        "Analysis Status": status,
    }
