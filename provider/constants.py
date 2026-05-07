"""Constants for the Yandex Alice (Dialogs custom skill) plugin provider."""

from __future__ import annotations

import logging
import os
from typing import cast

from ya_dialogs_api import DIALOG_CHANNEL as _LIB_DIALOG_CHANNEL
from ya_dialogs_api import Channel

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config entry keys (user-facing)
# ---------------------------------------------------------------------------
CONF_INSTANCE_NAME = "instance_name"
# Override for MA's webserver Base URL — used when generating callback /
# webhook URLs for Yandex. Lets users keep MA's global Base URL unset (so
# HA Ingress / local access keep working) while still exposing a public
# HTTPS URL only to Yandex via a reverse proxy.
CONF_EXTERNAL_BASE_URL = "external_base_url"
CONF_EXPOSED_PLAYERS = "exposed_players"

# Cached Yandex Passport x_token from the first successful Device Flow.
# Reused on subsequent auto-create / rename runs so the user doesn't have
# to re-confirm the device code every time. Long-lived (months);
# automatically refreshed on use. Cleared if Yandex returns 401 on refresh.
CONF_AUTH_X_TOKEN = "auth_x_token"

# Dialog skill (Yandex Dialogs custom skill — voice playback)
CONF_DIALOG_SKILL_NAME = "dialog_skill_name"
CONF_DIALOG_SKILL_ID = "dialog_skill_id"
CONF_DIALOG_SKILL_TOKEN = "dialog_skill_token"
CONF_DIALOG_WEBHOOK_SECRET = "dialog_webhook_secret"
CONF_DIALOG_AUTO_CREATE_ARTIFACTS = "dialog_auto_create_artifacts"
CONF_DIALOG_AUTO_CREATE_SESSION_ID = "dialog_auto_create_session_id"
# Persisted DeviceCodeSession (JSON) so the auto-create button can advance
# the Device Flow state machine across multiple clicks. Cleared after a
# successful poll, on expiry, or on Cancel.
CONF_DIALOG_AUTO_CREATE_DEVICE_SESSION = "dialog_auto_create_device_session"

# ---------------------------------------------------------------------------
# Config actions (config-flow buttons)
# ---------------------------------------------------------------------------
CONF_ACTION_AUTO_CREATE_DIALOG = "auto_create_dialog_skill"
CONF_ACTION_RENAME_DIALOG_SKILL = "rename_dialog_skill"
# Cancel an in-flight Device Flow / drop partial artifacts. Visible only when
# DEVICE_FLOW_STARTED or FAILED. Cached x_token is preserved across cancel.
CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW = "cancel_dialog_skill_flow"
# Test webhook reachability — outgoing POST to verify DNS + TLS + reverse proxy.
CONF_ACTION_TEST_WEBHOOK = "test_webhook_reachability"
# Regenerate the webhook URL secret. Drops the existing skill registration in
# Yandex (delete_skill) so the next auto-create starts fresh — guards against
# the user editing the webhook secret field by hand and orphaning the route.
CONF_ACTION_REGENERATE_WEBHOOK_SECRET = "regenerate_webhook_secret"
# Revert Skill name back to artifacts.last_known_name (drift undo).
CONF_ACTION_REVERT_SKILL_NAME = "revert_skill_name"

# v1.2.0 Step 2: pre-check duplicate name flow — two resolution actions.
# RECREATE: delete the existing skill in Yandex + register fresh one with
# the same name. ADOPT: skip create, position artifacts on the discovered
# skill_id and continue the pipeline (re-deploys with our backend URL).
CONF_ACTION_RECREATE_DUPLICATE = "recreate_duplicate"
CONF_ACTION_ADOPT_EXISTING = "adopt_existing"
# Hidden persistence: skill_id of the duplicate found by the pre-check
# during the previous click. When non-empty, the form renders the
# Recreate / Adopt resolution UI instead of the regular Create button.
CONF_PENDING_DUPLICATE_SKILL_ID = "pending_duplicate_skill_id"
CONF_PENDING_DUPLICATE_SKILL_NAME = "pending_duplicate_skill_name"

