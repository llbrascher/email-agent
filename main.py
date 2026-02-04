import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from summarizer import build_items, build_summary_from_items


# =========================
# CONFIGURAÇÕES
# =========================
TZ_NAME = os.getenv("TIMEZONE", "America/Sao_Paulo")
RUN_TIMES = os.getenv("RUN_TIMES", "09:00,12:00,18:00")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "30"))
HEARTBEAT_WHEN_EMPTY = os.getenv("HEARTBEAT_WHEN_EMPTY", "1") == "1"


# =========================
# FUNÇÕES DE APOIO
# =========================
def parse_times(times_csv: str):
    slots = []
    for part in times_csv.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        slots.append((int(hh), int(mm), part))
    slots.sort()
    return slots


def next_run(now: datetime, schedule):
    for hh, mm, label in schedule:
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate > now:
            return candidate, label

    # próximo dia
    hh, mm, label = schedule[0]
    tomorrow = (now + timedelta(days=1)).replace(
        hour=hh, minute=mm, second=0, microsecond=0
    )
    return tomorrow, label


# =========================
# EXECUÇÃO ÚNICA
# =========================
def run_once(now: datetime, slot: str):
    print(f"[RUN] slot={slot} now={now.isoformat()} max_results={MAX_RESULTS}")

    try:
        emails = list_recent_emails(max_results=MAX_RESULTS) or []
    except Exception as e:
        print(f"[ERROR] Gmail fetch failed: {type(e).__name__}: {e}")
        return

    if not emails:
        if HEARTBEAT_WHEN_EMPTY:
            send_telegram_message(
                "📭 Caixa tranquila por enquanto.\n\n"
                "Não encontrei emails recentes que pareçam banco, contas, escola ou prazos importantes."
            )
        return

    try:
        items = build_items(emails)
        if not items:
            if HEARTBEAT_WHEN_EMPTY:
                send_telegram_message(
                    "Tudo sob controle 👍\n\n"
                    "Li seus emails recentes e não vi nada que exija ação agora."
                )
            return

        summary = build_summary_from_items(items)
        if summary and summary.strip():
            send_telegram_message(summary)

    except Exception as e:
        # ⚠️ Proteção contra erro de JSON / OpenAI / parsing
        print(f"[ERROR] Summarizer failed: {type(e).__name__}: {e}")
        send_telegram_message(
            "⚠️ Tive um problema técnico ao resumir seus emails agora.\n\n"
            "Nada foi perdido — tento novamente no próximo horário programado."
        )


# =========================
# LOOP PRINCIPAL
# =========================
def main_loop():
    tz = ZoneInfo(TZ_NAME)
    schedule = parse_times(RUN_TIMES)

    if not schedule:
        raise RuntimeError("RUN_TIMES inválido. Ex: 09:00,12:00,18:00")

    print(
        f"BOOT: worker loop started | "
        f"TZ={TZ_NAME} | RUN_TIMES={RUN_TIMES} | MAX_RESULTS={MAX_RESULTS}"
    )

    while True:
        now = datetime.now(tz)
        nxt, slot = next_run(now, schedule)
        sleep_s = max(1, int((nxt - now).total_seconds()))

        print(
            f"[SCHEDULE] now={now.isoformat()} "
            f"next={nxt.isoformat()} slot={slot} sleep={sleep_s}s"
        )

        time.sleep(sleep_s)

        try:
            run_once(datetime.now(tz), slot)
        except Exception as e:
            print(f"[FATAL] run_once crashed: {type(e).__name__}: {e}")

        # pequena pausa de segurança
        time.sleep(5)


# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    main_loop()
