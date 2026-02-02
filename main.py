import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from summarizer import build_summary


TZ = os.getenv("TZ", "America/Sao_Paulo")
TIMEZONE = ZoneInfo(TZ)

# Horários fixos (3x/dia). Padrão: 06:00 / 12:00 / 18:00
# Você pode mudar no Render > Environment:
# RUN_TIMES="06:00,12:00,18:00"
RUN_TIMES = os.getenv("RUN_TIMES", "06:00,12:00,18:00")

# Quantos emails buscar a cada rodada
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "40"))


def parse_run_times(run_times_str: str):
    times = []
    for part in run_times_str.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        times.append((int(hh), int(mm)))
    times.sort()
    return times


def next_run_datetime(now: datetime, run_times):
    today = now.date()

    for hh, mm in run_times:
        candidate = datetime(today.year, today.month, today.day, hh, mm, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate

    # se já passou de todos hoje -> primeiro horário de amanhã
    tomorrow = today + timedelta(days=1)
    hh, mm = run_times[0]
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hh, mm, tzinfo=now.tzinfo)


def main():
    run_times = parse_run_times(RUN_TIMES)
    if not run_times:
        raise ValueError("RUN_TIMES inválido. Ex: 06:00,12:00,18:00")

    print(f"BOOT: worker loop started (TZ={TZ}, RUN_TIMES={RUN_TIMES}, MAX_RESULTS={MAX_RESULTS})")

    while True:
        now = datetime.now(TIMEZONE)
        nxt = next_run_datetime(now, run_times)
        sleep_s = max(1, int((nxt - now).total_seconds()))

        print(f"Next run at {nxt.isoformat()} (sleep {sleep_s}s)")
        time.sleep(sleep_s)

        try:
            emails = list_recent_emails(max_results=MAX_RESULTS)
            summary_text = build_summary(emails)
            send_telegram_message(summary_text)
            print("Sent summary to Telegram.")
        except Exception as e:
            # Não derruba o worker
            print(f"ERROR: {repr(e)}")


if __name__ == "__main__":
    main()
