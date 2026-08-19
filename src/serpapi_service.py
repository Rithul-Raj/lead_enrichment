from serpapi import GoogleSearch
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import SERPAPI_KEY
from .website_analyzer import analyze_website


def _fetch_places(location, industry, num_leads):
    """Step 1: Collect raw place data from SerpAPI only (no website analysis)."""
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


def _analyse_one(args):
    """Step 2 (parallel): Analyze a single website and return the merged lead dict."""
    idx, place, industry = args
    website = place.get("website", "")

    analysis = analyze_website(website)

    return idx, {
        "Lead Name":            place.get("title", ""),
        "Website":              website,
        "Website Available":    "Yes" if website else "No",
        "Phone":                place.get("phone", ""),
        "Lead Score":           analysis["Service Opportunity Score"],
        "Priority":             analysis["Priority"],
        "Source":               "SerpAPI",
        "Location":             place.get("address", ""),
        "Industry":             industry,
        "Recommended Services": analysis["Recommended Services"],
        "_status":              analysis["Analysis Status"],
    }


def search_businesses(location, industry, num_leads, max_workers=5):
    """
    Fetch leads from SerpAPI then analyse all websites in parallel.

    Parameters
    ----------
    max_workers : int
        Number of parallel threads for website analysis.
        Default = 5 (good balance of speed vs. server load).
        Increase to 10 for even faster results.
    """

    # ── Step 1: Collect all place data (fast) ───────────────────────────────
    print("  Fetching leads from Google Maps...", flush=True)
    places = _fetch_places(location, industry, num_leads)

    if not places:
        return []

    print(f"  Found {len(places)} leads. Analysing websites in parallel...\n", flush=True)

    # ── Step 2: Analyse all websites in parallel ─────────────────────────────
    args_list = [(i, place, industry) for i, place in enumerate(places)]
    results   = [None] * len(places)   # preserve order

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyse_one, args): args[0] for args in args_list}

        completed = 0
        for future in as_completed(futures):
            idx, lead = future.result()
            status    = lead.pop("_status")          # internal field, remove before saving
            results[idx] = lead
            completed += 1
            print(
                f"  [{completed}/{len(places)}] {lead['Lead Name']} "
                f"→ Priority: {lead['Priority']}  ({status})",
                flush=True,
            )

    # Filter out any None slots (shouldn't happen, safety check)
    return [r for r in results if r is not None]


def search_leads_parallel(location, industry, num_leads, max_workers=5):
    """Public alias used by lead_search_engine."""
    return search_businesses(location, industry, num_leads, max_workers)
