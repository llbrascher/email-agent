from gmail_client import list_recent_emails
from summarizer import build_summary

emails = list_recent_emails(hours_back=24, max_results=10)
summary = build_summary(emails)

print(summary)