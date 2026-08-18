from .serpapi_service import search_businesses
from .lead_processor import process_leads_parallel


def search_leads(location: str, industry: str, num_leads: int) -> list:
    """Fetch leads from SerpAPI then enrich them in parallel."""
    raw_leads = search_businesses(location, industry, num_leads)
    if not raw_leads:
        return []
    return process_leads_parallel(raw_leads)
