from .serpapi_service import search_businesses

def search_leads(location, industry, num_leads):
    return search_businesses(location, industry, num_leads)
