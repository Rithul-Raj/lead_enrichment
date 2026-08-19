"""
website_analyzer.py
-------------------
Analyzes a lead's website to detect gaps and map them to
Detagenix's specific service offerings.

Services (in priority order):
    1. Security (SSL / HTTPS)   — weight 25
    2. SEO Structure            — weight 22
    3. Mobile Accessibility     — weight 20
    4. UI / UX                  — weight 18
    5. Broken / Dead Links      — weight 10
    6. Content Freshness        — weight  5
    Total max = 100

Returns:
    - Recommended Services      : comma-separated string
    - Service Opportunity Score : int 0–100
    - Priority                  : "Highest" | "High" | "Medium" | "Low"
    - Analysis Status           : "No Website" | "Success" | "Failed"
"""

import re
import requests
from bs4 import BeautifulSoup

# ── Request config ──────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 5   # seconds per page fetch  (reduced for parallel speed)
LINK_TIMEOUT    = 2   # seconds per broken-link check (reduced for parallel speed)


# ── HTML fetcher ────────────────────────────────────────────────────────────

def _fetch(url: str):
    """
    Fetch a URL and return (soup, raw_html_lowercase, final_url, is_https).
    Returns (None, None, None, None) on any failure.
    """
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
        )
        resp.raise_for_status()
        soup      = BeautifulSoup(resp.text, "lxml")
        raw_lower = resp.text.lower()
        final_url = resp.url
        is_https  = final_url.startswith("https://")
        return soup, raw_lower, final_url, is_https
    except Exception:
        return None, None, None, None


# ════════════════════════════════════════════════════════════════════════════
# Individual detectors — each returns True if the gap/issue EXISTS
# (i.e., the service IS needed)
# ════════════════════════════════════════════════════════════════════════════

# ── 1. Security (SSL / HTTPS) ── weight 25 ──────────────────────────────────
def _check_ssl(url: str, is_https) -> bool:
    """True if site is NOT served over HTTPS."""
    if is_https is None:
        # Could not reach site — infer from URL string
        return url.strip().lower().startswith("http://")
    return not is_https


# ── 2. SEO Structure ── weight 22 ───────────────────────────────────────────
def _check_seo(soup) -> bool:
    """
    True if the site has poor SEO structure:
      - Missing <title> or title is blank/very short
      - Missing meta description
      - Missing <h1> tag, or multiple <h1> tags (bad practice)
      - No canonical link tag
    Two or more of the above → flag as needing SEO work.
    """
    if soup is None:
        return True  # can't verify → assume gap

    issues = 0

    # Title check
    title_tag = soup.find("title")
    if not title_tag or len((title_tag.string or "").strip()) < 10:
        issues += 1

    # Meta description check
    meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not meta_desc or not meta_desc.get("content", "").strip():
        issues += 1

    # H1 check
    h1_tags = soup.find_all("h1")
    if len(h1_tags) != 1:          # 0 or 2+ h1 tags = bad SEO
        issues += 1

    # Canonical check
    canonical = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
    if not canonical:
        issues += 1

    return issues >= 2             # flag only if 2+ issues found


# ── 3. Mobile Accessibility ── weight 20 ────────────────────────────────────
def _check_mobile(soup, raw_lower: str) -> bool:
    """
    True if the site is NOT mobile-friendly:
      - No <meta name="viewport"> tag
      - No responsive framework hint (bootstrap, tailwind, foundation, etc.)
      - No CSS @media queries referenced
    """
    if soup is None:
        return True

    has_viewport = bool(
        soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    )
    if not has_viewport:
        return True  # definitive sign of non-responsive site

    # Secondary check: responsive framework or media query keywords
    responsive_hints = [
        "bootstrap", "tailwind", "foundation", "bulma",
        "@media", "media query", "responsive"
    ]
    has_responsive = any(h in raw_lower for h in responsive_hints)
    return not has_responsive


# ── 4. UI / UX ── weight 18 ─────────────────────────────────────────────────
def _check_uiux(soup, raw_lower: str) -> bool:
    """
    True if the site uses an old/poor tech stack or outdated UI:
      - Deprecated HTML tags: <font>, <center>, <marquee>, <blink>
      - Layout tables (table used for page layout, not data)
      - Inline style overuse (>10 inline style attributes)
      - No modern JS framework hint
      - Very old jQuery version
    Two or more signals → flag as needing UI/UX work.
    """
    if soup is None:
        return False   # can't analyse — don't over-flag

    issues = 0

    # Deprecated tags
    deprecated = ["font", "center", "marquee", "blink"]
    if any(soup.find(tag) for tag in deprecated):
        issues += 1

    # Layout tables (heuristic: <table> without <th> or summary)
    tables = soup.find_all("table")
    layout_tables = [t for t in tables if not t.find("th")]
    if len(layout_tables) >= 2:
        issues += 1

    # Excessive inline styles
    inline_styles = soup.find_all(style=True)
    if len(inline_styles) > 15:
        issues += 1

    # Old jQuery (1.x, 2.x)
    old_jquery = re.search(r'jquery[.-]([12])\.\d', raw_lower)
    if old_jquery:
        issues += 1

    return issues >= 2


