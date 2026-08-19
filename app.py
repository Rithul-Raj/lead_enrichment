from collections import Counter
from src.input_handler import get_user_input
from src.lead_search_engine import search_leads
from src.deduplication import remove_duplicates
from src.export_service import export_csv


def _summarise_services(leads):
    """Return the top 3 most-recommended services across all analysed leads."""
    counter = Counter()
    for lead in leads:
        services = lead.get("Recommended Services", "")
        if services and services not in ("None Identified", "Analysis Failed"):
            for s in services.split(","):
                s = s.strip()
                if s:
                    counter[s] += 1
    return counter.most_common(3)


def main():
    print("=" * 45)
    print("       SMART LEAD GENERATION SYSTEM")
    print("=" * 45 + "\n")

    location, industry, num_leads = get_user_input()

    print(f"\nIndustry : {industry}")
    print(f"Location : {location}")
    print(f"Leads    : {num_leads}\n")
    print("-" * 45)
    print("Fetching leads & analysing websites in parallel...")
    print("(All websites are checked simultaneously)\n")

    leads = search_leads(location, industry, num_leads)

    print()
    unique, dup, dup_count, new_count = remove_duplicates(leads)
    total = export_csv(unique)

    print(f"\nResults fetched    : {len(leads)}")
    if dup_count:
        print(f"Duplicates skipped : {dup_count} (already in database)")

    print("\n" + "=" * 45)
    print("           SEARCH COMPLETED")
    print("=" * 45)
    print(f"  New Leads Added      : {new_count}")
    print(f"  Total in Database    : {total}")

    # ── Service opportunity summary ─────────────────────────────────────────
    top_services = _summarise_services(leads)
    if top_services:
        print("\n  Top Service Opportunities Identified:")
        for rank, (service, count) in enumerate(top_services, 1):
            print(f"    {rank}. {service} ({count} leads)")

    print("\n  Data saved to:")
    print("    data/lead_results.csv        (latest search)")
    print("    data/all_leads_database.csv  (full database)\n")


if __name__ == "__main__":
    main()

