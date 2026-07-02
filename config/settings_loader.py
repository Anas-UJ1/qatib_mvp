"""
Centralized settings loader. Reads config/settings.yaml once and caches it,
so the model name, temperatures, chunk sizes, and top_k are defined in ONE
place instead of being hardcoded across multiple files.
"""

import os
import functools
import yaml

_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.yaml")


@functools.lru_cache(maxsize=1)
def get_settings() -> dict:
    with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
