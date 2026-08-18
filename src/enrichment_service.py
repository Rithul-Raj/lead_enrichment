"""
enrichment_service.py
---------------------
Extracts Email, Social Media, and Founder Name from website HTML.
- Email + Social Media: pure HTML scraping (fast, parallel-safe)
- Founder Name + Email fallback: Gemini API in batches of 5 leads per call
"""

import re
import time
import io
import contextlib
import warnings
import logging
from google import genai
from config import GEMINI_API_KEY

# Suppress Gemini AFC warning from warnings module
warnings.filterwarnings("ignore", message=".*AFC.*")
warnings.filterwarnings("ignore", message=".*automatic function calling.*")
logging.getLogger("google.genai").setLevel(logging.ERROR)
logging.getLogger("google.ai").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Gemini client (lazy init)
# ---------------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is None:
        key = GEMINI_API_KEY.strip() if GEMINI_API_KEY else ""
        if key and key != "your_gemini_api_key_here":
            try:
                _client = genai.Client(api_key=key)
            except Exception as e:
                print(f"  [Gemini] Client init failed: {e}", flush=True)
    return _client


# ---------------------------------------------------------------------------
# Email extraction (from HTML)
# ---------------------------------------------------------------------------
_EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE,
)

_EMAIL_EXCLUDES = {
    "example.com", "sentry.io", "w3.org", "schema.org", "google.com",
    "jquery.com", "cloudflare.com", "amazonaws.com", "wixpress.com",
    "squarespace.com", "wordpress.com", "domain.com", "yourdomain.com",
    "email.com", "test.com", "sample.com", "placeholder.com",
    # Common website template placeholder emails
    "mydomain.com", "yourcompany.com", "company.com", "website.com",
    "mail.com", "webmaster.com", "info.com", "support.com",
    "abc.com", "xyz.com", "demo.com", "temp.com",
}


def extract_email(soup) -> str:
    """Extract first valid email from HTML. Returns email or 'Not Found'."""
    if not soup:
        return "Not Found"

    # 1. mailto: links (most reliable)
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if "@" in email:
                domain = email.split("@")[-1].lower()
                if domain not in _EMAIL_EXCLUDES and len(email) < 80:
                    return email

    # 2. Regex on visible page text
    page_text = soup.get_text(separator=" ")
    matches = _EMAIL_REGEX.findall(page_text)
    for email in matches:
        domain = email.split("@")[-1].lower()
        if domain not in _EMAIL_EXCLUDES and len(email) < 80:
            return email

    return "Not Found"


def _try_contact_page(base_url: str) -> str:
    """
    Try scraping common contact/about pages for an email.
    Attempts /contact, /contact-us, /about, /about-us paths.
    Returns first email found or 'Not Found'.
    """
    from urllib.parse import urlparse
    from .website_analyzer import fetch_html

    try:
        parsed   = urlparse(base_url)
        base     = f"{parsed.scheme}://{parsed.netloc}"
        paths    = ["/contact", "/contact-us", "/about", "/about-us", "/reach-us"]
        for path in paths:
            soup, _, _ = fetch_html(base + path)
            if soup:
                email = extract_email(soup)
                if email != "Not Found":
                    return email
    except Exception:
        pass
    return "Not Found"


# ---------------------------------------------------------------------------
# Social media extraction (from HTML)
# ---------------------------------------------------------------------------
_SOCIAL_PRIORITY = [
    ("linkedin.com/company/", "LinkedIn"),
    ("linkedin.com/in/",      "LinkedIn"),
    ("linkedin.com",          "LinkedIn"),
    ("instagram.com",         "Instagram"),
    ("facebook.com",          "Facebook"),
    ("twitter.com",           "Twitter"),
    ("x.com",                 "Twitter"),
    ("youtube.com",           "YouTube"),
]


