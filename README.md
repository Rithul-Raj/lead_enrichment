# Smart Lead Generation

## Setup

1. Add your SerpAPI key to `config.py`
2. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\Activate
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run:
   ```
   python app.py
   ```

## Features

- **Lead Search**: Fetches business leads from Google Maps via SerpAPI.
- **Website Analysis**: Automatically scrapes each lead's website to detect service gaps.
- **Intelligent Priority Scoring**: Priority (High / Medium / Low) is calculated based on the number and weight of detected service opportunities — not just star ratings.
- **Deduplication**: Skips leads already present in the master database.
- **CSV Export**: Saves results to `data/lead_results.csv` (latest run) and `data/all_leads_database.csv` (full database).

## Output Columns

| Column | Description |
|---|---|
| Lead Name | Business name |
| Website | Website URL |
| Website Available | Yes / No |
| Phone | Contact number |
| Lead Score | 0–100 (blend of rating + opportunity score) |
| Priority | High / Medium / Low (based on website analysis) |
| Rating | Google Maps star rating |
| Source | Data source (SerpAPI) |
| Location | Business address |
| Industry | Searched industry |
| Recommended Services | Comma-separated list of Detagenix services relevant to this lead |
| Service Opportunity Score | 0–100 score indicating how many service gaps were detected |

## Detected Services

The analyzer checks for the following service opportunities:
- **Web Development** – Lead has no website
- **Website Revamp** – Outdated or very basic website detected
- **Mobile App Development** – No app store links found
- **Digital Marketing** – No social media links found
- **SSL / Security** – Website served over HTTP (not HTTPS)
- **AI Chatbot / CRM** – No live chat or chatbot integration found
- **CRM / HRM Software** – No CRM/ERP/HR system mentions found
- **Cloud Services** – No cloud infrastructure keywords found
- **Analytics Integration** – No analytics/tracking scripts found
- **E-Commerce Development** – No shopping/checkout features found
