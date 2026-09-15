import pandas as pd
from pathlib import Path

DATA   = Path('data'); DATA.mkdir(exist_ok=True)
RECENT = DATA / 'lead_results.csv'
MASTER = DATA / 'all_leads_database.csv'

COLS = [
    'Lead Name', 'Website', 'Website Available', 'Phone',
    'Lead Score', 'Priority', 'Source', 'Location', 'Industry',
    'Recommended Services',
    'Performance Issues', 'SEO Issues', 'Best Practices Issues',
]

def export_csv(df):
    if isinstance(df, list):
        df = pd.DataFrame(df)

    # Ensure all expected columns exist (fill missing with empty string)
    df = df.reindex(columns=COLS, fill_value='')

    df.to_csv(RECENT, index=False)

    # Load (or create) master database and ensure it has the new columns too
    if MASTER.exists():
        master = pd.read_csv(MASTER)
        master = master.reindex(columns=COLS, fill_value='')
    else:
        master = pd.DataFrame(columns=COLS)

    updated = (
        pd.concat([master, df], ignore_index=True)
        .drop_duplicates(subset=['Lead Name', 'Website', 'Location', 'Industry'])
    )
    updated.to_csv(MASTER, index=False)
    return len(updated)
