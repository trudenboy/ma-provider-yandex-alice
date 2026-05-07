"""Yandex Alice (Dialogs custom skill) plugin provider for Music Assistant.

Exposes Music Assistant playback to a Yandex Dialogs custom skill — a Russian
NLU voice control surface invoked via *«Алиса, попроси Music Assistant …»*.

Setup paths:

1. **Auto** (since v1.1.0): the *Create skill* button kicks off a Yandex
   Passport Device Flow login and registers the skill in
   ``https://dialogs.yandex.ru/developer`` programmatically via
   ``ya-dialogs-api``. The skill ID is auto-populated on success.
2. **Manual** (still supported): create the skill yourself in the dev console,
   point its webhook URL at ``/api/yandex_dialogs/webhook/<your-secret>``,
   and paste the skill ID + token into the form.
"""

from __future__ import annotations

import dataclasses
import logging
import secrets
import time
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from ya_dialogs_api import (
    SkillCreationArtifacts,
    SkillCreationState,
    dump_artifacts,
    load_artifacts,
)

from .auto_create import (
    AutoCreateOutcome,
    LocalAutoCreateStage,
    deserialize_device_session,
    run_auto_create_step,
)
from .auto_create_view import build_auto_create_entries
from .auto_update import run_auto_update
from .constants import (
    CATEGORY_ADVANCED,
    CATEGORY_SETUP,
    CATEGORY_VOICE,
    CONF_ACTION_AUTO_CREATE_DIALOG,
    CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
    CONF_ACTION_REGENERATE_WEBHOOK_SECRET,
    CONF_ACTION_RENAME_DIALOG_SKILL,
    CONF_ACTION_REVERT_SKILL_NAME,
    CONF_ACTION_TEST_WEBHOOK,
    CONF_AUTH_X_TOKEN,
    CONF_DIALOG_AUTO_CREATE_ARTIFACTS,
    CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION,
    CONF_DIALOG_SKILL_ENABLED,
    CONF_DIALOG_SKILL_ID,
    CONF_DIALOG_SKILL_NAME,
    CONF_DIALOG_SKILL_TOKEN,
    CONF_DIALOG_WEBHOOK_SECRET,
    CONF_EXPOSED_PLAYERS,
    CONF_EXPOSED_PLAYLISTS,
    CONF_EXTERNAL_BASE_URL,
    CONF_INSTANCE_NAME,
    CONF_USE_DIFFERENT_INSTANCE_NAME,
    DIALOG_DEFAULT_NAME,
    DIALOG_NAME_MAX_LEN,
    DIALOG_NAME_MIN_LEN,
    DIALOG_WEBHOOK_BASE_PATH,
    YANDEX_DIALOGS_DEVELOPER_URL,
)
from .dialog_skill_meta import (
    build_activation_phrases,
    build_backend_uri,
    build_skill_description,
    build_structured_examples,
    validate_skill_name,
)
from .playlists import fetch_playlist_options
from .plugin import YandexAlicePlugin
from .url_helpers import is_public_https_url, try_detect_public_https_url
from .webhook_probe import probe_webhook_reachability

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(
    mass: MusicAssistant,
    manifest: ProviderManifest,
    config: ProviderConfig,
) -> ProviderInstanceType:
    """Initialise the provider instance with the given configuration."""
    return YandexAlicePlugin(mass, manifest, config, SUPPORTED_FEATURES)


def _generate_webhook_secret() -> str:
    """Return a fresh URL-safe random secret for the webhook path."""
    return secrets.token_urlsafe(24)


async def _list_player_options(mass: MusicAssistant) -> list[ConfigValueOption]:
    """List MA players the user can expose to voice control."""
    options: list[ConfigValueOption] = []
    try:
        for player in mass.players.all_players():
            options.append(
                ConfigValueOption(
                    title=player.display_name or player.name or player.player_id,
                    value=player.player_id,
                )
            )
    except Exception as exc:
        _LOGGER.debug("could not enumerate players: %s", exc)
    return options


def _name_drifted(artifacts: SkillCreationArtifacts, skill_name: str) -> bool:
    """Detect divergence between MA-side `skill_name` and Yandex `last_known_name`."""
    return bool(
        artifacts.last_known_name and artifacts.last_known_name.strip() != skill_name.strip()
    )


