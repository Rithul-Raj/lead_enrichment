"""
serpapi_service.py
------------------
Orchestrates two-phase lead generation:

  Phase 1 — _fetch_places()
      Collect raw business data from Google Maps via SerpAPI.

  Phase 2 — PSI batch analysis
      Send all lead websites to psi_analyzer.run_batch() in one async call.
      Domain dedup, caching, retry logic are all handled inside psi_analyzer.

  Phase 3 — _build_lead()
      Interpret each lead's PSI health dict into Lead Score, Priority, and
      Recommended Services via website_analyzer.score_from_health().
"""

from serpapi import GoogleSearch
from config import SERPAPI_KEY, PSI_API_KEY
from .psi_analyzer import run_batch, get_domain
from .website_analyzer import score_from_health, no_website_result


# ── Phase 1: Fetch places from SerpAPI ──────────────────────────────────────

def _fetch_places(location: str, industry: str, num_leads: int) -> list[dict]:
    """Collect raw place records from Google Maps via SerpAPI."""
    places = []
    start  = 0

    while len(places) < num_leads:
        params = {
            "engine":  "google_maps",
            "q":       f"{industry} in {location}",
            "hl":      "en",
            "start":   start,
            "api_key": SERPAPI_KEY,
        }
        results = GoogleSearch(params).get_dict()
        local   = results.get("local_results", [])
        if not local:
            break

        for place in local:
            places.append(place)
            if len(places) >= num_leads:
                break

        start += 20

    return places[:num_leads]


# ── Phase 2+3: Analyze + build lead dicts ───────────────────────────────────

def _build_lead(place: dict, industry: str, health: dict) -> dict:
    """
    Merge SerpAPI place data with PSI health into a final lead dict.
    Numeric PSI scores are used only for Lead Score calculation (internal).
    CSV columns show human-readable problem descriptions instead of numbers.
    """
    website = place.get("website", "").strip()
    scoring = score_from_health(health)

    return {
        "Lead Name":              place.get("title", ""),
        "Website":                website,
        "Website Available":      "Yes" if website else "No",
        "Phone":                  place.get("phone", ""),
        "Lead Score":             scoring["Lead Score"],
        "Priority":               scoring["Priority"],
        "Source":                 "SerpAPI",
        "Location":               place.get("address", ""),
        "Industry":               industry,
        "Recommended Services":   scoring["Recommended Services"],
        "Performance Issues":     health.get("performance_issues", ""),
        "SEO Issues":             health.get("seo_issues", ""),
        "Best Practices Issues":  health.get("best_practices_issues", ""),
    }


def search_businesses(location: str, industry: str, num_leads: int) -> list[dict]:
    """
    Full pipeline: SerpAPI fetch → PSI batch analysis → scored lead list.

    Returns
    -------
    List of lead dicts ready for deduplication and CSV export.
    """

    # ── Phase 1: Fetch all places ────────────────────────────────────────────
    print("  Fetching leads from Google Maps...", flush=True)
    places = _fetch_places(location, industry, num_leads)

    if not places:
        return []

    print(f"  Found {len(places)} leads.", flush=True)

    # ── Phase 2: Build domain map (deduplicate) ──────────────────────────────
    urls_by_domain: dict[str, str] = {}
    for place in places:
        url = place.get("website", "").strip()
        if url:
            domain = get_domain(url)
            if domain and domain not in urls_by_domain:
                urls_by_domain[domain] = url

    # ── Phase 3: PSI batch analysis (async, all domains at once) ────────────
    if urls_by_domain:
        print(
            f"  Analysing {len(urls_by_domain)} unique website(s) via "
            f"PageSpeed Insights...\n",
            flush=True,
        )
        health_map = run_batch(urls_by_domain, api_key=PSI_API_KEY)
    else:
        health_map = {}

    # ── Phase 4: Build final lead dicts ─────────────────────────────────────
    leads = []
    for i, place in enumerate(places):
        url    = place.get("website", "").strip()
        domain = get_domain(url) if url else None

        if not url:
            # No website at all — no PSI call needed
            scoring = no_website_result()
            health  = {"status": "no_website"}
            lead    = {
                "Lead Name":             place.get("title", ""),
                "Website":               "",
                "Website Available":     "No",
                "Phone":                 place.get("phone", ""),
                "Lead Score":            scoring["Lead Score"],
                "Priority":              scoring["Priority"],
                "Source":                "SerpAPI",
                "Location":              place.get("address", ""),
                "Industry":              industry,
                "Recommended Services":  scoring["Recommended Services"],
                "Performance Issues":    "N/A (no website)",
                "SEO Issues":            "N/A (no website)",
                "Best Practices Issues": "N/A (no website)",
            }
        else:
            health = health_map.get(domain, {"status": "psi_error", "issues": []})
            lead   = _build_lead(place, industry, health)

        leads.append(lead)
        status     = health.get("status", "?")
        perf_iss   = health.get("performance_issues", "")
        seo_iss    = health.get("seo_issues", "")
        bp_iss     = health.get("best_practices_issues", "")
        issue_note = f"{len(perf_iss.split(',')) if perf_iss else 0} perf, " \
                     f"{len(seo_iss.split(',')) if seo_iss else 0} seo, " \
                     f"{len(bp_iss.split(',')) if bp_iss else 0} bp issues"
        print(
            f"  [{i+1}/{len(places)}] {lead['Lead Name']} "
            f"→ Priority: {lead['Priority']}  ({issue_note})  [{status}]",
            flush=True,
        )

    return leads
