r"""Pure rendering of the 3-step setup UI from state.

The form is structured around three sequential **visual sections**, one
of which is active at any time:

1. **Authenticate** — IDLE without cached_x_token, OR DEVICE_FLOW_STARTED.
   The user signs in to Yandex Passport via Device Flow (custom
   ``user_code`` page handed off to ``AuthenticationHelper`` in the FE).
2. **Create skill** — IDLE with cached_x_token, OR PIPELINE_RUNNING, OR
   FAILED post-auth, OR DUPLICATE_DETECTED. The user presses *Create
   skill* once we have a Passport session; the pipeline pre-checks for
   a name collision in Yandex and offers Recreate / Adopt if it finds
   one.
3. **Skill registered** — DONE. Identity-card view + an *Edit skill*
   toggle that flips the section into edit mode (skill_name +
   activation_phrases + voice editable, with *Update skill* / *Cancel*
   action buttons).

Decoupled from the dispatcher (``provider.__init__`` uses these helpers
verbatim) so the form-shape can be unit-tested without exercising the
actual orchestrator.

Rendering style: **plain text + Unicode emoji**. Phase 0 confirmed that
Music Assistant's frontend renders ``ConfigEntry(LABEL)`` text inside a
Vuetify ``v-alert`` with ``white-space: normal`` — markdown (``**bold**``
/ ``*italic*`` / `` `code` ``) is shown literally and ``\n`` newlines
collapse into spaces. We compensate by:

- Splitting multi-line content into **multiple LABEL entries** (each one
  is a separate v-alert block, so the user sees them as visually
  distinct rows).
- Using Unicode emoji + ALL CAPS / ``«guillemets»`` / square-bracket
  prefixes for visual emphasis.
"""

from __future__ import annotations

from music_assistant_models.config_entries import ConfigEntry, ConfigValueOption
from music_assistant_models.enums import ConfigEntryType
from ya_dialogs_api import SkillCreationArtifacts, SkillCreationState

from .auto_create import AutoCreateOutcome, LocalAutoCreateStage
from .constants import (
    CONF_ACTION_ADOPT_EXISTING,
    CONF_ACTION_AUTO_CREATE_DIALOG,
    CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
    CONF_ACTION_CANCEL_EDIT,
    CONF_ACTION_EDIT_SKILL,
    CONF_ACTION_RECREATE_DUPLICATE,
    CONF_ACTION_TEST_WEBHOOK,
    CONF_ACTION_UPDATE_SKILL,
    CONF_DIALOG_ACTIVATION_PHRASES,
    CONF_DIALOG_SKILL_NAME,
    CONF_DIALOG_SKILL_VOICE,
    CONF_EXTERNAL_BASE_URL,
    DIALOG_VOICE_DEFAULT,
    DIALOG_VOICE_OPTIONS,
    DIALOG_WEBHOOK_BASE_PATH,
)

__all__ = [
    "build_auto_create_entries",
    "derive_active_step",
]


# ---------------------------------------------------------------------------
# Step routing
# ---------------------------------------------------------------------------


def derive_active_step(
    *,
    artifacts: SkillCreationArtifacts,
    cached_x_token_present: bool,
) -> int:
    """Return 1, 2, or 3 — which top-level section is rendered now.

    - **Step 1 (Authenticate)**: no cached x_token. Until the user
      has signed in we cannot proceed; everything else is hidden so
      the form can't outrun Yandex Passport.
    - **Step 3 (Skill registered)**: artifacts in ``DONE`` state —
      the skill exists at Yandex's side, we move to the post-create
      identity card.
    - **Step 2 (Create skill)**: everything in between.
    """
    if not cached_x_token_present:
        return 1
    if artifacts.state == SkillCreationState.DONE:
        return 3
    return 2


