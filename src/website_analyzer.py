"""
website_analyzer.py
--------------------
Score interpreter: converts a PSI `website_health` dict (produced by
psi_analyzer.py) into Lead Score (0-100), Priority, and Recommended Services.

No HTTP calls are made here — all network work is done by psi_analyzer.py.

Lead Score formula (inverse PSI — lower PSI score = more opportunity):
    Lead Score = (100-perf)×0.35 + (100-seo)×0.40 + (100-bp)×0.25

Priority thresholds:
    Highest  → no website / unreachable
    High     → score ≥ 60
    Medium   → score ≥ 30
    Low      → score < 30

Recommended Services come from Lighthouse issue flags + overall score bands.
"""

# ── Issue flag → Detagenix service mapping ───────────────────────────────────
_ISSUE_SERVICE: dict[str, str] = {
    "no_https":                  "Security (SSL / HTTPS)",
    "site_unreachable":          "Security (SSL / HTTPS)",
    "not_mobile_friendly":       "Mobile Accessibility",
    "slow_lcp":                  "UI / UX",
    "render_blocking_resources": "UI / UX",
    "unoptimized_images":        "UI / UX",
    "missing_meta_description":  "SEO Structure",
    "missing_title":             "SEO Structure",
}

# Score bands that trigger a service even without a specific audit flag
_PERF_THRESHOLD = 50   # performance < 50  → UI / UX
_SEO_THRESHOLD  = 60   # seo         < 60  → SEO Structure
_BP_THRESHOLD   = 60   # best-practices < 60 → Security (SSL / HTTPS)


def _issues_to_services(issues: list, health: dict) -> str:
    services: set[str] = set()

    # Map specific audit flags
    for issue in issues:
        svc = _ISSUE_SERVICE.get(issue)
        if svc:
            services.add(svc)

    # Map overall score bands
    perf = health.get("performance_score")
    seo  = health.get("seo_score")
    bp   = health.get("best_practices_score")

    if perf is not None and perf < _PERF_THRESHOLD:
        services.add("UI / UX")
    if seo is not None and seo < _SEO_THRESHOLD:
        services.add("SEO Structure")
    if bp is not None and bp < _BP_THRESHOLD:
        services.add("Security (SSL / HTTPS)")

    return ", ".join(sorted(services)) if services else "None Identified"


def score_from_health(health: dict) -> dict:
    """
    Interpret a website_health dict and return scoring fields.

    Parameters
    ----------
    health : dict
        Output from psi_analyzer._analyze_domain / run_batch.
        Keys: performance_score, seo_score, best_practices_score,
              issues (list), status.

    Returns
    -------
    dict with:
        Lead Score          (int 0-100)
        Priority            (str)
        Recommended Services(str, comma-separated)
    """
    status = health.get("status", "")
    issues = health.get("issues", [])

    # ── No website or completely unreachable ─────────────────────────────────
    if status in ("site_unreachable", "no_website"):
        return {
            "Lead Score":           100,
            "Priority":             "Highest",
            "Recommended Services": (
                "Security (SSL / HTTPS), SEO Structure, "
                "Mobile Accessibility, UI / UX"
            ),
        }

    perf = health.get("performance_score")
    seo  = health.get("seo_score")
    bp   = health.get("best_practices_score")

    # ── PSI call failed after retries — use conservative fallback ────────────
    if status == "psi_error" or (perf is None and seo is None and bp is None):
        return {
            "Lead Score":           65,
            "Priority":             "High",
            "Recommended Services": "SEO Structure, Mobile Accessibility, UI / UX",
        }

    # ── Normal case: compute opportunity score from inverse PSI ──────────────
    # Use 50 as neutral if a category is unexpectedly None
    p = perf if perf is not None else 50
    s = seo  if seo  is not None else 50
    b = bp   if bp   is not None else 50

    lead_score = round((100 - p) * 0.35 + (100 - s) * 0.40 + (100 - b) * 0.25)
    lead_score = max(0, min(lead_score, 100))

    # ── Priority ──────────────────────────────────────────────────────────────
    if lead_score >= 60:
        priority = "High"
    elif lead_score >= 30:
        priority = "Medium"
    else:
        priority = "Low"

    return {
        "Lead Score":           lead_score,
        "Priority":             priority,
        "Recommended Services": _issues_to_services(issues, health),
    }


def no_website_result() -> dict:
    """Scoring result for a lead that has no website URL at all."""
    return {
        "Lead Score":           100,
        "Priority":             "Highest",
        "Recommended Services": (
            "Security (SSL / HTTPS), SEO Structure, "
            "Mobile Accessibility, UI / UX"
        ),
        "PSI Performance":    "",
        "PSI SEO":            "",
        "PSI Best Practices": "",
        "PSI Issues":         "no_website",
    }
