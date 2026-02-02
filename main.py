import os
import time
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from summarizer import build_items, build_summary_from_items


TZ_NAME = os.getenv("TIMEZONE", "America/Sao_Paulo")
RUN_TIMES = os.getenv("RUN_TIMES", "09:00,12:00,18:00")  # 3x/dia
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "30"))
HEARTBEAT_WHEN_EMPTY = os.getenv("HEARTBEAT_WHEN_EMPTY", "1") == "1"

STATE_PATH = os.getenv("STATE_PATH", "/tmp/email_agent_state.json")


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Could not save state: {e}")


def _parse_times(times_csv: str):
    out = []
    for part in times_csv.split(","):
        t = part.strip()
        if not t:
            continue
        hh, mm = t.split(":")
        out.append((int(hh), int(mm), t))
    out.sort()
    return out


def _today_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _next_run(now: datetime, schedule):
    """
    schedule = [(hh, mm, "HH:MM"), ...]
    returns (run_dt, slot_str)
    """
    for hh, mm, slot in schedule:
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate > now:
            return candidate, slot
    # otherwise, next day first slot
    hh, mm, slot = schedule[0]
    tomorrow = (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return tomorrow, slot


def _should_run_now(now: datetime, schedule, state: dict) -> str | None:
    """
    If we missed a slot (restart / downtime), run it as soon as possible.
    Returns the slot_str that should run, or None.
    """
    today = _today_key(now)
    ran = state.get("ran", {})  # {"YYYY-MM-DD": ["09:00", ...]}

    ran_today = set(ran.get(today, []))

    # find earliest slot today that is already due and not executed
    for hh, mm, slot in schedule:
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= due and slot not in ran_today:
            return slot

    return None


def _mark_ran(now: datetime, slot: str, state: dict):
    today = _today_key(now)
    if "ran" not in state:
        state["ran"] = {}
    if today not in state["ran"]:
        state["ran"][today] = []
    if slot not in state["ran"][today]:
        state["ran"][today].append(slot)


def run_once(now: datetime, slot: str):
    print(f"[RUN] slot={slot} now={now.isoformat()} max_results={MAX_RESULTS}")

    emails = list_recent_emails(max_results=MAX_RESULTS) or []
    # emails: lista de dicts. Se faltar snippet, o summarizer aguenta.

    items = build_items(emails)

    # Se não tiver nada relevante, você decide se manda heartbeat
    if not items:
        if HEARTBEAT_WHEN_EMPTY:
            msg = (
                "Tudo tranquilo por aqui.\n\n"
                "Olhei seus últimos emails e não vi nada que pareça banco/contas, escola, "
                "ou prazos importantes agora. 👍"
            )
            send_telegram_message(msg)
            print("[INFO] Sent heartbeat (empty).")
        else:
            print("[INFO] No items to send. Skipping message.")
        return

    summary_text = build_summary_from_items(items)
    send_telegram_message(summary_text)
    print("[OK] Telegram sent.")


def main_loop():
    tz = ZoneInfo(TZ_NAME)
    schedule = _parse_times(RUN_TIMES)
    if not schedule:
        raise RuntimeError("RUN_TIMES vazio. Ex: RUN_TIMES=09:00,12:00,18:00")

    print(f"BOOT: worker loop started | TZ={TZ_NAME} | RUN_TIMES={RUN_TIMES} | MAX_RESULTS={MAX_RESULTS}")

    state = _load_state()

    while True:
        now = datetime.now(tz)
        due_slot = _should_run_now(now, schedule, state)

        if due_slot:
            try:
                run_once(now, due_slot)
            except Exception as e:
                # não mata o worker por erro pontual
                print(f"[ERROR] run_once failed: {type(e).__name__}: {e}")
            finally:
                _mark_ran(now, due_slot, state)
                _save_state(state)

            # pequeno intervalo para evitar loop apertado após execução
            time.sleep(5)
            continue

        next_dt, next_slot = _next_run(now, schedule)
        sleep_s = max(1, int((next_dt - now).total_seconds()))
        print(f"[SCHEDULE] now={now.isoformat()} next={next_dt.isoformat()} slot={next_slot} sleep={sleep_s}s")
        time.sleep(sleep_s)


if __name__ == "__main__":
    main_loop()
