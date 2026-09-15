"""
website_analyzer.py
--------------------
Score interpreter: converts PSI website_health data (from psi_analyzer.py)
into Lead Score, Priority, and Recommended Services.

Lead Score is calculated by summing the weight of each detected issue.
This makes the score fully transparent — it directly reflects the issues
shown in the 'Performance Issues', 'SEO Issues', 'Best Practices Issues' columns.

Priority thresholds:
    Highest  → no website / unreachable           (fixed score: 100)
    High     → score ≥ 60
    Medium   → score ≥ 30
    Low      → score < 30
"""

# ── Issue weights ─────────────────────────────────────────────────────────────
# Each key is the exact human-readable label produced by psi_analyzer.py.
# Weight reflects how serious the issue is as a service opportunity for Detagenix.
# Total max possible score if ALL issues detected ≈ 100.

ISSUE_WEIGHTS: dict[str, int] = {
    # ── Best Practices (most critical for trust & security) ──────────────────
    "Not using HTTPS (SSL missing)":          12,
    "Outdated/vulnerable JS libraries":        6,
    "Browser console errors":                  5,
    "Missing DOCTYPE declaration":             2,
    "Auto geolocation request on load":        1,
    "Auto notification request on load":       1,
    "Missing charset declaration":             1,
    "Incorrect image aspect ratios":           1,
    "Paste blocked on password fields":        0,

    # ── SEO (critical for search visibility) ─────────────────────────────────
    "Page blocked from crawling":             10,
    "Missing page title":                      8,
    "Missing meta description":                8,
    "Not mobile-friendly":                     6,
    "Uncrawlable links":                       5,
    "Missing canonical tag":                   4,
    "Missing image alt text":                  3,
    "Poor link text":                          2,
    "No structured data":                      2,
    "Missing language tags":                   1,

    # ── Performance ───────────────────────────────────────────────────────────
    "Slow server response":                    8,
    "Slow main content load (LCP)":            7,
    "Page response delay (TBT)":               6,
    "Render-blocking code":                    6,
    "Slow page load":                          5,
    "No text compression":                     4,
    "Slow time to interactive":                4,
    "Unoptimized images":                      3,
    "Unused JavaScript":                       2,
    "Non-responsive images":                   1,
    "Unused CSS":                              1,
}

# Issue flag → Detagenix service (for Recommended Services column)
_ISSUE_SERVICE: dict[str, str] = {
    "no_https":                  "Security (SSL / HTTPS)",
    "site_unreachable":          "Security (SSL / HTTPS)",
    "Not using HTTPS (SSL missing)": "Security (SSL / HTTPS)",
    "not_mobile_friendly":       "Mobile Accessibility",
    "Not mobile-friendly":       "Mobile Accessibility",
    "slow_lcp":                  "UI / UX",
    "Slow main content load (LCP)": "UI / UX",
    "render_blocking_resources": "UI / UX",
    "Render-blocking code":      "UI / UX",
    "unoptimized_images":        "UI / UX",
    "Unoptimized images":        "UI / UX",
    "Slow page load":            "UI / UX",
    "Slow server response":      "UI / UX",
    "Page response delay (TBT)": "UI / UX",
    "No text compression":       "UI / UX",
    "Unused JavaScript":         "UI / UX",
    "Non-responsive images":     "Mobile Accessibility",
    "missing_meta_description":  "SEO Structure",
    "Missing meta description":  "SEO Structure",
    "missing_title":             "SEO Structure",
    "Missing page title":        "SEO Structure",
    "Uncrawlable links":         "SEO Structure",
    "Missing canonical tag":     "SEO Structure",
    "Missing image alt text":    "SEO Structure",
    "Poor link text":            "SEO Structure",
    "No structured data":        "SEO Structure",
    "Page blocked from crawling": "SEO Structure",
    "Outdated/vulnerable JS libraries": "Security (SSL / HTTPS)",
    "Browser console errors":    "Security (SSL / HTTPS)",
}


def _parse_issue_list(issues_str: str) -> list[str]:
    """Split a comma-separated issue string into individual issue labels."""
    if not issues_str or issues_str.startswith("N/A"):
        return []
    return [s.strip() for s in issues_str.split(",") if s.strip()]


def _score_from_issues(
    perf_issues: str,
    seo_issues: str,
    bp_issues: str,
) -> int:
    """
    Sum the weights of all detected issues to produce a Lead Score (0-100).
    Each issue label maps to a fixed point value in ISSUE_WEIGHTS.
    """
    all_issues = (
        _parse_issue_list(perf_issues)
        + _parse_issue_list(seo_issues)
        + _parse_issue_list(bp_issues)
    )
    total = sum(ISSUE_WEIGHTS.get(issue, 0) for issue in all_issues)
    return min(total, 100)


def _build_recommended_services(
    perf_issues: str,
    seo_issues: str,
    bp_issues: str,
    internal_flags: list,
) -> str:
    """
    Map detected issues to Detagenix service names.
    Combines human-readable issue labels + internal snake_case flags.
    """
    services: set[str] = set()

    all_labels = (
        _parse_issue_list(perf_issues)
        + _parse_issue_list(seo_issues)
        + _parse_issue_list(bp_issues)
    )
    for label in all_labels:
        svc = _ISSUE_SERVICE.get(label)
        if svc:
            services.add(svc)

    for flag in internal_flags:
        svc = _ISSUE_SERVICE.get(flag)
        if svc:
            services.add(svc)

    return ", ".join(sorted(services)) if services else "None Identified"


# ── Main scoring function ────────────────────────────────────────────────────

def score_from_health(health: dict) -> dict:
    """
    Interpret a website_health dict and return scoring fields.

    Parameters
    ----------
    health : dict
        Output from psi_analyzer. Keys include:
            performance_issues    (str, comma-separated labels)
            seo_issues            (str, comma-separated labels)
            best_practices_issues (str, comma-separated labels)
            issues                (list of internal flags)
            status                (str)

    Returns
    -------
    dict with: Lead Score (int), Priority (str), Recommended Services (str)
    """
    status = health.get("status", "")

    # ── No website or unreachable ────────────────────────────────────────────
    if status in ("site_unreachable", "no_website"):
        return {
            "Lead Score":           100,
            "Priority":             "Highest",
            "Recommended Services": (
                "Security (SSL / HTTPS), SEO Structure, "
                "Mobile Accessibility, UI / UX"
            ),
        }

    # ── PSI call failed — use conservative fallback ──────────────────────────
    if status == "psi_error":
        return {
            "Lead Score":           60,
            "Priority":             "High",
            "Recommended Services": "SEO Structure, Mobile Accessibility, UI / UX",
        }

    # ── Normal case: score based on detected issues ──────────────────────────
    perf_issues = health.get("performance_issues", "")
    seo_issues  = health.get("seo_issues", "")
    bp_issues   = health.get("best_practices_issues", "")
    flags       = health.get("issues", [])

    lead_score = _score_from_issues(perf_issues, seo_issues, bp_issues)

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
        "Recommended Services": _build_recommended_services(
            perf_issues, seo_issues, bp_issues, flags
        ),
    }


def no_website_result() -> dict:
    """Scoring result for a lead with no website URL."""
    return {
        "Lead Score":           100,
        "Priority":             "Highest",
        "Recommended Services": (
            "Security (SSL / HTTPS), SEO Structure, "
            "Mobile Accessibility, UI / UX"
        ),
    }
