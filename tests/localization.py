"""Helpers for asserting against the provider's ``strings.json`` texts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_STRINGS_PATH = Path(__file__).resolve().parent.parent / "provider" / "strings.json"


@lru_cache(maxsize=1)
def load_strings() -> dict[str, Any]:
    """Parse the provider ``strings.json`` once per test session."""
    data: dict[str, Any] = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    return data


def entry_text(key: str, field: str = "label") -> str:
    """
    Return ``config_entries.<key>.<field>`` from ``strings.json``.

    :param key: The config entry key (or explicit translation key).
    :param field: The authored field: ``label`` / ``description`` / ``action_label``.
    :raises KeyError: When the key or field is not authored.
    """
    text: str = load_strings()["config_entries"][key][field]
    return text
