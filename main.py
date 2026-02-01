# main.py
from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gmail_client import list_recent_emails
from telegram_sender import send_telegram_message
from state_store import load_state, save_state, prune_old, now_ts
from summarizer import build_items, build_summary_from_items


TZ = ZoneInfo("America/Sao_Paulo")

# Horários fixos (pode mudar por env var)
SEND_TIMES = os.getenv("SEND_TIMES", "06:00,12:00,18:00")  # HH:MM, separados por vírgula
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "4"))     # tolerância p/ disparo
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30")) # loop curto, sem spam

MAX_EMAILS = int(os.getenv("MAX_EMAILS", "20"))
MIN_SCORE_TO_NOTIFY = int(os.getenv("MIN_SCORE_TO_NOTIFY", "35"))

# histórico
STATE_TTL_DAYS = int(os.getenv("STATE_TTL_DAYS", "14"))
STATE_TTL_SECONDS = STATE_TTL_DAYS * 24 * 3600


def parse_times(times_str: str):
    out = []
    for part in times_str.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        out.append((int(hh), int(mm)))
    return out


def slot_id(dt: datetime, hh: int, mm: int) -> str:
    return f"{dt.date().isoformat()}_{hh:02d}{mm:02d}"


def within_window(now: datetime, target_h: int, target_m: int, window_minutes: int) -> bool:
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    delta = abs((now - target).total_seconds())
    return delta <= window_minutes * 60


def run_once():
    # 1) carrega estado e faz prune
    state = load_state()
    state.setdefault("items", {})
    state.setdefault("sent_slots", {})
    state = prune_old(state, STATE_TTL_SECONDS)

    # 2) verifica se estamos em uma janela de envio
    now = datetime.now(TZ)
    times = parse_times(SEND_TIMES)

    active_slot = None
    for hh, mm in times:
        if within_window(now, hh, mm, WINDOW_MINUTES):
            active_slot = (hh, mm)
            break

    if not active_slot:
        return  # fora da janela, não envia

    hh, mm = active_slot
    sid = slot_id(now, hh, mm)

    # Evita enviar 2x no mesmo horário no mesmo dia
    if state["sent_slots"].get(sid):
        return

    # 3) busca emails e cria itens
    emails = list_recent_emails(max_results=MAX_EMAILS)
    items = build_items(emails)

    # 4) filtra "novos importantes" via histórico
    ts = now_ts()
    new_important = []
    for it in items:
        key = it["key"]
        score = int(it.get("score", 0))
        bucket = it.get("bucket", "BAIXA")

        # registra "last_seen"
        rec = state["items"].get(key, {})
        rec["last_seen"] = ts
        state["items"][key] = rec

        # só notifica acima do score mínimo e bucket não-baixa
        if score < MIN_SCORE_TO_NOTIFY or bucket == "BAIXA":
            continue

        # dedupe: só considera "novo" se nunca alertou ou se ficou 12h sem alertar
        last_alerted = int(rec.get("last_alerted", 0) or 0)
        if last_alerted == 0 or (ts - last_alerted) >= 12 * 3600:
            new_important.append(it)

    # 5) envia se tiver algo novo importante
    if new_important:
        text = build_summary_from_items(new_important)
        send_telegram_message(text)

        # marca como alertado
        for it in new_important:
            key = it["key"]
            state["items"][key]["last_alerted"] = ts

    else:
        # opcional: mandar “sem novidades”
        # send_telegram_message("Sem novidades importantes neste horário.")
        pass

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