def _derive_stage(
    *,
    artifacts: SkillCreationArtifacts,
    cached_x_token_present: bool,
    duplicate_pending: bool,
) -> LocalAutoCreateStage:
    """Derive the legacy stage enum from persistent state.

    Used for the Step 2 button-label / section variant routing.
    ``duplicate_pending`` is a transient flag from the dispatcher
    (set when ``run_create_skill`` returned ``DUPLICATE_DETECTED`` on
    the previous click — persisted via a hidden config entry).
    """
    if duplicate_pending:
        return LocalAutoCreateStage.DUPLICATE_DETECTED
    if artifacts.state == SkillCreationState.DONE:
        return LocalAutoCreateStage.DONE
    if artifacts.state == SkillCreationState.FAILED:
        return LocalAutoCreateStage.FAILED
    if cached_x_token_present and artifacts.state in (
        SkillCreationState.APP_CREATED,
        SkillCreationState.DRAFT_UPDATED,
        SkillCreationState.OAUTH_CREATED,
        SkillCreationState.OAUTH_ATTACHED,
        SkillCreationState.DEPLOY_REQUESTED,
    ):
        return LocalAutoCreateStage.PIPELINE_RUNNING
    return LocalAutoCreateStage.IDLE


# ---------------------------------------------------------------------------
# Step 1 — Authenticate
# ---------------------------------------------------------------------------


def _render_step1_auth_section(
    *,
    last_error: str | None,
) -> tuple[ConfigEntry, ...]:
    """Render the *Authenticate* section.

    Single state: friendly intro + *Sign in to Yandex Passport*
    button. The click is **blocking** — the dispatcher hands off to
    :func:`provider.auth_page.perform_device_auth` which opens an
    AuthenticationHelper popup, displays the user_code, and waits
    until Yandex confirms (or the code expires). On success the
    captured ``x_token`` is written to ``values`` and the form
    re-renders into Step 2.

    ``last_error`` (post-failure) is surfaced above the action so
    the user understands why the form snapped back to Step 1.
    """
    entries: list[ConfigEntry] = [
        ConfigEntry(
            key="label_step1_header",
            type=ConfigEntryType.LABEL,
            label="STEP 1 / 3 · Sign in to Yandex Passport",
        ),
    ]

    if last_error:
        entries.append(
            ConfigEntry(
                key="label_step1_last_error",
                type=ConfigEntryType.LABEL,
                label=f"✗ {last_error}",
            )
        )

    entries.append(
        ConfigEntry(
            key="label_step1_intro",
            type=ConfigEntryType.LABEL,
            label=(
                "Click 'Sign in to Yandex Passport' below — Music "
                "Assistant will open a sign-in popup with a short "
                "verification code that you confirm in your Yandex "
                "account. You only need to do this once per install."
            ),
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_ACTION_AUTO_CREATE_DIALOG,
            type=ConfigEntryType.ACTION,
            label="Sign in to Yandex Passport",
            description=(
                "Starts the Yandex Passport Device Flow. We never "
                "see your password — Yandex hands us a long-lived "
                "x_token only after you confirm the code in the "
                "popup window."
            ),
            action=CONF_ACTION_AUTO_CREATE_DIALOG,
            action_label="Sign in to Yandex Passport",
            required=False,
            default_value="",
        )
    )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Step 2 — Create skill
# ---------------------------------------------------------------------------


def _build_external_base_url_entries(
    *,
    external_base_url: str,
    description: str,
    is_valid: bool,
) -> tuple[ConfigEntry, ...]:
    """Render the external base URL field inline at Step 2.

    The URL is required before the user can click *Create skill* — we
    surface it directly inside the step rather than buried in a Setup
    section. ``description`` is the contextual hint (auto-detected /
    HTTPS-required / OK), set by the dispatcher.
    """
    entries = [
        ConfigEntry(
            key=CONF_EXTERNAL_BASE_URL,
            type=ConfigEntryType.STRING,
            label="External base URL (HTTPS, required)",
            description=description,
            required=False,
            value=external_base_url,
            default_value="",
        ),
    ]
    if is_valid:
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_TEST_WEBHOOK,
                type=ConfigEntryType.ACTION,
                label="Test webhook reachability",
                description=(
                    "Sends a sentinel POST to <external_base_url>"
                    f"{DIALOG_WEBHOOK_BASE_PATH}/<secret> and reports "
                    "the result. Catches DNS / TLS / reverse-proxy "
                    "issues *before* you spend a Yandex moderation "
                    "cycle on a broken setup."
                ),
                action=CONF_ACTION_TEST_WEBHOOK,
                action_label="Test webhook",
                required=False,
                default_value="",
            )
        )
    return tuple(entries)