def _build_diagnostics_entries(
    mass: MusicAssistant, instance_id: str | None
) -> tuple[ConfigEntry, ...]:
    """Render runtime stats from the loaded plugin instance (#17).

    Reads counters off the running ``YandexAlicePlugin`` (set in
    ``handle_async_init`` / updated in the webhook handler). When the
    provider is not loaded yet (config-edit before first save) we render
    a single placeholder LABEL so users know diagnostics is available.
    """
    if not instance_id:
        return ()
    try:
        plugin = mass.get_provider(instance_id)
    except Exception:
        return ()
    if plugin is None or not isinstance(plugin, YandexAlicePlugin):
        return ()

    stats = plugin.get_diagnostics()
    handler_active = bool(stats.get("handler_active"))
    if not handler_active:
        return (
            ConfigEntry(
                key="label_diagnostics_inactive",
                type=ConfigEntryType.LABEL,
                label=(
                    "Diagnostics: webhook handler not active "
                    "(skill disabled or credentials missing)."
                ),
                advanced=True,
                category=CATEGORY_ADVANCED,
            ),
        )

    webhook_calls = int(stats.get("webhook_calls_total") or 0)
    intent_calls = int(stats.get("intent_calls_total") or 0)
    last_ts_raw = stats.get("last_webhook_ts")
    if isinstance(last_ts_raw, (int, float)) and last_ts_raw > 0:
        delta = max(0, int(time.time() - last_ts_raw))
        if delta < 60:
            last_ago = f"{delta} sec ago"
        elif delta < 3600:
            last_ago = f"{delta // 60} min ago"
        else:
            last_ago = f"{delta // 3600} h ago"
    else:
        last_ago = "never"

    summary = (
        f"Diagnostics: {webhook_calls} webhook hits ({intent_calls} valid "
        f"intents) · last webhook {last_ago}."
    )
    return (
        ConfigEntry(
            key="label_diagnostics_summary",
            type=ConfigEntryType.LABEL,
            label=summary,
            advanced=True,
            category=CATEGORY_ADVANCED,
        ),
    )


def _build_instance_name_section(
    *, instance_name: str, skill_name: str, use_different: bool
) -> tuple[ConfigEntry, ...]:
    """Render the Instance-name split toggle + conditional field (#1).

    Default is *merged* — the Yandex skill name doubles as the MA-side
    instance name. Toggle this on to split them (rare; useful when an
    install was created before v1.2.0 with different values).
    """
    entries: list[ConfigEntry] = [
        ConfigEntry(
            key=CONF_USE_DIFFERENT_INSTANCE_NAME,
            type=ConfigEntryType.BOOLEAN,
            label="Use a different MA-side instance name",
            description=(
                "By default the Skill name above is also used as the "
                "instance name shown in Music Assistant's provider list. "
                "Turn this on to specify a different MA-side name (e.g. "
                "to keep the skill name short for voice but show a "
                "longer label in MA settings)."
            ),
            required=False,
            default_value=False,
            advanced=True,
            category=CATEGORY_ADVANCED,
        ),
    ]
    if use_different:
        entries.append(
            ConfigEntry(
                key=CONF_INSTANCE_NAME,
                type=ConfigEntryType.STRING,
                label="Instance name (MA-side display)",
                description=(
                    "Display name shown in Music Assistant's provider list. "
                    "Independent from the Skill name (which is what users "
                    "say to Alice)."
                ),
                required=False,
                default_value=instance_name or DIALOG_DEFAULT_NAME,
                advanced=True,
                category=CATEGORY_ADVANCED,
                depends_on=CONF_USE_DIFFERENT_INSTANCE_NAME,
                depends_on_value=True,
            )
        )
    else:
        # Hidden carrier so MA still has a value to use in display contexts;
        # always tracks skill_name when the toggle is off.
        entries.append(
            ConfigEntry(
                key=CONF_INSTANCE_NAME,
                type=ConfigEntryType.STRING,
                label="Instance name (auto)",
                required=False,
                default_value=skill_name or DIALOG_DEFAULT_NAME,
                hidden=True,
            )
        )
    return tuple(entries)


