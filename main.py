import os
from gmail_client import list_recent_emails
from summarizer import build_summary
from telegram_sender import send_telegram_message

def main():
    print("Worker started.")

    # Ajuste quantos emails quer resumir
    max_results = int(os.getenv("MAX_EMAILS", "10"))

    emails = list_recent_emails(max_results=max_results)
    summary = build_summary(emails)

    # Envia para Telegram
    send_telegram_message(summary)

    print("Done.")

if __name__ == "__main__":
    main()
