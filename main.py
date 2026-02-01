# main.py
import os
import time
import traceback

from gmail_client import list_recent_emails
from summarizer import build_summary
from telegram_sender import send_telegram_message

INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "300"))  # 5 min padrão

def run_once():
    max_results = int(os.getenv("MAX_RESULTS", "10"))
    emails = list_recent_emails(max_results=max_results)

    summary = build_summary(emails)
    if summary.strip():
        send_telegram_message(summary)

def main():
    while True:
        try:
            run_once()
            print("Done.")
        except Exception:
            # evita o processo morrer e facilita debug no log
            print("ERROR in loop:\n", traceback.format_exc())
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
