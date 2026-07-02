"""
File-backed history persistence for the Chat / Doc Review / Compliance Gen
pages.

st.session_state does not reliably survive a full browser refresh --
Streamlit can start a brand-new session on reconnect, wiping in-memory
state. Mirroring each page's history to a small local JSON file lets
users refresh (or come back later) without losing their conversation,
past audits, or generated reports.
"""

import json
import os
from typing import Any, List

_HISTORY_DIR = os.path.join("data", "session_history")
_MAX_ENTRIES = 50


def _path(name: str) -> str:
    return os.path.join(_HISTORY_DIR, f"{name}.json")


def load_history(name: str) -> List[Any]:
    path = _path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(name: str, entries: List[Any]) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(entries[-_MAX_ENTRIES:], f, ensure_ascii=False, indent=2)


def clear_history(name: str) -> None:
    save_history(name, [])