# ── 5. Broken / Dead Links ── weight 10 ─────────────────────────────────────
def _check_broken_links(soup, base_url: str) -> bool:
    """
    True if any internal/absolute links on the page return a 4xx error.
    Checks up to 8 links to keep runtime reasonable.
    """
    if soup is None:
        return False

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/") and not href.startswith("//"):
            # Build absolute URL from root
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
        if len(links) >= 8:
            break

    for link in links:
        try:
            r = requests.head(
                link, headers=HEADERS, timeout=LINK_TIMEOUT,
                allow_redirects=True
            )
            if r.status_code >= 400:
                return True   # at least one broken link found
        except Exception:
            pass   # network error on link — skip

    return False


# ── 6. Content Freshness ── weight 5 ────────────────────────────────────────
def _check_content_freshness(soup, raw_lower: str) -> bool:
    """
    True if the content appears stale:
      - Copyright year is 3+ years old
      - Body text is very thin (< 300 characters)
    """
    if soup is None:
        return False

    issues = 0

    # Old copyright year
    year_match = re.findall(r'©\s*(\d{4})|copyright\s*©?\s*(\d{4})', raw_lower)
    if year_match:
        years = [int(y[0] or y[1]) for y in year_match if (y[0] or y[1])]
        if years and max(years) <= 2021:
            issues += 1

    # Thin content
    body = soup.find("body")
    body_text = body.get_text(strip=True) if body else ""
    if len(body_text) < 300:
        issues += 1

    return issues >= 1


# ════════════════════════════════════════════════════════════════════════════
# Service registry  (name, weight)
# Weights are already designed to sum to 100 max.
# ════════════════════════════════════════════════════════════════════════════

SERVICE_REGISTRY = [
    ("Security (SSL / HTTPS)", 25),
    ("SEO Structure",          22),
    ("Mobile Accessibility",   20),
    ("UI / UX",                18),
    ("Broken / Dead Links",    10),
    ("Content Freshness",       5),
]


# ════════════════════════════════════════════════════════════════════════════
# Main public function
# ════════════════════════════════════════════════════════════════════════════

def analyze_website(website: str) -> dict:
    """
    Analyze a lead's website against Detagenix's 6 services.

    Parameters
    ----------
    website : str   URL of the lead's website (may be empty).

    Returns
    -------
    dict with keys:
        Recommended Services      (str)
        Service Opportunity Score (int 0-100)
        Priority                  (str: Highest / High / Medium / Low)
        Analysis Status           (str: No Website / Success / Failed)
    """

    # ── No website → Highest priority ───────────────────────────────────────
    if not website or not website.strip():
        return {
            "Recommended Services":     "Security (SSL / HTTPS), SEO Structure, "
                                        "Mobile Accessibility, UI / UX, "
                                        "Broken / Dead Links, Content Freshness",
            "Service Opportunity Score": 100,
            "Priority":                 "Highest",
            "Analysis Status":          "No Website",
        }

    # ── Fetch website ────────────────────────────────────────────────────────
    soup, raw_lower, final_url, is_https = _fetch(website.strip())
    fetch_failed = soup is None

    # ── Run detectors ────────────────────────────────────────────────────────
    found_services = []
    total_score    = 0

    for service_name, weight in SERVICE_REGISTRY:

        if fetch_failed:
            # Can only check SSL from URL string; skip HTML-dependent checks
            if service_name == "Security (SSL / HTTPS)":
                triggered = _check_ssl(website, None)
            else:
                triggered = False
        else:
            if service_name == "Security (SSL / HTTPS)":
                triggered = _check_ssl(website, is_https)
            elif service_name == "SEO Structure":
                triggered = _check_seo(soup)
            elif service_name == "Mobile Accessibility":
                triggered = _check_mobile(soup, raw_lower)
            elif service_name == "UI / UX":
                triggered = _check_uiux(soup, raw_lower)
            elif service_name == "Broken / Dead Links":
                triggered = _check_broken_links(soup, final_url)
            elif service_name == "Content Freshness":
                triggered = _check_content_freshness(soup, raw_lower)
            else:
                triggered = False

        if triggered:
            found_services.append(service_name)
            total_score += weight

    score = min(total_score, 100)

    # ── Priority thresholds ──────────────────────────────────────────────────
    if score >= 60:
        priority = "High"
    elif score >= 30:
        priority = "Medium"
    else:
        priority = "Low"

    # ── Graceful fallback if site was unreachable ────────────────────────────
    status = "Failed" if fetch_failed else "Success"
    if fetch_failed and not found_services:
        found_services = ["SEO Structure", "Mobile Accessibility", "UI / UX"]
        score    = 60
        priority = "High"

    return {
        "Recommended Services":     ", ".join(found_services) if found_services else "None Identified",
        "Service Opportunity Score": score,
        "Priority":                 priority,
        "Analysis Status":          status,
    }