def _render_step2_create_section(
    *,
    stage: LocalAutoCreateStage,
    artifacts: SkillCreationArtifacts,
    action_outcome: AutoCreateOutcome | None,  # noqa: ARG001  # reserved for outcome banner
    duplicate_skill_name: str | None,
    duplicate_skill_id: str | None,
    external_base_url: str,
    base_url_description: str,
    base_url_valid: bool,
    update_message: str | None,
) -> tuple[ConfigEntry, ...]:
    """Render the *Create skill* section.

    Inlines the *external base URL* field (and the *Test webhook*
    button when the URL is valid) directly inside the step — that is
    the user's only required input here, so it must be visible
    alongside the action button rather than buried elsewhere.

    States:

    - **IDLE post-auth**: ready to create. Show the URL field +
      *Create skill* button (button hidden until URL is valid HTTPS).
    - **PIPELINE_RUNNING**: setup was interrupted. *Continue setup*
      button to resume from the last completed sub-step.
    - **DUPLICATE_DETECTED**: a skill with the same name already
      exists in the user's Yandex account. Two resolution buttons:
      *Recreate* (delete + register fresh) and *Adopt* (re-deploy
      the existing skill against our backend URL).
    - **FAILED**: pipeline error. Show last_error + *Try again* +
      *Reset (start over)*.
    """
    entries: list[ConfigEntry] = [
        ConfigEntry(
            key="label_step2_header",
            type=ConfigEntryType.LABEL,
            label="STEP 2 / 3 · Create the dialog skill",
        ),
        ConfigEntry(
            key="label_step2_signed_in",
            type=ConfigEntryType.LABEL,
            label="✓ Signed in to Yandex Passport.",
        ),
        *_build_external_base_url_entries(
            external_base_url=external_base_url,
            description=base_url_description,
            is_valid=base_url_valid,
        ),
    ]

    if update_message and stage not in (
        LocalAutoCreateStage.FAILED,
        LocalAutoCreateStage.DUPLICATE_DETECTED,
    ):
        entries.append(
            ConfigEntry(
                key="label_step2_update_msg",
                type=ConfigEntryType.LABEL,
                label=update_message,
            )
        )

    # The DUPLICATE_DETECTED branch shows its own structured prompt
    # (see below); FAILED renders artifacts.last_error directly. The
    # outcome message would duplicate either, so we skip it here.

    if stage == LocalAutoCreateStage.DUPLICATE_DETECTED:
        name = duplicate_skill_name or artifacts.last_known_name or ""
        entries.append(
            ConfigEntry(
                key="label_step2_duplicate_intro",
                type=ConfigEntryType.LABEL,
                label=(
                    f"⚠ A skill named «{name}» already exists in your "
                    "Yandex Dialogs account. Choose how to proceed:"
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key="label_step2_duplicate_recreate_hint",
                type=ConfigEntryType.LABEL,
                label=(
                    "  • Recreate — delete the existing skill in Yandex "
                    "and register a fresh one with the same name. "
                    "Discards any custom edits in the dev console."
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key="label_step2_duplicate_adopt_hint",
                type=ConfigEntryType.LABEL,
                label=(
                    "  • Adopt — keep the existing skill and re-deploy "
                    "it pointing at this Music Assistant's webhook URL. "
                    "Preserves any custom dev-console edits."
                ),
            )
        )
        if duplicate_skill_id:
            dev_console_url = (
                f"https://dialogs.yandex.ru/developer/skills/{duplicate_skill_id}"
            )
            entries.append(
                ConfigEntry(
                    key="label_step2_duplicate_dev_console",
                    type=ConfigEntryType.LABEL,
                    label=f"Open existing skill in Yandex Dialogs: {dev_console_url}",
                    help_link=dev_console_url,
                )
            )
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_RECREATE_DUPLICATE,
                type=ConfigEntryType.ACTION,
                label="Recreate (delete + create fresh)",
                description=(
                    "Deletes the existing skill in Yandex and registers "
                    "a fresh one against this Music Assistant's webhook "
                    "URL. Yandex moderation: 5-15 min."
                ),
                action=CONF_ACTION_RECREATE_DUPLICATE,
                action_label="Recreate skill",
                required=False,
                default_value="",
            )
        )
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_ADOPT_EXISTING,
                type=ConfigEntryType.ACTION,
                label="Adopt existing skill",
                description=(
                    "Keeps the existing skill and re-deploys it against "
                    "this Music Assistant's webhook URL. Yandex "
                    "moderation: 5-15 min."
                ),
                action=CONF_ACTION_ADOPT_EXISTING,
                action_label="Adopt existing",
                required=False,
                default_value="",
            )
        )
        return tuple(entries)

    if stage == LocalAutoCreateStage.PIPELINE_RUNNING:
        entries.append(
            ConfigEntry(
                key="label_step2_resume",
                type=ConfigEntryType.LABEL,
                label=(
                    "⏸ Setup was interrupted. Click 'Continue setup' "
                    f"to resume from step {artifacts.state.value}."
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_AUTO_CREATE_DIALOG,
                type=ConfigEntryType.ACTION,
                label="Continue setup",
                description=(
                    "Resumes the skill creation pipeline from the last "
                    "completed step. Idempotent — safe to click again "
                    "if it failed mid-way."
                ),
                action=CONF_ACTION_AUTO_CREATE_DIALOG,
                action_label="Continue setup",
                required=False,
                default_value="",
            )
        )
        return tuple(entries)

    if stage == LocalAutoCreateStage.FAILED:
        err = (artifacts.last_error or "Unknown error.").strip()
        entries.append(
            ConfigEntry(
                key="label_step2_failed_error",
                type=ConfigEntryType.LABEL,
                label=f"✗ {err}",
            )
        )
        entries.append(
            ConfigEntry(
                key="label_step2_failed_advice",
                type=ConfigEntryType.LABEL,
                label=(
                    "Click 'Try again' to retry from the last completed "
                    "step, or 'Reset (start over)' to drop partial state "
                    "and begin from scratch."
                ),
            )
        )
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_AUTO_CREATE_DIALOG,
                type=ConfigEntryType.ACTION,
                label="Try again",
                description="Retries the skill creation pipeline from the last completed step.",
                action=CONF_ACTION_AUTO_CREATE_DIALOG,
                action_label="Try again",
                required=False,
                default_value="",
            )
        )
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                type=ConfigEntryType.ACTION,
                label="Reset and start over",
                description=(
                    "Drops partial setup state and clears the failed "
                    "flag, so the next click starts a fresh attempt. "
                    "Cached Passport sign-in is kept."
                ),
                action=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                action_label="Reset (start over)",
                required=False,
                default_value="",
            )
        )
        return tuple(entries)

    # Default IDLE-post-auth → ready to create.
    # We render the Create button unconditionally and let the action
    # handler fail loudly with a FAILED outcome if the URL is missing
    # or non-public. Hiding the button on URL change would require a
    # form re-render that doesn't happen on plain text input.
    entries.append(
        ConfigEntry(
            key="label_step2_intro",
            type=ConfigEntryType.LABEL,
            label=(
                "Click 'Create skill' below — Music Assistant will "
                "register a new dialog skill in your Yandex Dialogs "
                "account using the Skill name you set above. The "
                "external base URL must be filled in above first."
            ),
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_ACTION_AUTO_CREATE_DIALOG,
            type=ConfigEntryType.ACTION,
            label="Create skill",
            description=(
                "Pre-checks Yandex for an existing skill with the same "
                "name; if found, prompts to Recreate or Adopt. "
                "Otherwise registers a fresh skill and points it at "
                "this Music Assistant's webhook URL."
            ),
            action=CONF_ACTION_AUTO_CREATE_DIALOG,
            action_label="Create skill",
            required=False,
            default_value="",
        )
    )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Step 3 — Skill registered (with edit mode)
