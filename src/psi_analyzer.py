"""
psi_analyzer.py
---------------
Async batch client for Google PageSpeed Insights (PSI) API.
PSI is free, hosted Lighthouse — no browser or Chrome install needed.

Responsibilities:
  - Async batch fetching via asyncio + aiohttp (bounded concurrency)
  - Domain-level deduplication  (one API call per unique domain)
  - File-based result cache      (data/psi_cache.json, 24-h TTL)
  - Cheap reachability pre-check before PSI call
  - Retry on HTTP 429 / 5xx with back-off (max 2 retries)
  - Hard per-request timeout
  - Graceful fallback — never raises, always returns a result dict

Public API
----------
    health_map = await batch(urls_by_domain, api_key)
    # Returns  {domain: website_health_dict, ...}
"""

import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

# ── Constants ────────────────────────────────────────────────────────────────
PSI_ENDPOINT   = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_CATEGORIES = ["performance", "seo", "best-practices"]
PSI_STRATEGY   = "mobile"

CONCURRENCY     = 8    # max simultaneous PSI requests (free quota safe)
REQUEST_TIMEOUT = 30   # seconds — hard PSI call timeout
REACH_TIMEOUT   = 5    # seconds — cheap HEAD check before PSI
MAX_RETRIES     = 2    # retry cap on 429/5xx

CACHE_FILE    = Path("data/psi_cache.json")
CACHE_TTL_H   = 24    # hours before a cached result is considered stale

# ── Cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_hit(cached: dict) -> bool:
    """True if cached entry is still within TTL."""
    age_h = (time.time() - cached.get("_cached_at", 0)) / 3600
    return age_h < CACHE_TTL_H


# ── Domain helper ────────────────────────────────────────────────────────────

def get_domain(url: str) -> str:
    """Extract bare domain (no www, no path) from a URL."""
    try:
        netloc = urlparse(url.strip()).netloc.lower()
        return netloc.removeprefix("www.")
    except Exception:
        return url.strip()


# ── PSI response parsers ─────────────────────────────────────────────────────

def _parse_scores(data: dict) -> dict:
    """Extract 0-100 category scores (or None if missing)."""
    cats = data.get("lighthouseResult", {}).get("categories", {})

    def score(key: str):
        raw = cats.get(key, {}).get("score")
        return round(raw * 100) if raw is not None else None

    return {
        "performance_score":    score("performance"),
        "seo_score":            score("seo"),
        "best_practices_score": score("best-practices"),
    }


def _parse_issues(data: dict) -> list[str]:
    """
    Derive a list of issue-flag strings from individual Lighthouse audits.
    Each flag is a short snake_case identifier consumed by website_analyzer.py.
    """
    audits = data.get("lighthouseResult", {}).get("audits", {})
    issues = []

    def failed(key: str) -> bool:
        return audits.get(key, {}).get("score", 1) == 0

    def slow(key: str, threshold: float = 0.5) -> bool:
        s = audits.get(key, {}).get("score")
        return s is not None and s < threshold

    if failed("is-on-https"):
        issues.append("no_https")
    if failed("viewport"):
        issues.append("not_mobile_friendly")
    if slow("largest-contentful-paint"):
        issues.append("slow_lcp")
    if failed("meta-description"):
        issues.append("missing_meta_description")
    if failed("document-title"):
        issues.append("missing_title")
    if slow("render-blocking-resources"):
        issues.append("render_blocking_resources")
    if slow("uses-optimized-images"):
        issues.append("unoptimized_images")

    return issues


# ── Fallback results ─────────────────────────────────────────────────────────

def _fallback(status: str, issues: list[str] | None = None) -> dict:
    return {
        "performance_score":    None,
        "seo_score":            None,
        "best_practices_score": None,
        "issues":               issues or [status],
        "status":               status,
    }


UNREACHABLE_FALLBACK = _fallback("site_unreachable", ["no_https", "site_unreachable"])
PSI_ERROR_FALLBACK   = _fallback("psi_error")


# ── Async helpers ────────────────────────────────────────────────────────────

