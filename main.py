import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from summarizer import build_items, build_summary_from_items


TZ_NAME = os.getenv("TIMEZONE", "America/Sao_Paulo")
RUN_TIMES = os.getenv("RUN_TIMES", "09:00,12:00,18:00")  # 3x ao dia
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "30"))

# Se quiser receber "tudo tranquilo" quando não houver nada relevante:
HEARTBEAT_WHEN_EMPTY = os.getenv("HEARTBEAT_WHEN_EMPTY", "1") == "1"


def parse_times(times_csv: str):
    out = []
    for part in times_csv.split(","):
        t = part.strip()
        if not t:
            continue
        hh, mm = t.split(":")
        out.append((int(hh), int(mm), t))
    out.sort()
    return out


def next_run(now: datetime, schedule):
    for hh, mm, slot in schedule:
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate > now:
            return candidate, slot
    hh, mm, slot = schedule[0]
    tomorrow = (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return tomorrow, slot


def run_once(now: datetime, slot: str):
    print(f"[RUN] slot={slot} now={now.isoformat()} max_results={MAX_RESULTS}", flush=True)

    emails = list_recent_emails(max_results=MAX_RESULTS) or []
    items = build_items(emails)

    if not items:
        if HEARTBEAT_WHEN_EMPTY:
            send_telegram_message(
                "Tudo tranquilo por aqui.\n\n"
                "Olhei os emails recentes e não vi nada que pareça banco/contas, escola ou prazos importantes agora."
            )
        return

    msg = build_summary_from_items(items)
    if msg and msg.strip():
        send_telegram_message(msg)


def main_loop():
    tz = ZoneInfo(TZ_NAME)
    schedule = parse_times(RUN_TIMES)
    if not schedule:
        raise RuntimeError("RUN_TIMES vazio. Ex: 09:00,12:00,18:00")

    print(
        f"BOOT: worker loop started | TZ={TZ_NAME} | RUN_TIMES={RUN_TIMES} | MAX_RESULTS={MAX_RESULTS}",
        flush=True
    )

    while True:
        now = datetime.now(tz)
        nxt, slot = next_run(now, schedule)
        sleep_s = max(1, int((nxt - now).total_seconds()))

        print(
            f"[SCHEDULE] now={now.isoformat()} next={nxt.isoformat()} slot={slot} sleep={sleep_s}s",
            flush=True
        )

        time.sleep(sleep_s)

        try:
            run_once(datetime.now(tz), slot)
        except Exception as e:
            print(f"[ERROR] run_once failed: {type(e).__name__}: {e}", flush=True)

        time.sleep(2)


if __name__ == "__main__":
    main_loop()