def extract_social_media(soup) -> str:
    """Extract best social media link (LinkedIn first). Returns URL or 'Not Found'."""
    if not soup:
        return "Not Found"

    found = {}
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        href_lower = href.lower()
        for domain, label in _SOCIAL_PRIORITY:
            if domain in href_lower and label not in found:
                clean = href.split("?")[0].rstrip("/")
                if len(clean) > len("https://" + domain) + 2:
                    found[label] = clean
                    break

    for _, label in _SOCIAL_PRIORITY:
        if label in found:
            return found[label]

    return "Not Found"


# ---------------------------------------------------------------------------
# Page text helper
# ---------------------------------------------------------------------------
def get_page_text(soup, max_chars: int = 2000) -> str:
    """Extract clean visible text from BeautifulSoup (for Gemini input)."""
    if not soup:
        return ""
    for tag in soup(["script", "style", "nav", "footer", "head", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r'\s+', ' ', text)
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Combined enrichment (email + social — no API needed)
# ---------------------------------------------------------------------------
def enrich_lead_html(website: str, soup) -> dict:
    """
    Extract email and social media from already-fetched soup.
    If email not found on homepage, tries the contact/about page.
    """
    email  = extract_email(soup)
    # If homepage didn't have email, try contact page
    if email == "Not Found" and website:
        email = _try_contact_page(website)

    return {
        "Email":        email,
        "Social Media": extract_social_media(soup),
    }


# ---------------------------------------------------------------------------
# Gemini rate limiter (free tier: 15 RPM for gemini-2.0-flash)
# ---------------------------------------------------------------------------
# Models confirmed working (tested against current API key)
_GEMINI_MODELS  = ["gemini-3.5-flash-lite"]
_RETRY_ATTEMPTS = 3           # back to normal retries since lite is faster/higher limit
_RETRY_WAIT     = 5           # base seconds
_last_gemini_time = 0.0
_GEMINI_INTERVAL  = 4.2  # seconds between calls (15 RPM free tier)


def _call_gemini(prompt: str):
    """
    Rate-limited Gemini API call.
    - Tries gemini-1.5-flash first, falls back to gemini-1.5-flash-8b
    - Retries up to 3 times on 503/overload errors
    - Suppresses AFC stderr noise via redirect
    """
    global _last_gemini_time

    client = _get_client()
    if not client:
        return None

    # Rate limiting
    elapsed = time.time() - _last_gemini_time
    wait    = _GEMINI_INTERVAL - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_gemini_time = time.time()

    for model in _GEMINI_MODELS:
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                # Redirect stderr to suppress AFC info message from SDK
                with contextlib.redirect_stderr(io.StringIO()):
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                    )
                return response
            except Exception as e:
                err = str(e)
                if "503" in err or "UNAVAILABLE" in err or "overload" in err.lower() or "429" in err:
                    if attempt < _RETRY_ATTEMPTS - 1:
                        wait_s = _RETRY_WAIT * (attempt + 1)
                        print(f"  [Gemini] {model} busy, retrying in {wait_s}s...", flush=True)
                        time.sleep(wait_s)
                        continue
                elif "404" in err or "NOT_FOUND" in err:
                    # Model not found — skip to next model immediately
                    break
                else:
                    print(f"  [Gemini] Error ({model}): {e}", flush=True)
                break   # non-retryable error — try next model

    return None


# ---------------------------------------------------------------------------
# Batch extraction: Founder Name + Email fallback via Gemini
# ---------------------------------------------------------------------------

