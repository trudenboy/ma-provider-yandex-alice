"""Every rendered config entry must resolve its user-facing text.

Entry texts live in ``strings.json`` under ``config_entries.<key>.<field>``
and are resolved by MA at serialization (``translation_key`` re-keys an
entry when one config key needs several texts). An entry that neither
passes ``label=`` in code nor is authored in ``strings.json`` would render
empty in the UI — these tests walk the form through its major states and
fail on any such entry.

Entries whose text is composed at runtime (dispatcher outcome / update
messages, probe descriptions) pass ``label=``/``description=`` directly;
their keys must NOT be authored in ``strings.json``, or the static
translation would silently override the dynamic text.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from ya_dialogs_api import SkillCreationArtifacts, SkillCreationState, dump_artifacts

from provider import get_config_entries
from provider.constants import (
    CONF_AUTH_X_TOKEN,
    CONF_DIALOG_AUTO_CREATE_ARTIFACTS,
    CONF_EDIT_MODE,
    CONF_EXTERNAL_BASE_URL,
    CONF_PENDING_DUPLICATE_SKILL_ID,
    CONF_PENDING_DUPLICATE_SKILL_NAME,
)

from .localization import load_strings

_PLACEHOLDER = re.compile(r"\{(\d+)\}")


def _make_mass() -> MagicMock:
    mass = MagicMock()
    mass.players.all_players = MagicMock(return_value=[])
    mass.webserver = None
    mass.config.get.return_value = {}
    return mass


def _artifacts(state: SkillCreationState, **kwargs: Any) -> str:
    return dump_artifacts(SkillCreationArtifacts(state=state, **kwargs))


_FORM_STATES: dict[str, dict[str, Any]] = {
    "signed_out": {},
    "signed_in_idle": {CONF_AUTH_X_TOKEN: "tok"},
    "pipeline_running": {
        CONF_AUTH_X_TOKEN: "tok",
        CONF_DIALOG_AUTO_CREATE_ARTIFACTS: _artifacts(
            SkillCreationState.APP_CREATED, skill_id="sk-1"
        ),
    },
    "failed": {
        CONF_AUTH_X_TOKEN: "tok",
        CONF_EXTERNAL_BASE_URL: "https://ma.example.org",
        CONF_DIALOG_AUTO_CREATE_ARTIFACTS: _artifacts(SkillCreationState.FAILED, last_error="boom"),
    },
    "duplicate_pending": {
        CONF_AUTH_X_TOKEN: "tok",
        CONF_PENDING_DUPLICATE_SKILL_ID: "sk-dup",
        CONF_PENDING_DUPLICATE_SKILL_NAME: "My Skill",
    },
    "registered": {
        CONF_AUTH_X_TOKEN: "tok",
        CONF_DIALOG_AUTO_CREATE_ARTIFACTS: _artifacts(SkillCreationState.DONE, skill_id="sk-1"),
    },
    "registered_edit_mode": {
        CONF_AUTH_X_TOKEN: "tok",
        CONF_DIALOG_AUTO_CREATE_ARTIFACTS: _artifacts(SkillCreationState.DONE, skill_id="sk-1"),
        CONF_EDIT_MODE: True,
    },
}


async def _render(values: dict[str, Any]) -> tuple[Any, ...]:
    entries: tuple[Any, ...] = await get_config_entries(_make_mass(), values=dict(values))
    return entries


@pytest.mark.asyncio
@pytest.mark.parametrize("state", _FORM_STATES)
async def test_every_visible_entry_resolves_text(state: str) -> None:
    """Non-hidden entries carry an in-code label or an authored strings.json text."""
    authored = load_strings()["config_entries"]
    entries = await _render(_FORM_STATES[state])
    assert entries
    for entry in entries:
        if getattr(entry, "hidden", False):
            continue
        translation_key = getattr(entry, "translation_key", None) or entry.key
        texts = authored.get(translation_key, {})
        in_code_label = getattr(entry, "label", None)
        assert in_code_label or "label" in texts, (
            f"{state}: entry '{entry.key}' (translation_key={translation_key!r}) "
            "has no label in code and none authored in strings.json"
        )
        if entry.type.value == "action":
            assert getattr(entry, "action_label", None) or "action_label" in texts, (
                f"{state}: action entry '{entry.key}' has no action_label anywhere"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", _FORM_STATES)
async def test_dynamic_texts_are_not_shadowed_by_strings_json(state: str) -> None:
    """Entries passing runtime-composed label= must stay unauthored in strings.json."""
    authored = load_strings()["config_entries"]
    for entry in await _render(_FORM_STATES[state]):
        if not getattr(entry, "label", None):
            continue
        translation_key = getattr(entry, "translation_key", None) or entry.key
        assert "label" not in authored.get(translation_key, {}), (
            f"{state}: entry '{entry.key}' passes a runtime label but "
            f"'{translation_key}' is also authored in strings.json — the static "
            "translation would override the dynamic text"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", _FORM_STATES)
async def test_placeholders_receive_translation_params(state: str) -> None:
    """Authored ``{n}`` placeholders must be fed by enough translation_params."""
    authored = load_strings()["config_entries"]
    for entry in await _render(_FORM_STATES[state]):
        translation_key = getattr(entry, "translation_key", None) or entry.key
        texts = authored.get(translation_key, {})
        params = getattr(entry, "translation_params", None) or []
        for field in ("label", "description", "action_label"):
            placeholders = [int(m) for m in _PLACEHOLDER.findall(texts.get(field, ""))]
            if not placeholders:
                continue
            assert len(params) > max(placeholders), (
                f"{state}: '{translation_key}.{field}' uses placeholder "
                f"{{{max(placeholders)}}} but entry '{entry.key}' provides "
                f"only {len(params)} translation_params"
            )


def test_config_categories_are_authored() -> None:
    """The three form section slugs resolve from config_categories."""
    categories = load_strings()["config_categories"]
    assert {"Authorization", "Skill", "Settings"} <= set(categories)
