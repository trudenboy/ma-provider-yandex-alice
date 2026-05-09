# ruff: noqa: D107, RUF001
"""Effective skill manifest with file-based override + UI status reporting.

Single class :class:`SkillManifestProvider` is the only entry point for
the rest of the provider to read / write / validate the skill TOML
manifest. It encapsulates:

* Loading the **effective** manifest (override file if present and
  valid, else the package-bundled default at
  ``provider/data/skill.toml``).
* Status reporting to UI: bundled / override-active / override-invalid
  with the parser error message for the latter.
* File operations exposed as user-facing actions: export current
  effective manifest to override path; import paste from UI; reset
  (delete override); validate override locally.
* Runtime dispatch of an NLU intent block (``request.nlu.intents``)
  into a :class:`ParsedControl` / :class:`ParsedCommand` via the
  manifest's ``runtime:`` blocks (provider-side ``parse_intent``).

Override file path: ``<storage_root>/yandex_alice/skill.toml`` where
``storage_root`` is ``mass.storage_path`` if MA exposes it, falling
back to ``$HOME/.musicassistant`` (matching the path convention the
provider already documents in dialogs.py for log files).
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import importlib.resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ya_dialogs_api import (
    EntityDraft,
    IntentDraft,
    SkillManifest,
    SkillManifestError,
    apply_runtime_mapping,
    iter_intent_matches,
    parse_manifest_text,
)

from .dialogs_control import ParsedControl
from .dialogs_nlu import ParsedCommand

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant

__all__ = [
    "ManifestStatus",
    "SkillManifestProvider",
]


_LOGGER = logging.getLogger(__name__)

_BASE64_PASTE_PREFIX = "data:base64,"


@dataclasses.dataclass(frozen=True, slots=True)
class ManifestStatus:
    """User-facing snapshot of the effective manifest.

    :param source: ``"bundled"`` when no override file exists,
        ``"override_valid"`` when the override file parses cleanly,
        ``"override_invalid"`` when the override file is present but
        unusable (the bundled default is loaded as fallback).
    :param override_path: path where the override file lives or
        would live (always reportable to UI even when absent).
    :param intent_count: number of intents in the effective manifest.
    :param entity_count: number of entities in the effective manifest.
    :param error: parser error message when ``source ==
        "override_invalid"``, ``None`` otherwise.
    """

    source: Literal["bundled", "override_valid", "override_invalid"]
    override_path: Path
    intent_count: int
    entity_count: int
    error: str | None = None


class SkillManifestProvider:
    """Effective skill manifest gateway for the rest of the provider.

    Cheap to construct (no I/O); each method that needs the manifest
    re-reads from disk, so override edits take effect on the next call
    without a restart.
    """

    def __init__(self, mass: MusicAssistant) -> None:
        self._mass = mass
        self._last_import_success = False

    # -----------------------------------------------------------------------
    # Path & status
    # -----------------------------------------------------------------------

    @property
    def override_path(self) -> Path:
        """Where the user override TOML lives (or would live)."""
        return self._storage_root() / "yandex_alice" / "skill.toml"

    @property
    def last_import_success(self) -> bool:
        """``True`` if the most recent ``import_from_paste`` call succeeded."""
        return self._last_import_success

    def status(self) -> ManifestStatus:
        """Diagnostic snapshot for UI display."""
        path = self.override_path
        if not path.exists():
            bundled = self._bundled_manifest()
            return ManifestStatus(
                source="bundled",
                override_path=path,
                intent_count=len(bundled.intents),
                entity_count=len(bundled.to_entity_drafts()),
            )
        try:
            text = path.read_text(encoding="utf-8")
            override = parse_manifest_text(text)
        except (OSError, SkillManifestError) as exc:
            bundled = self._bundled_manifest()
            return ManifestStatus(
                source="override_invalid",
                override_path=path,
                intent_count=len(bundled.intents),
                entity_count=len(bundled.to_entity_drafts()),
                error=str(exc),
            )
        return ManifestStatus(
            source="override_valid",
            override_path=path,
            intent_count=len(override.intents),
            entity_count=len(override.to_entity_drafts()),
        )

    # -----------------------------------------------------------------------
    # Effective manifest loading
    # -----------------------------------------------------------------------

    def manifest(self) -> SkillManifest:
        """Return the effective manifest — override if valid, else bundled."""
        path = self.override_path
        if path.exists():
            try:
                return parse_manifest_text(path.read_text(encoding="utf-8"))
            except (OSError, SkillManifestError) as exc:
                _LOGGER.warning(
                    "skill manifest override at %s is invalid (%s); "
                    "falling back to bundled default",
                    path,
                    exc,
                )
        return self._bundled_manifest()

    def grammar(self) -> list[IntentDraft]:
        """Effective intents as ``IntentDraft`` for ``set_intents``."""
        return self.manifest().to_intent_drafts()

    def entities(self) -> list[EntityDraft]:
        """Effective entities as ``EntityDraft`` for ``set_entities``."""
        return self.manifest().to_entity_drafts()

    # -----------------------------------------------------------------------
    # Runtime dispatch — NLU intent block → ParsedControl/ParsedCommand
    # -----------------------------------------------------------------------

    def parse_intent(
        self,
        nlu_intents: dict[str, Any] | None,
    ) -> ParsedControl | ParsedCommand | None:
        """Map an NLU intent block to the dispatcher's dataclass.

        Walks ``request.nlu.intents`` matches against the effective
        manifest's ``runtime`` blocks; the first matched intent with a
        valid runtime mapping yields a :class:`ParsedControl` (kind
        ``"control"``) or :class:`ParsedCommand` (kind ``"play"``).
        Returns ``None`` when no intent has a runtime mapping that
        applies (slot missing without default, value rejected by
        cap / reject_if_below, or matched intent has no runtime block).
        """
        manifest = self.manifest()
        by_form = {i.form_name: i for i in manifest.intents}
        for match in iter_intent_matches(nlu_intents):
            intent = by_form.get(match.form_name)
            if intent is None or intent.runtime is None:
                continue
            fields = apply_runtime_mapping(match, intent.runtime)
            if fields is None:
                continue
            if intent.runtime.kind == "control":
                return ParsedControl(
                    action=intent.runtime.action,  # type: ignore[arg-type]
                    **fields,
                )
            if intent.runtime.kind == "play":
                # Play-side ParsedCommand has fixed fields; manifest
                # may declare no mapping (my_wave) or future query
                # mappings. Defaults match v1.5.0 hardcoded behaviour.
                return ParsedCommand(
                    kind=intent.runtime.action,  # type: ignore[arg-type]
                    query=fields.get("query", ""),
                    radio_mode=bool(fields.get("radio_mode", True)),
                )
            # Unknown kind — silently skip (consumer-side configuration
            # error; production logs would catch repeat offenders).
        return None

    # -----------------------------------------------------------------------
    # User-facing actions
    # -----------------------------------------------------------------------

    def export_to_override(self) -> str:
        """Copy bundled default into the override path (if not already there).

        First-time export bootstraps the override file from the
        manifest the user is currently effectively running. Subsequent
        invocations are a no-op — user edits aren't trampled.
        """
        path = self.override_path
        if path.exists():
            return f"Override уже существует: {path}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._bundled_manifest_text(), encoding="utf-8")
        return f"Манифест экспортирован в {path}. Откройте файл во внешнем редакторе."

    def import_from_paste(self, paste: str) -> str:
        """Validate and write a TOML paste into the override file.

        ``data:base64,<b64>`` prefix triggers base64 decoding (fallback
        for MA UI clients that strip newlines from STRING fields).
        Sets :attr:`last_import_success` so the dispatcher in
        ``__init__.py`` can clear the paste field on success.
        """
        self._last_import_success = False
        if not paste or not paste.strip():
            return "Поле для вставки пусто, нечего импортировать"

        text, decode_error = self._decode_paste(paste)
        if decode_error is not None:
            return f"Импорт не удался: {decode_error}"

        try:
            manifest = parse_manifest_text(text)
        except SkillManifestError as exc:
            return f"Импорт не удался — манифест невалиден: {exc}"

        path = self.override_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return f"Импорт не удался — не могу записать {path}: {exc}"

        self._last_import_success = True
        return (
            f"Манифест импортирован в {path} — "
            f"{len(manifest.intents)} intents, "
            f"{len(manifest.to_entity_drafts())} entities"
        )

    def reset_override(self) -> str:
        """Delete the override file so the bundled default takes effect.

        Idempotent — clean state and missing-file produce the same
        success message.
        """
        path = self.override_path
        if not path.exists():
            return "Override отсутствует, используется bundled default"
        try:
            path.unlink()
        except OSError as exc:
            return f"Сброс не удался — не могу удалить {path}: {exc}"
        return f"Override удалён ({path}), используется bundled default"

    def validate_override_message(self) -> str:
        """Local-only validation of the override file.

        TOML parse + manifest schema check. Granet (Yandex) validation
        runs at "Apply skill changes" time; this method is a quick
        sanity check before that.
        """
        path = self.override_path
        if not path.exists():
            return "Override отсутствует, нечего валидировать"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Не могу прочитать {path}: {exc}"
        try:
            manifest = parse_manifest_text(text)
        except SkillManifestError as exc:
            return f"✗ Override невалиден: {exc}"
        return (
            f"✓ Override валиден ({len(manifest.intents)} intents, "
            f"{len(manifest.to_entity_drafts())} entities)"
        )

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _storage_root(self) -> Path:
        """MA storage root, with a documented fallback.

        Tries ``mass.storage_path`` first (the path MA-core uses for
        its own state). Falls back to ``$HOME/.musicassistant`` —
        matches the path the provider already documents for log files
        in ``dialogs.py``.
        """
        attr = getattr(self._mass, "storage_path", None)
        if attr:
            return Path(attr)
        return Path.home() / ".musicassistant"

    def _bundled_manifest(self) -> SkillManifest:
        return parse_manifest_text(self._bundled_manifest_text())

    @staticmethod
    def _bundled_manifest_text() -> str:
        ref = importlib.resources.files("provider.data").joinpath("skill.toml")
        return ref.read_text(encoding="utf-8")

    @staticmethod
    def _decode_paste(paste: str) -> tuple[str, str | None]:
        """Return ``(decoded_text, error_message)``.

        On success ``error_message`` is ``None``. On base64 decode
        failure the original paste is returned alongside an
        explanation.
        """
        if not paste.startswith(_BASE64_PASTE_PREFIX):
            return paste, None
        encoded = paste.removeprefix(_BASE64_PASTE_PREFIX).strip()
        try:
            decoded_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            return paste, f"base64 декодирование не удалось: {exc}"
        try:
            return decoded_bytes.decode("utf-8"), None
        except UnicodeDecodeError as exc:
            return paste, f"декодированные данные не UTF-8: {exc}"