# v1.2.0 Step 3: edit-mode toggle + actions. Edit mode is a hidden boolean
# in form values; flipping it in/out reshapes the post-DONE section.
CONF_EDIT_MODE = "edit_mode"
CONF_ACTION_EDIT_SKILL = "edit_skill"
CONF_ACTION_UPDATE_SKILL = "update_skill"
CONF_ACTION_CANCEL_EDIT = "cancel_edit"

# Voice + activation phrases editable in edit mode (otherwise auto-derived).
CONF_DIALOG_SKILL_VOICE = "dialog_skill_voice"
CONF_DIALOG_ACTIVATION_PHRASES = "dialog_activation_phrases"

# Toggle: split-personality between MA "Instance name" (internal) and Yandex
# "Skill name" (user-facing voice trigger). Default merged — both come from
# CONF_DIALOG_SKILL_NAME. Power users can flip this to expose a separate
# CONF_INSTANCE_NAME field.
CONF_USE_DIFFERENT_INSTANCE_NAME = "use_different_instance_name"

# Yandex Dialogs catalog voice options (TTS), passed to draft payload.
# Wire values + display names extracted live from the dev console
# (https://dialogs.yandex.ru/developer → skill → Голос dropdown) on
# 2026-05-07; other strings will be rejected by the draft PATCH.
# Voice selection rarely matters for voice-control skills (the user
# hears Alice, not the skill's TTS), but we expose it for completeness.
DIALOG_VOICE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("good_oksana", "Оксана (default)"),
    ("jane", "Джейн"),
    ("zahar", "Захар"),  # noqa: RUF001
    ("ermil", "Эрмил"),
    ("erkanyavas", "Эркан Явас"),
    ("shitova.us", "Алиса"),
    ("kostya.gpu", "Костя"),
    ("valtz.gpu", "Филипп"),
    ("tatyana_abramova.gpu", "Аня"),
)
DIALOG_VOICE_DEFAULT = "good_oksana"

# ---------------------------------------------------------------------------
# Form categories (progressive disclosure)
# ---------------------------------------------------------------------------
CATEGORY_SETUP = "setup"
CATEGORY_VOICE = "voice_control"
CATEGORY_ADVANCED = "advanced"

# ---------------------------------------------------------------------------
# Webhook routing
# ---------------------------------------------------------------------------
DIALOG_WEBHOOK_BASE_PATH = "/api/yandex_dialogs/webhook"
# Maximum time the dialogs webhook handler may spend resolving / dispatching
# before it must return a response. Yandex's Alice Dialogs protocol enforces
# a 3-second hard cap; we leave 0.5s of headroom.
DIALOG_RESOLVE_TIMEOUT = 2.5

# ---------------------------------------------------------------------------
# Dialog skill metadata defaults
# ---------------------------------------------------------------------------
DIALOG_DEFAULT_NAME = "Music Assistant"
# Yandex Dialogs app-store-api channel string for the custom dialog skill.
# Captured from dev console DevTools (POST /apps): channel="aliceSkill".
# Override via MA_YANDEX_DIALOG_CHANNEL env var if Yandex changes the contract.
# Validated against ya_dialogs_api.Channel — invalid values fall back to the
# library default with a warning rather than producing a silent type lie.
_dialog_channel_raw = os.environ.get("MA_YANDEX_DIALOG_CHANNEL", _LIB_DIALOG_CHANNEL)
if _dialog_channel_raw not in ("smartHome", "aliceSkill"):
    _LOGGER.warning(
        "MA_YANDEX_DIALOG_CHANNEL=%r is not a recognised Yandex Channel "
        "wire value; falling back to %r",
        _dialog_channel_raw,
        _LIB_DIALOG_CHANNEL,
    )
    _dialog_channel_raw = _LIB_DIALOG_CHANNEL
DIALOG_CHANNEL: Channel = cast("Channel", _dialog_channel_raw)
DIALOG_NAME_MIN_LEN = 2
DIALOG_NAME_MAX_LEN = 64

# ---------------------------------------------------------------------------
# Yandex Passport / Dialogs reference URLs
# ---------------------------------------------------------------------------
YANDEX_DIALOGS_DEVELOPER_URL = "https://dialogs.yandex.ru/developer"
YANDEX_OAUTH_URL = (
    "https://oauth.yandex.ru/authorize?response_type=token"
    "&client_id=c473ca268cd749d3a8371351a8f2bcbd"
)
