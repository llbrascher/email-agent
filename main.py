# main.py
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from state_store import load_state, save_state, prune_old, now_ts
from summarizer import build_items, build_summary_from_items

TZ = ZoneInfo("America/Sao_Paulo")

# Horários de envio (HH:MM separados por vírgula)
SEND_TIMES = os.getenv("SEND_TIMES", "06:00,12:00,18:00")
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "4"))          # tolerância para disparo
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))      # loop interno (não é horário do resumo)
MAX_EMAILS = int(os.getenv("MAX_EMAILS", "30"))                  # quantos emails buscar do Gmail
MIN_SCORE_TO_NOTIFY = int(os.getenv("MIN_SCORE_TO_NOTIFY", "35"))# corte do score (0-100)

# Histórico
STATE_TTL_DAYS = int(os.getenv("STATE_TTL_DAYS", "14"))
STATE_TTL_SECONDS = STATE_TTL_DAYS * 24 * 3600
RE_ALERT_HOURS = int(os.getenv("RE_ALERT_HOURS", "12"))          # só re-alerta o mesmo item após N horas


def parse_times(times_str: str):
    out = []
    for part in times_str.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        out.append((int(hh), int(mm)))
    return out


def slot_id(now: datetime, hh: int, mm: int) -> str:
    return f"{now.date().isoformat()}_{hh:02d}{mm:02d}"


def within_window(now: datetime, hh: int, mm: int, window_minutes: int) -> bool:
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta_sec = abs((now - target).total_seconds())
    return delta_sec <= window_minutes * 60


def run_once():
    # 1) estado
    state = load_state()
    state.setdefault("items", {})
    state.setdefault("sent_slots", {})
    state = prune_old(state, STATE_TTL_SECONDS)

    now = datetime.now(TZ)
    ts = now_ts()

    # 2) verifica se estamos perto de um horário de envio
    times = parse_times(SEND_TIMES)
    active = None
    for hh, mm in times:
        if within_window(now, hh, mm, WINDOW_MINUTES):
            active = (hh, mm)
            break

    if not active:
        return

    hh, mm = active
    sid = slot_id(now, hh, mm)

    # Não manda 2x no mesmo slot do mesmo dia
    if state["sent_slots"].get(sid):
        return

    # 3) busca emails e gera itens com score
    emails = list_recent_emails(max_results=MAX_EMAILS)
    items = build_items(emails)  # <- já retorna itens deduplicados + bucket + score

    # 4) filtra apenas itens novos e relevantes
    new_important = []
    for it in items:
        key = it["key"]
        score = int(it.get("score", 0))
        bucket = it.get("bucket", "BAIXA")

        # marca visto
        rec = state["items"].get(key, {})
        rec["last_seen"] = ts
        state["items"][key] = rec

        # só notifica acima do score e não-baixa
        if bucket == "BAIXA" or score < MIN_SCORE_TO_NOTIFY:
            continue

        last_alerted = int(rec.get("last_alerted", 0) or 0)
        if last_alerted == 0 or (ts - last_alerted) >= RE_ALERT_HOURS * 3600:
            new_important.append(it)

    # 5) envia se houver novidade importante
    if new_important:
        msg = build_summary_from_items(new_important)  # <- inclui [score/100] no texto
        send_telegram_message(msg)

        # marca alertado
        for it in new_important:
            state["items"][it["key"]]["last_alerted"] = ts

    # 6) marca slot como enviado e salva estado
    state["sent_slots"][sid] = ts
    save_state(state)


def main():
    print("BOOT: worker loop started", flush=True)
    while True:
        try:
            run_once()
        except Exception:
            print("ERROR:\n", traceback.format_exc(), flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