def extract_details_batch(leads_data: list) -> list:
    """
    Extract founder name and email (as fallback) for a list of leads via Gemini.

    Parameters
    ----------
    leads_data : list of (lead_name: str, page_text: str, scraped_email: str)
        scraped_email is the email already found via HTML scraping (or 'Not Found').

    Returns
    -------
    list of (founder_name: str, final_email: str) — same order as input.
    """
    BATCH_SIZE = 5
    results    = []

    for i in range(0, len(leads_data), BATCH_SIZE):
        batch = leads_data[i : i + BATCH_SIZE]
        n     = len(batch)

        prompt = (
            f"You are a business data extractor for Indian companies.\n"
            f"For each of the {n} companies below, extract:\n\n"
            "1. FOUNDER/OWNER NAME — Use ANY of these signals (in order):\n"
            "   a) Website text: look for 'founded by', 'CEO', 'MD', 'Director',\n"
            "      'Proprietor', 'Owner', 'Managing Director', 'Chairman'\n"
            "   b) Company name: if it IS a person's name\n"
            "      (e.g. 'Jacob Thomas Consulting' → Jacob Thomas,\n"
            "       'Hanu Reddy Realty' → Hanu Reddy)\n"
            "   c) Email pattern: if email is firstname@company.com or\n"
            "      name@company.com, infer the name\n"
            "      (e.g. 'jacob@jacobthomas.biz' → Jacob Thomas)\n"
            "   → Use 'Not Found' ONLY if none of the above signals apply.\n"
            "   → DO NOT fabricate names when there is no signal.\n\n"
            "2. EMAIL — Check website text first.\n"
            "   If not in text, guess a likely address based on domain\n"
            "   (e.g. info@companysite.com). Mark guesses as-is.\n\n"
            "3. SOCIAL MEDIA URL — LinkedIn preferred, then Instagram/Facebook.\n"
            "   Check website text first. If not there, use your knowledge.\n\n"
            f"Respond with EXACTLY {n} lines in this format:\n"
            "founder_name | email_address | social_media_url\n"
            "Use 'Not Found' only when you truly cannot determine a value.\n\n"
        )

        for j, (lead_name, text, scraped_email, scraped_social) in enumerate(batch):
            email_note  = scraped_email  if scraped_email  != "Not Found" else "not found in HTML"
            social_note = scraped_social if scraped_social != "Not Found" else "not found in HTML"
            prompt += (
                f"Company {j+1}: {lead_name}\n"
                f"Email (use for name inference): {email_note}\n"
                f"Social (already found): {social_note}\n"
                f"Website text: {text[:500]}\n\n"
            )

        response = _call_gemini(prompt)

        if response and response.text:
            raw_lines   = response.text.strip().splitlines()
            valid_lines = [l.strip() for l in raw_lines if "|" in l]

            for k in range(n):
                scraped_email  = batch[k][2]
                scraped_social = batch[k][3]

                if k < len(valid_lines):
                    parts = valid_lines[k].split("|", 2)

                    raw_founder = parts[0].strip() if len(parts) > 0 else "Not Found"
                    raw_email   = parts[1].strip() if len(parts) > 1 else "Not Found"
                    raw_social  = parts[2].strip() if len(parts) > 2 else "Not Found"

                    # Validate founder
                    founder = (
                        raw_founder
                        if raw_founder and raw_founder.lower() not in ("not found", "n/a", "-", "")
                        else "Not Found"
                    )

                    # Email: prefer scraped (exact) over Gemini
                    if scraped_email != "Not Found":
                        email = scraped_email
                    elif "@" in raw_email and raw_email.lower() not in ("not found", "n/a", "-"):
                        email = raw_email
                    else:
                        email = "Not Found"

                    # Social: prefer scraped over Gemini
                    if scraped_social != "Not Found":
                        social = scraped_social
                    elif raw_social and raw_social.lower() not in ("not found", "n/a", "-", "") \
                            and ("linkedin" in raw_social.lower() or "instagram" in raw_social.lower()
                                 or "facebook" in raw_social.lower() or "twitter" in raw_social.lower()
                                 or "http" in raw_social.lower()):
                        social = raw_social
                    else:
                        social = "Not Found"

                else:
                    founder = "Not Found"
                    email   = scraped_email
                    social  = scraped_social

                results.append((founder, email, social))

        else:
            for k in range(n):
                results.append(("Not Found", batch[k][2], batch[k][3]))

    return results
