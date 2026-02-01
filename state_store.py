# state_store.py
from __future__ import annotations

import json
import os
import time
from typing import Dict, Any

DEFAULT_STATE_PATH = os.getenv("STATE_PATH", "state.json")

def load_state(path: str = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        # Se corromper, volta vazio (não derruba o worker)
        return {}

def save_state(state: Dict[str, Any], path: str = DEFAULT_STATE_PATH) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def now_ts() -> int:
    return int(time.time())

def prune_old(state: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
    """
    Remove chaves antigas (evita state crescer indefinidamente).
    """
    ts = now_ts()
    items = state.get("items", {})
    if not isinstance(items, dict):
        items = {}
    new_items = {}
    for k, v in items.items():
        last_seen = int(v.get("last_seen", 0) or 0)
        if ts - last_seen <= ttl_seconds:
            new_items[k] = v
    state["items"] = new_items
    return state
