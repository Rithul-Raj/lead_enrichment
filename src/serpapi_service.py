"""
serpapi_service.py
------------------
Fetches raw lead data from Google Maps via SerpAPI.
Website analysis and enrichment are handled separately
by lead_processor.py (parallel).
"""

from serpapi import GoogleSearch
from config import SERPAPI_KEY


def search_businesses(location: str, industry: str, num_leads: int) -> list:
    """Return raw lead dicts (no analysis — just SerpAPI fields)."""
    leads = []
    start = 0

    while len(leads) < num_leads:
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
            website = place.get("website", "")
            leads.append({
                "Lead Name": place.get("title", ""),
                "Website":   website,
                "Phone":     place.get("phone", ""),
                "Rating":    float(place.get("rating", 0) or 0),
                "Source":    "SerpAPI",
                "Location":  place.get("address", ""),
                "Industry":  industry,
            })
            if len(leads) >= num_leads:
                break

        start += 20

    return leads[:num_leads]
