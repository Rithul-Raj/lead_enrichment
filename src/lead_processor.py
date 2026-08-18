"""
lead_processor.py
-----------------
Parallel processing engine.

Phase 1 (parallel, ThreadPoolExecutor):
    - Fetch website HTML once per lead
    - Run website analysis (service gaps, priority, score)
    - Extract email and social media link

Phase 2 (sequential, batched):
    - Send website text to Gemini in batches of 5
    - Extract founder / CEO names
    - Rate-limited to stay within Gemini free-tier (15 RPM)
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .website_analyzer import fetch_html, analyze_website
from .enrichment_service import (
    enrich_lead_html,
    get_page_text,
    extract_details_batch,
)

_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Phase 1 worker — runs in parallel
# ---------------------------------------------------------------------------

def _process_one(lead: dict, counter: list, lock: threading.Lock, total: int) -> dict:
    """
    For a single lead:
      1. Fetch website (once)
      2. Analyze (service gaps, priority, score)
      3. Extract email + social media
      4. Store page text for Gemini batch (Phase 2)
    """
    website = lead.get("Website", "")
    rating  = float(lead.get("Rating", 0) or 0)

    # ── Single fetch ───────────────────────────────────────────────────────
    if website:
        soup, raw_text, is_https = fetch_html(website)
    else:
        soup, raw_text, is_https = None, None, None

    # ── Website analysis (uses pre-fetched HTML) ───────────────────────────
    analysis = analyze_website(website, soup=soup, raw_text=raw_text, is_https=is_https)

    # ── Email + social (from same soup, also tries contact page) ──────────
    enrichment = enrich_lead_html(website, soup)

    # ── Blended lead score ─────────────────────────────────────────────────
    rating_part = round((rating / 5) * 50)
    opp_part    = round(analysis["Service Opportunity Score"] / 2)
    lead_score  = min(rating_part + opp_part, 100)

    # ── Update lead dict ───────────────────────────────────────────────────
    lead.update({
        "Lead Score":                lead_score,
        "Priority":                  analysis["Priority"],
        "Website Available":         "Yes" if website else "No",
        "Recommended Services":      analysis["Recommended Services"],
        "Service Opportunity Score": analysis["Service Opportunity Score"],
        "Email":                     enrichment["Email"],
        "Social Media":              enrichment["Social Media"],
        "Founder Name":              "__PENDING__",       # filled in Phase 2
        "_page_text":                get_page_text(soup), # temp, removed after Phase 2
    })

    # ── Thread-safe progress print ─────────────────────────────────────────
    with lock:
        counter[0] += 1
        n = counter[0]
    status = analysis["Analysis Status"]
    with _print_lock:
        print(f"  [{n}/{total}] {lead.get('Lead Name', 'Unknown')} ({status})", flush=True)

    return lead


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def process_leads_parallel(raw_leads: list, max_workers: int = 10) -> list:
    """
    Process all leads in two phases:
      Phase 1 – parallel fetch + analysis + email/social
      Phase 2 – batched Gemini for founder names

    Parameters
    ----------
    raw_leads   : list of raw lead dicts from SerpAPI
    max_workers : number of parallel threads (default 10)

    Returns
    -------
    list of fully enriched lead dicts
    """
    total   = len(raw_leads)
    results = [None] * total
    counter = [0]           # mutable for thread-safe counting
    lock    = threading.Lock()

    # ── Phase 1: Parallel website fetch + analysis + email/social ──────────
    print(f"  Fetching & analysing {total} leads with {max_workers} parallel workers...\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_process_one, lead, counter, lock, total): i
            for i, lead in enumerate(raw_leads)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                # Keep raw lead with safe defaults on unexpected error
                lead = raw_leads[idx]
                lead.update({
                    "Lead Score": 0, "Priority": "Low",
                    "Recommended Services": "Analysis Failed",
                    "Service Opportunity Score": 0,
                    "Email": "Not Found", "Social Media": "Not Found",
                    "Founder Name": "Not Found", "_page_text": "",
                })
                results[idx] = lead

    # ── Phase 2: Batched Gemini for founder name + email fallback ─────────
    print(f"\n  Extracting founder names & filling missing emails via Gemini...", flush=True)

    valid_results = [r for r in results if r is not None]
    leads_data    = [
        (
            r.get("Lead Name", ""),
            r.get("_page_text", ""),
            r.get("Email", "Not Found"),
            r.get("Social Media", "Not Found"),
        )
        for r in valid_results
    ]

    details = extract_details_batch(leads_data)

    for i, lead in enumerate(valid_results):
        if i < len(details):
            founder, email_final, social_final = details[i]
            lead["Founder Name"] = founder
            if lead.get("Email", "Not Found") == "Not Found" and email_final != "Not Found":
                lead["Email"] = email_final
            if lead.get("Social Media", "Not Found") == "Not Found" and social_final != "Not Found":
                lead["Social Media"] = social_final
        else:
            lead["Founder Name"] = "Not Found"
        lead.pop("_page_text", None)

    print(f"  Done.\n", flush=True)
    return valid_results
