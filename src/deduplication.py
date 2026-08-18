import pandas as pd
from pathlib import Path
DB=Path('data/all_leads_database.csv')
KEYS=['Lead Name','Website','Location','Industry']
def remove_duplicates(leads):
    new=pd.DataFrame(leads)
    if new.empty:
        return new,pd.DataFrame(),0,0
    for c in KEYS:
        if c not in new.columns:
            new[c]=''
    if not DB.exists():
        return new,pd.DataFrame(columns=new.columns),0,len(new)
    old=pd.read_csv(DB)
    for c in KEYS:
        if c not in old.columns:
            old[c]=''
    old_keys=set(zip(old['Lead Name'].fillna('').astype(str).str.lower(),old['Website'].fillna('').astype(str).str.lower(),old['Location'].fillna('').astype(str).str.lower(),old['Industry'].fillna('').astype(str).str.lower()))
    new_keys=list(zip(new['Lead Name'].fillna('').astype(str).str.lower(),new['Website'].fillna('').astype(str).str.lower(),new['Location'].fillna('').astype(str).str.lower(),new['Industry'].fillna('').astype(str).str.lower()))
    mask=pd.Series([k in old_keys for k in new_keys],index=new.index)
    return new[~mask].copy(),new[mask].copy(),int(mask.sum()),int((~mask).sum())