# ---------------------------------------------------------------------------


def _render_step3_configured_section(
    *,
    artifacts: SkillCreationArtifacts,
    edit_mode: bool,
    skill_name: str,
    activation_phrases: str,
    voice: str,
    update_message: str | None,
) -> tuple[ConfigEntry, ...]:
    """Render the *Skill registered* section.

    States:

    - **edit_mode = False** (default): identity-card LABELs + *Edit
      skill* button. Identity-card content (skill name, skill_id,
      webhook URL, dev-console link) is rendered separately by the
      dispatcher in ``_build_identity_card_entries``; here we only
      add the section header + the edit toggle.
    - **edit_mode = True**: editable fields (skill_name [from main
      form] + activation_phrases + voice) plus *Update skill* /
      *Cancel edit* action buttons. The skill_name field itself stays
      at the top of the form for consistency, but the activation
      phrases + voice fields are rendered here so they only appear
      when the user is actively editing.
    """
    name = artifacts.last_known_name or skill_name or "Music Assistant"
    entries: list[ConfigEntry] = [
        ConfigEntry(
            key="label_step3_header",
            type=ConfigEntryType.LABEL,
            label=f"STEP 3 / 3 · Skill «{name}» is registered",
        ),
    ]

    if update_message:
        entries.append(
            ConfigEntry(
                key="label_step3_update_msg",
                type=ConfigEntryType.LABEL,
                label=update_message,
            )
        )

    if not edit_mode:
        entries.extend(
            [
                ConfigEntry(
                    key="label_step3_examples_header",
                    type=ConfigEntryType.LABEL,
                    label="Try saying:",
                ),
                ConfigEntry(
                    key="label_step3_example1",
                    type=ConfigEntryType.LABEL,
                    label=f"  • «Алиса, попроси {name} включи джаз»",
                ),
                ConfigEntry(
                    key="label_step3_example2",
                    type=ConfigEntryType.LABEL,
                    label=f"  • «Алиса, попроси {name} что играет»",
                ),
                ConfigEntry(
                    key="label_step3_example3",
                    type=ConfigEntryType.LABEL,
                    label=f"  • «Алиса, попроси {name} поставь на паузу»",
                ),
                ConfigEntry(
                    key="label_step3_moderation",
                    type=ConfigEntryType.LABEL,
                    label=(
                        "⏳ Yandex moderation queue: 5-15 min. The "
                        "skill goes live when the dev console shows "
                        "it as on-air."
                    ),
                ),
                ConfigEntry(
                    key=CONF_ACTION_EDIT_SKILL,
                    type=ConfigEntryType.ACTION,
                    label="Edit skill",
                    description=(
                        "Reveals editable fields for the skill name, "
                        "activation phrases, and voice. Save and "
                        "click 'Update skill' to push changes to "
                        "Yandex (re-deploy + 5-15 min moderation)."
                    ),
                    action=CONF_ACTION_EDIT_SKILL,
                    action_label="Edit skill",
                    required=False,
                    default_value="",
                ),
            ]
        )
        return tuple(entries)

    # Edit mode — show editable fields + Update / Cancel buttons.
    entries.append(
        ConfigEntry(
            key="label_step3_edit_intro",
            type=ConfigEntryType.LABEL,
            label=(
                "Edit the fields below. The 'Skill name' field above "
                "is also editable. Click 'Update skill' to push "
                "changes to Yandex."
            ),
        )
    )
    voice_options = [
        ConfigValueOption(title=label, value=value) for value, label in DIALOG_VOICE_OPTIONS
    ]
    entries.append(
        ConfigEntry(
            key=CONF_DIALOG_ACTIVATION_PHRASES,
            type=ConfigEntryType.STRING,
            label="Activation phrases (one per line)",
            description=(
                "Phrases users say after «Алиса, попроси …» to invoke "
                "the skill. Default = the Skill name itself plus a few "
                "common variations. One phrase per line."
            ),
            required=False,
            default_value=activation_phrases,
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_DIALOG_SKILL_VOICE,
            type=ConfigEntryType.STRING,
            label="TTS voice",
            description=(
                "Voice used for the skill's text-to-speech replies. "
                "Most users won't hear this voice in practice (Alice "
                "answers in her own voice for voice-control skills); "
                "exposed for completeness."
            ),
            required=False,
            default_value=voice or DIALOG_VOICE_DEFAULT,
            options=voice_options,
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_ACTION_UPDATE_SKILL,
            type=ConfigEntryType.ACTION,
            label="Update skill",
            description=(
                "Pushes the edited fields (skill name + activation "
                "phrases + voice) to Yandex via PATCH draft + "
                "re-deploy. Yandex moderation: 5-15 min."
            ),
            action=CONF_ACTION_UPDATE_SKILL,
            action_label="Update skill",
            required=False,
            default_value="",
        )
    )
    entries.append(
        ConfigEntry(
            key=CONF_ACTION_CANCEL_EDIT,
            type=ConfigEntryType.ACTION,
            label="Cancel edit",
            description=(
                "Discards your edits and exits edit mode. No Yandex "
                "API calls."
            ),
            action=CONF_ACTION_CANCEL_EDIT,
            action_label="Cancel edit",
            required=False,
            default_value="",
        )
    )
    # Hidden marker — flips the form back to non-edit on the next
    # render after the user clicks Cancel/Update.
    _ = CONF_DIALOG_SKILL_NAME  # consumer reference for clarity
    return tuple(entries)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def build_auto_create_entries(  # noqa: PLR0913
    *,
    artifacts: SkillCreationArtifacts,
    cached_x_token_present: bool,
    action_outcome: AutoCreateOutcome | None,
    duplicate_skill_name: str | None = None,
    duplicate_skill_id: str | None = None,
    edit_mode: bool = False,
    skill_name: str = "Music Assistant",
    activation_phrases: str = "",
    voice: str = DIALOG_VOICE_DEFAULT,
    update_message: str | None = None,
    last_error: str | None = None,
    external_base_url: str = "",
    base_url_description: str = "",
    base_url_valid: bool = False,
) -> tuple[ConfigEntry, ...]:
    """Render the active step's section based on persistent state.

    Exactly one of three sections is returned:

    - **Step 1**: Authenticate (blocking Device Flow + popup).
    - **Step 2**: Create skill (with duplicate-name pre-check).
    - **Step 3**: Skill registered (identity card + edit mode).

    The dispatcher in ``provider.__init__`` chains these entries with
    the surrounding form (skill_name field, external_base_url, voice
    control section, Advanced section, hidden state-carriers).
    """
    step = derive_active_step(
        artifacts=artifacts,
        cached_x_token_present=cached_x_token_present,
    )
    stage = _derive_stage(
        artifacts=artifacts,
        cached_x_token_present=cached_x_token_present,
        duplicate_pending=bool(duplicate_skill_id),
    )

    if step == 1:
        return _render_step1_auth_section(last_error=last_error)
    if step == 3:
        return _render_step3_configured_section(
            artifacts=artifacts,
            edit_mode=edit_mode,
            skill_name=skill_name,
            activation_phrases=activation_phrases,
            voice=voice,
            update_message=update_message,
        )
    return _render_step2_create_section(
        stage=stage,
        artifacts=artifacts,
        action_outcome=action_outcome,
        duplicate_skill_name=duplicate_skill_name,
        duplicate_skill_id=duplicate_skill_id,
        external_base_url=external_base_url,
        base_url_description=base_url_description,
        base_url_valid=base_url_valid,
        update_message=update_message,
    )
