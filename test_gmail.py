from gmail_client import list_recent_emails

emails = list_recent_emails(hours_back=24, max_results=5)
print(f"Encontrei {len(emails)} emails.\n")

for e in emails:
    print("FROM:", e["from"])
    print("SUBJ:", e["subject"])
    print("DATE:", e["date"])
    print("SNIP:", e["snippet"])
    print("-" * 60)