def _build_rename_cluster(
    *,
    artifacts: SkillCreationArtifacts,
    cached_x_token: str,
    skill_name: str,
    update_message: str | None,
) -> tuple[ConfigEntry, ...]:
    """Render the rename / drift-sync action cluster (#13).

    Visible only when the skill exists *and* we have a cached x_token (so a
    rename can run without a fresh Device Flow). When the MA-side
    ``Skill name`` differs from ``artifacts.last_known_name``, a multi-line
    preview tells the user exactly what activation phrase will change and
    offers a "Revert" button to abandon the half-typed rename.
    """
    if not (artifacts.skill_id and cached_x_token):
        return ()

    drifted = _name_drifted(artifacts, skill_name)
    entries: list[ConfigEntry] = []

    if update_message:
        entries.append(
            ConfigEntry(
                key="label_rename_outcome",
                type=ConfigEntryType.LABEL,
                label=update_message,
            )
        )

    if drifted and artifacts.last_known_name:
        old = artifacts.last_known_name
        entries.append(
            ConfigEntry(
                key="label_rename_drift_header",
                type=ConfigEntryType.LABEL,
                label=(
                    f"⚠ Skill name in Yandex is «{old}», but the field above says «{skill_name}»."
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key="label_rename_drift_phrase",
                type=ConfigEntryType.LABEL,
                label=(
                    f"  Renaming will change the activation phrase from "
                    f"«Алиса, попроси {old} …» to «Алиса, попроси {skill_name} …»."
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key="label_rename_drift_moderation",
                type=ConfigEntryType.LABEL,
                label=(
                    "  Yandex moderation: 5-15 min. Existing voice commands "
                    "keep working during moderation."
                ),
            )
        )

    entries.append(
        ConfigEntry(
            key=CONF_ACTION_RENAME_DIALOG_SKILL,
            type=ConfigEntryType.ACTION,
            label="Rename skill in Yandex",
            description=(
                "Apply the current 'Skill name' value to the existing "
                "skill in Yandex Dialogs (PATCH draft + re-deploy). "
                "Uses the cached x_token — no re-authentication required."
            ),
            action=CONF_ACTION_RENAME_DIALOG_SKILL,
            action_label="Apply rename",
            required=False,
            default_value="",
        )
    )

    if drifted and artifacts.last_known_name:
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_REVERT_SKILL_NAME,
                type=ConfigEntryType.ACTION,
                label="Revert skill name",
                description=(
                    f"Discards your edit and restores «{artifacts.last_known_name}» "
                    "into the Skill name field above. No Yandex API calls."
                ),
                action=CONF_ACTION_REVERT_SKILL_NAME,
                action_label=f"Revert to «{artifacts.last_known_name}»",
                required=False,
                default_value="",
            )
        )

    return tuple(entries)


def _build_identity_card_entries(
    artifacts: SkillCreationArtifacts,
    webhook_secret: str,
    external_base_url: str,
    is_configured: bool,
) -> tuple[ConfigEntry, ...]:
    """Render a compact "identity card" once the skill is registered + on-air.

    Replaces the bare ``Skill ID`` / ``Webhook URL secret`` editable inputs at
    the top of the form with a read-only summary: skill name, skill UUID,
    full webhook URL (copyable), and a ``help_link`` shortcut to the dev
    console. The original input fields are still rendered below this card —
    moved to ``advanced=True`` and ``read_only=True`` (see callers) so manual
    edits stay possible but don't clutter the default view.
    """
    if not is_configured or not artifacts.skill_id:
        return ()

    base = (external_base_url or "").rstrip("/")
    full_webhook_url = (
        f"{base}{DIALOG_WEBHOOK_BASE_PATH}/{webhook_secret}" if base else "(not assembled)"
    )
    dev_console_url = f"https://dialogs.yandex.ru/developer/skills/{artifacts.skill_id}"
    skill_label = artifacts.last_known_name or "(name unknown)"

    return (
        ConfigEntry(
            key="label_identity_card_header",
            type=ConfigEntryType.LABEL,
            label=f"✓ Configured: «{skill_label}» — Skill ID: {artifacts.skill_id}",
        ),
        ConfigEntry(
            key="label_identity_card_webhook",
            type=ConfigEntryType.LABEL,
            label=f"Webhook URL (copy into Yandex Dialogs if asked): {full_webhook_url}",
        ),
        ConfigEntry(
            key="label_identity_card_dev_console",
            type=ConfigEntryType.LABEL,
            label=f"Open in Yandex Dialogs dev console: {dev_console_url}",
            help_link=dev_console_url,
        ),
    )