async def _is_reachable(session: aiohttp.ClientSession, url: str) -> bool:
    """Cheap HEAD request to skip dead sites before calling PSI."""
    try:
        timeout = aiohttp.ClientTimeout(total=REACH_TIMEOUT)
        async with session.head(url, timeout=timeout, allow_redirects=True) as r:
            return r.status < 500
    except Exception:
        return False


async def _call_psi(
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    sem: asyncio.Semaphore,
) -> dict | None:
    """
    Call PSI API with retry + back-off.
    Returns parsed JSON dict or None on permanent failure.
    """
    # Build params — multiple 'category' values require a list of tuples
    base_params = [("url", url), ("strategy", PSI_STRATEGY)]
    if api_key:
        base_params.append(("key", api_key))
    cat_params = [("category", c) for c in PSI_CATEGORIES]
    params = base_params + cat_params

    async with sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                async with session.get(
                    PSI_ENDPOINT, params=params, timeout=timeout
                ) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        if attempt < MAX_RETRIES:
                            wait = int(
                                resp.headers.get("Retry-After", 2 ** (attempt + 1))
                            )
                            await asyncio.sleep(wait)
                            continue
                        return None
                    if resp.status != 200:
                        return None
                    return await resp.json(content_type=None)

            except (asyncio.TimeoutError, aiohttp.ClientError):
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

    return None


# ── Per-domain analysis ──────────────────────────────────────────────────────

async def _analyze_domain(
    session:  aiohttp.ClientSession,
    domain:   str,
    url:      str,
    api_key:  str,
    sem:      asyncio.Semaphore,
    cache:    dict,
) -> tuple[str, dict]:
    """
    Analyze one domain: check cache → reachability → PSI call → parse result.
    Always returns (domain, health_dict) — never raises.
    """
    # ── Cache hit ─────────────────────────────────────────────────────────
    if domain in cache and _cache_hit(cache[domain]):
        return domain, {k: v for k, v in cache[domain].items() if k != "_cached_at"}

    # ── Reachability check ────────────────────────────────────────────────
    if not await _is_reachable(session, url):
        result = UNREACHABLE_FALLBACK.copy()
        cache[domain] = {**result, "_cached_at": time.time()}
        return domain, result

    # ── PSI call ──────────────────────────────────────────────────────────
    data = await _call_psi(session, url, api_key, sem)
    if data is None:
        result = PSI_ERROR_FALLBACK.copy()
        cache[domain] = {**result, "_cached_at": time.time()}
        return domain, result

    # ── Parse scores + issues ─────────────────────────────────────────────
    result = {
        **_parse_scores(data),
        "issues": _parse_issues(data),
        "status": "success",
    }
    cache[domain] = {**result, "_cached_at": time.time()}
    return domain, result


# ── Public batch function ────────────────────────────────────────────────────

async def batch(urls_by_domain: dict[str, str], api_key: str) -> dict[str, dict]:
    """
    Analyze a batch of domains asynchronously.

    Parameters
    ----------
    urls_by_domain : {domain: url, ...}   (already deduplicated)
    api_key        : PSI API key (may be empty — works without key at low quota)

    Returns
    -------
    {domain: website_health_dict, ...}
    """
    if not urls_by_domain:
        return {}

    cache = _load_cache()
    sem   = asyncio.Semaphore(CONCURRENCY)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 4)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            _analyze_domain(session, domain, url, api_key, sem, cache)
            for domain, url in urls_by_domain.items()
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    _save_cache(cache)

    health_map: dict[str, dict] = {}
    for item in raw_results:
        if isinstance(item, Exception):
            continue
        domain, health = item
        health_map[domain] = health

    return health_map


# ── Convenience sync wrapper (called from sync code) ────────────────────────

def run_batch(urls_by_domain: dict[str, str], api_key: str = "") -> dict[str, dict]:
    """
    Synchronous wrapper around batch() for use in non-async call sites.
    Handles the asyncio.run() call safely.
    """
    if not api_key:
        api_key = os.environ.get("PSI_API_KEY", "")
    return asyncio.run(batch(urls_by_domain, api_key))