def _resolve_saved_value(
    values: dict[str, ConfigValueType],
    key: str,
) -> str:
    """Read a config value from form ``values`` (string-coerced).

    Earlier versions also fell through to ``mass.config.get_provider_config``
    for keys the frontend may not echo back. That call deadlocks against the
    config controller's own lock when MA opens the provider settings page —
    `get_config_entries` is invoked by MA *while* it holds the config lock,
    and the recursive read blocks indefinitely. So we now rely solely on
    ``values``, and stabilise critical SECURE_STRING fields by writing the
    derived value back into ``values`` early in the dispatcher (so subsequent
    action clicks within the same form session see the same value).
    """
    return str(values.get(key) or "")


async def get_config_entries(  # noqa: PLR0915
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """Build the provider config-form entries with auto-create / rename actions.

    Action handling:

    - ``CONF_ACTION_AUTO_CREATE_DIALOG`` — advance the Device Flow + skill
      creation state machine by one external-IO step. Re-click drives further
      stages (see :mod:`provider.auto_create`).
    - ``CONF_ACTION_RENAME_DIALOG_SKILL`` — patch the existing skill draft
      via cached x_token; no Device Flow.
    - ``CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW`` — drop pending session +
      reset artifacts; preserve cached x_token.

    Auto-create / rename state lives in three hidden config entries
    (``CONF_AUTH_X_TOKEN``, ``CONF_DIALOG_AUTO_CREATE_ARTIFACTS``,
    ``CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION``) that round-trip through the
    form on every save.
    """
    values = values or {}

    # Generate a webhook secret on first open if the user hasn't set one yet.
    # Read through saved provider config too: the frontend may not echo
    # SECURE_STRING fields between action clicks, and regenerating the
    # secret per call would orphan webhooks already registered with Yandex
    # against an earlier (now-discarded) secret.
    _ = instance_id  # reserved for future per-instance config lookups
    existing_secret = _resolve_saved_value(values, CONF_DIALOG_WEBHOOK_SECRET).strip()
    default_secret = existing_secret or _generate_webhook_secret()
    # Stabilise inside this dispatch: any backend_uri assembled below uses
    # the same secret as the form will save on user click.
    values[CONF_DIALOG_WEBHOOK_SECRET] = default_secret

    instance_name = str(values.get(CONF_INSTANCE_NAME) or DIALOG_DEFAULT_NAME)

    # ---- Pull persistent auto-create / auth state ----
    artifacts = load_artifacts(
        _resolve_saved_value(values, CONF_DIALOG_AUTO_CREATE_ARTIFACTS) or None
    )
    cached_x_token = _resolve_saved_value(values, CONF_AUTH_X_TOKEN)
    device_session_blob = _resolve_saved_value(values, CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION)

    # Auto-clear stale Device Flow session — the user closed the form mid-flow
    # and the user_code has since expired. Otherwise the form on reopen would
    # show a "Confirm and continue" button against a long-dead code, with no
    # path to recover except clicking Cancel. Drop it silently here so the
    # next render shows a clean IDLE state.
    if device_session_blob:
        decoded = deserialize_device_session(device_session_blob)
        if decoded is not None and decoded[1] <= time.time():
            device_session_blob = ""
            values[CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION] = ""

    # Skill name priority: explicit dialog skill name → instance name → default.
    skill_name = (
        str(values.get(CONF_DIALOG_SKILL_NAME) or "").strip()
        or str(values.get(CONF_INSTANCE_NAME) or "").strip()
        or DIALOG_DEFAULT_NAME
    )

    external_base_url = str(values.get(CONF_EXTERNAL_BASE_URL) or "").strip().rstrip("/")
    webhook_secret = default_secret

    action_outcome: AutoCreateOutcome | None = None
    update_message: str | None = None

    # ---- Action dispatcher ----
    if action == CONF_ACTION_AUTO_CREATE_DIALOG:
        # Treat re-click on DONE as "Re-create" → reset artifacts before stepping.
        if artifacts.state == SkillCreationState.DONE:
            artifacts = SkillCreationArtifacts()
            device_session_blob = ""

        # Backup-restore safety: skill_id is set in config but artifacts are
        # NONE → pre-position to APP_CREATED so the library skips create_app
        # and patches the existing skill rather than creating a duplicate.
        saved_skill_id = str(values.get(CONF_DIALOG_SKILL_ID) or "").strip()
        if saved_skill_id and artifacts.state == SkillCreationState.NONE and not artifacts.skill_id:
            artifacts = dataclasses.replace(
                artifacts,
                state=SkillCreationState.APP_CREATED,
                skill_id=saved_skill_id,
            )

        try:
            backend_uri = build_backend_uri(external_base_url, webhook_secret)
        except ValueError as exc:
            action_outcome = AutoCreateOutcome(
                artifacts=dataclasses.replace(
                    artifacts,
                    state=SkillCreationState.FAILED,
                    last_error=str(exc),
                ),
                device_session_blob=None,
                x_token=None,
                user_code=None,
                verification_url=None,
                user_message=str(exc),
                stage=LocalAutoCreateStage.FAILED,
            )
        else:
            action_outcome = await run_auto_create_step(
                skill_name=skill_name,
                backend_uri=backend_uri,
                description=build_skill_description(skill_name),
                structured_examples=build_structured_examples(skill_name),
                activation_phrases=build_activation_phrases(skill_name),
                cached_x_token=cached_x_token or None,
                pending_device_session_blob=device_session_blob or None,
                artifacts=artifacts,
            )

    elif action == CONF_ACTION_RENAME_DIALOG_SKILL:
        try:
            backend_uri = build_backend_uri(external_base_url, webhook_secret)
        except ValueError as exc:
            update_message = str(exc)
            artifacts = dataclasses.replace(
                artifacts,
                state=SkillCreationState.FAILED,
                last_error=str(exc),
            )
        else:
            update_outcome = await run_auto_update(
                cached_x_token=cached_x_token or None,
                skill_name=skill_name,
                backend_uri=backend_uri,
                description=build_skill_description(skill_name),
                structured_examples=build_structured_examples(skill_name),
                activation_phrases=build_activation_phrases(skill_name),
                artifacts=artifacts,
            )
            artifacts = update_outcome.artifacts
            update_message = update_outcome.user_message
            if update_outcome.x_token == "":
                cached_x_token = ""

    elif action == CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW:
        # Drop pending session + reset artifacts; keep cached x_token.
        artifacts = SkillCreationArtifacts()
        device_session_blob = ""

    elif action == CONF_ACTION_REGENERATE_WEBHOOK_SECRET:
        # Webhook secret rotation: invalidates the URL Yandex was registered
        # against, so the existing skill's webhook would 404. Reset everything
        # and force the user back through auto-create with a fresh secret —
        # cached x_token is preserved so the second pass skips Passport login.
        default_secret = _generate_webhook_secret()
        values[CONF_DIALOG_WEBHOOK_SECRET] = default_secret
        webhook_secret = default_secret
        artifacts = SkillCreationArtifacts()
        device_session_blob = ""
        values[CONF_DIALOG_SKILL_ID] = ""
        update_message = (
            "Webhook secret regenerated. Click 'Sign in to Yandex Passport' "
            "to register a fresh skill against the new URL."
        )

    elif action == CONF_ACTION_TEST_WEBHOOK:
        # Reachability probe — does Yandex's traffic actually land in our
        # handler? Returns ``(ok, message)`` ready for an inline LABEL.
        reachable, msg = await probe_webhook_reachability(external_base_url, webhook_secret)
        update_message = ("✓ " if reachable else "✗ ") + msg

    elif action == CONF_ACTION_REVERT_SKILL_NAME:
        # Drift undo (#13) — copy artifacts.last_known_name back into the
        # form field so the user can abandon a half-typed rename and go
        # back to whatever Yandex currently has.
        if artifacts.last_known_name:
            values[CONF_DIALOG_SKILL_NAME] = artifacts.last_known_name
            update_message = (
                f"Skill name reverted to «{artifacts.last_known_name}» "
                "(matches the value currently registered with Yandex)."
            )
        else:
            update_message = "Nothing to revert — no last-known name on record yet."

    # ---- Reflect outcome into values so the next form save persists state ----
    if action_outcome is not None:
        artifacts = action_outcome.artifacts
        if action_outcome.device_session_blob is not None:
            device_session_blob = action_outcome.device_session_blob
        elif action_outcome.stage in (
            LocalAutoCreateStage.DONE,
            LocalAutoCreateStage.FAILED,
        ):
            device_session_blob = ""
        if action_outcome.x_token is not None:
            cached_x_token = action_outcome.x_token

    values[CONF_DIALOG_AUTO_CREATE_ARTIFACTS] = dump_artifacts(artifacts)
    values[CONF_AUTH_X_TOKEN] = cached_x_token
    values[CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION] = device_session_blob
    if artifacts.state == SkillCreationState.DONE and artifacts.skill_id:
        values[CONF_DIALOG_SKILL_ID] = artifacts.skill_id
        # Auto-enable voice control on first DONE — the user has just been
        # through the whole flow, leaving the skill disabled afterwards is
        # confusing UX (#2). Power users can still flip it off in the form
        # afterwards.
        if not values.get(CONF_DIALOG_SKILL_ENABLED):
            values[CONF_DIALOG_SKILL_ENABLED] = True

    is_configured = artifacts.state == SkillCreationState.DONE and bool(artifacts.skill_id)

    # ---- Player / playlist options ----
    player_options = await _list_player_options(mass)
    try:
        playlist_options = await fetch_playlist_options(mass)
    except Exception as exc:
        _LOGGER.debug("could not enumerate playlists: %s", exc)
        playlist_options = []

    # ---- External base URL: autodetect (#8) + inline HTTPS warning ----
    user_supplied_base_url = str(values.get(CONF_EXTERNAL_BASE_URL) or "").strip()
    if not user_supplied_base_url:
        detected = try_detect_public_https_url(mass)
        if detected:
            values[CONF_EXTERNAL_BASE_URL] = detected
            external_base_url = detected
            base_url_description = (
                f"Auto-detected from Music Assistant settings: {detected}. "
                "Edit if you use a different reverse-proxy URL."
            )
        else:
            base_url_description = (
                "Public HTTPS URL of this Music Assistant instance — the "
                "address Yandex will use to reach the webhook. "
                "Examples: https://ma.example.com, https://ha.example.com. "
                "Required for auto-create."
            )
    elif not is_public_https_url(user_supplied_base_url):
        base_url_description = (
            "✗ This URL is not a public HTTPS endpoint — Yandex requires "
            "https:// and a non-private host. Auto-create will refuse this. "
            f"Got: {user_supplied_base_url!r}"
        )
    else:
        base_url_description = (
            f"Public HTTPS URL: {user_supplied_base_url}. "
            "Click 'Test webhook' below to verify Yandex can reach it."
        )

    # ---- Auto-create cluster: status LABEL + auto-create ACTION + Cancel ----
    # Surface the pending session details so the LABEL can re-show the
    # user_code + verification URL + countdown after a form reload mid-Device-Flow.
    pending_user_code: str | None = None
    pending_verification_url: str | None = None
    pending_expires_at_epoch: float | None = None
    if device_session_blob:
        decoded = deserialize_device_session(device_session_blob)
        if decoded is not None:
            pending_user_code = decoded[0].user_code
            pending_verification_url = decoded[0].verification_url
            pending_expires_at_epoch = decoded[1]

    auto_create_entries = build_auto_create_entries(
        artifacts=artifacts,
        pending_session_present=bool(device_session_blob),
        cached_x_token_present=bool(cached_x_token),
        action_outcome=action_outcome,
        pending_user_code=pending_user_code,
        pending_verification_url=pending_verification_url,
        pending_expires_at_epoch=pending_expires_at_epoch,
        skill_name_for_examples=skill_name,
    )

    # ---- Rename cluster: drift LABELs (preview + #13 revert) + Rename ACTION ----
    rename_entries = _build_rename_cluster(
        artifacts=artifacts,
        cached_x_token=cached_x_token,
        skill_name=skill_name,
        update_message=update_message,
    )

    # ---- Hidden state-carrier entries (round-trip persistence) ----
    hidden_state_entries = (
        ConfigEntry(
            key=CONF_AUTH_X_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Yandex Passport x_token (cached)",
            description="Cached after first successful Device Flow.",
            required=False,
            default_value=cached_x_token,
            hidden=True,
        ),
        ConfigEntry(
            key=CONF_DIALOG_AUTO_CREATE_ARTIFACTS,
            type=ConfigEntryType.STRING,
            label="Auto-create artifacts (JSON)",
            description="State machine snapshot — persisted between clicks.",
            required=False,
            default_value=dump_artifacts(artifacts),
            hidden=True,
        ),
        ConfigEntry(
            key=CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION,
            type=ConfigEntryType.SECURE_STRING,
            label="Pending Device Flow session (JSON)",
            description="Persisted during DEVICE_FLOW_STARTED stage.",
            required=False,
            default_value=device_session_blob,
            hidden=True,
        ),
    )

    # ---- Diagnostics LABEL (Advanced section) — pulled from running plugin ----
    diagnostics_entries = _build_diagnostics_entries(mass, instance_id)

    # ---- Instance-name split toggle (#1) — power users only, default merged ----
    use_different_instance_name = bool(values.get(CONF_USE_DIFFERENT_INSTANCE_NAME, False))
    instance_name_section = _build_instance_name_section(
        instance_name=instance_name,
        skill_name=skill_name,
        use_different=use_different_instance_name,
    )

    return (
        # ===== Setup section =====
        ConfigEntry(
            key="label_intro",
            type=ConfigEntryType.LABEL,
            label=(
                "Yandex Alice voice control. Sign in to Yandex Passport "
                "below — Music Assistant will register a custom dialog "
                f"skill at {YANDEX_DIALOGS_DEVELOPER_URL} on your behalf."
            ),
            category=CATEGORY_SETUP,
        ),
        ConfigEntry(
            key=CONF_DIALOG_SKILL_NAME,
            type=ConfigEntryType.STRING,
            label="Skill name",
            description=(
                "At least 2 words. Globally unique across all Yandex skills. "
                "Examples: 'Music Assistant', 'Музыкальный Ассистент', "
                "'Домашняя Музыка'. "
                f"Min {DIALOG_NAME_MIN_LEN}, max {DIALOG_NAME_MAX_LEN} characters."
            ),
            required=False,
            default_value=instance_name,
            validate=validate_skill_name,
            category=CATEGORY_SETUP,
        ),
        ConfigEntry(
            key=CONF_EXTERNAL_BASE_URL,
            type=ConfigEntryType.STRING,
            label="External base URL (HTTPS, required for auto-create)",
            description=base_url_description,
            required=False,
            default_value="",
            category=CATEGORY_SETUP,
        ),
        ConfigEntry(
            key=CONF_ACTION_TEST_WEBHOOK,
            type=ConfigEntryType.ACTION,
            label="Test webhook reachability",
            description=(
                "Sends a sentinel POST to <external_base_url>"
                f"{DIALOG_WEBHOOK_BASE_PATH}/<secret> and reports the "
                "result. Catches DNS / TLS / reverse-proxy issues *before* "
                "you spend a Device Flow + Yandex moderation cycle."
            ),
            action=CONF_ACTION_TEST_WEBHOOK,
            action_label="Test webhook",
            required=False,
            default_value="",
            category=CATEGORY_SETUP,
        ),
        *auto_create_entries,
        *rename_entries,
        *_build_identity_card_entries(artifacts, default_secret, external_base_url, is_configured),
        # ===== Voice control section =====
        ConfigEntry(
            key=CONF_EXPOSED_PLAYERS,
            type=ConfigEntryType.STRING,
            label="Voice-controllable players",
            description=(
                "Players the skill is allowed to control. Leave empty to "
                "expose all players known to MA — Alice will then accept "
                "voice commands for any player by name."
            ),
            multi_value=True,
            options=player_options,
            required=False,
            default_value=[],
            category=CATEGORY_VOICE,
        ),
        ConfigEntry(
            key=CONF_EXPOSED_PLAYLISTS,
            type=ConfigEntryType.STRING,
            label="Voice-addressable playlists",
            description=(
                "Optional curated list of playlists the user can ask for by "
                "name. Leave empty for full library search."
            ),
            multi_value=True,
            options=playlist_options,
            required=False,
            default_value=[],
            category=CATEGORY_VOICE,
        ),
        ConfigEntry(
            key=CONF_DIALOG_SKILL_ENABLED,
            type=ConfigEntryType.BOOLEAN,
            label="Enable voice control",
            description=(
                "Turn off to temporarily mute the skill (the webhook stops "
                "responding to Yandex). Auto-enabled after a successful "
                "skill creation."
            ),
            required=False,
            default_value=False,
            category=CATEGORY_VOICE,
        ),
        # ===== Advanced section =====
        *instance_name_section,
        ConfigEntry(
            key=CONF_DIALOG_SKILL_ID,
            type=ConfigEntryType.STRING,
            label="Skill ID",
            description=(
                "UUID of the skill — populated automatically after a "
                "successful auto-create, or paste manually if you set up "
                "the skill yourself."
            ),
            required=False,
            default_value="",
            read_only=is_configured,
            advanced=True,
            category=CATEGORY_ADVANCED,
        ),
        ConfigEntry(
            key=CONF_DIALOG_SKILL_TOKEN,
            type=ConfigEntryType.SECURE_STRING,
            label="Skill OAuth token (manual setup only)",
            description=(
                "Optional OAuth token from "
                "https://oauth.yandex.ru/authorize?response_type=token"
                "&client_id=c473ca268cd749d3a8371351a8f2bcbd. "
                "Used to push state callbacks to Yandex (future feature; "
                "stored encrypted)."
            ),
            help_link=(
                "https://oauth.yandex.ru/authorize?response_type=token"
                "&client_id=c473ca268cd749d3a8371351a8f2bcbd"
            ),
            required=False,
            default_value="",
            advanced=True,
            category=CATEGORY_ADVANCED,
        ),
        ConfigEntry(
            key=CONF_DIALOG_WEBHOOK_SECRET,
            type=ConfigEntryType.SECURE_STRING,
            label="Webhook URL secret",
            description=(
                "Random secret embedded in the webhook URL. The full URL is "
                f"<external_base_url>{DIALOG_WEBHOOK_BASE_PATH}/<this-secret>. "
                "Pre-filled with a fresh value; click 'Save' to commit. "
                "Locked once Yandex has been registered against this secret — "
                "use 'Regenerate webhook secret' below to rotate."
                if is_configured
                else "Random secret embedded in the webhook URL. The full URL is "
                f"<external_base_url>{DIALOG_WEBHOOK_BASE_PATH}/<this-secret>. "
                "Pre-filled with a fresh value; click 'Save' to commit."
            ),
            required=False,
            default_value=default_secret,
            read_only=is_configured,
            advanced=True,
            category=CATEGORY_ADVANCED,
        ),
        *(
            (
                ConfigEntry(
                    key=CONF_ACTION_REGENERATE_WEBHOOK_SECRET,
                    type=ConfigEntryType.ACTION,
                    label="Regenerate webhook secret",
                    description=(
                        "Generates a fresh secret + resets the auto-create "
                        "state. The current Yandex skill registration becomes "
                        "stale — you'll need to re-run 'Sign in' to register "
                        "the new webhook URL. Cached Passport login is kept."
                    ),
                    action=CONF_ACTION_REGENERATE_WEBHOOK_SECRET,
                    action_label="Regenerate (forces re-create)",
                    required=False,
                    default_value="",
                    advanced=True,
                    category=CATEGORY_ADVANCED,
                ),
            )
            if is_configured
            else ()
        ),
        *diagnostics_entries,
        *hidden_state_entries,
    )
