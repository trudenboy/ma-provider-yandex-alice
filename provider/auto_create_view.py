r"""Pure rendering of auto-create UI entries from state.

Decoupled from the dispatcher (``provider.__init__`` uses these helpers
verbatim) so the form-shape can be unit-tested without exercising the
actual orchestrator. Returns ``ConfigEntry`` tuples.

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

import time

from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType
from ya_dialogs_api import SkillCreationArtifacts, SkillCreationState

from .auto_create import AutoCreateOutcome, LocalAutoCreateStage
from .constants import (
    CONF_ACTION_AUTO_CREATE_DIALOG,
    CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
)

__all__ = ["build_auto_create_entries"]

# Action button label flip — "what *will happen* on the next click", not
# "what just happened". UX rule: a button is a verb pointing forward.
_BUTTON_LABEL_BY_STAGE: dict[LocalAutoCreateStage, str] = {
    LocalAutoCreateStage.IDLE: "Sign in to Yandex Passport",
    LocalAutoCreateStage.DEVICE_FLOW_STARTED: "I confirmed — continue",
    LocalAutoCreateStage.PIPELINE_RUNNING: "Continue setup",
    LocalAutoCreateStage.DONE: "Create another skill",
    LocalAutoCreateStage.FAILED: "Try again",
}

# 4-step setup checklist. Each line is a separate ConfigEntry(LABEL) so it
# renders on its own row in the form (newlines inside one LABEL are
# collapsed by Vuetify's white-space:normal). Markers: ✓ done, → current,
# ☐ pending, ✗ failed.
_CHECKLIST_STEPS: tuple[str, ...] = (
    "Sign in to Yandex Passport",
    "Confirm device code",
    "Register skill in dialogs.yandex.ru",
    "Wait for Yandex moderation (5-15 min)",
)


def _create_button_label(stage: LocalAutoCreateStage) -> str:
    """Forward-looking button label per stage (#19)."""
    return _BUTTON_LABEL_BY_STAGE[stage]


def _derive_stage(
    *,
    artifacts: SkillCreationArtifacts,
    pending_session_present: bool,
    cached_x_token_present: bool,
) -> LocalAutoCreateStage:
    """Derive the UX stage from persistent state.

    Decision order (most specific first):

    1. Pending Device Flow session → ``DEVICE_FLOW_STARTED``.
    2. Artifacts ``DONE`` → ``DONE`` regardless of token presence.
    3. Artifacts ``FAILED`` → ``FAILED`` (Retry button).
    4. Artifacts in any post-create state with cached token →
       ``PIPELINE_RUNNING`` ("Continue setup" — next click hits the pipeline).
    5. Same intermediate state but **no** cached token → ``IDLE``: next
       click will start a fresh Device Flow first, so the button label
       must say "Sign in to Yandex Passport", not "Continue setup".
    6. Otherwise → ``IDLE``.
    """
    if pending_session_present:
        return LocalAutoCreateStage.DEVICE_FLOW_STARTED
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


def _checklist_marker_for_step(stage: LocalAutoCreateStage, step_idx: int) -> str:
    """Return the leading marker for a checklist step at the given stage.

    Stage → completed step count:
      IDLE                 → 0 done, step 0 is current ("Sign in")
      DEVICE_FLOW_STARTED  → 1 done, step 1 is current ("Confirm code")
      PIPELINE_RUNNING     → 2 done, step 2 is current ("Register skill")
      DONE                 → all 3 first done; step 3 ("Moderation") current
      FAILED               → all marked ✗ from the failed step on (caller
                             flips marker mapping; here we keep the simple
                             done/current/pending mapping)
    """
    completed_count = {
        LocalAutoCreateStage.IDLE: 0,
        LocalAutoCreateStage.DEVICE_FLOW_STARTED: 1,
        LocalAutoCreateStage.PIPELINE_RUNNING: 2,
        LocalAutoCreateStage.DONE: 3,
        LocalAutoCreateStage.FAILED: 0,
    }[stage]
    if step_idx < completed_count:
        return "✓"
    if step_idx == completed_count and stage != LocalAutoCreateStage.FAILED:
        return "→"
    return "☐"


def _format_time_remaining(expires_at_epoch: float | None) -> str | None:
    """Return ``M:SS`` (or ``mins`` for >= 5 min) string for code countdown.

    None → no display. Used in user_code instructions (#7).
    """
    if not expires_at_epoch:
        return None
    remaining = int(expires_at_epoch - time.time())
    if remaining <= 0:
        return None
    if remaining >= 300:
        return f"{remaining // 60} min"
    return f"{remaining // 60}:{remaining % 60:02d}"


def _build_checklist_entries(stage: LocalAutoCreateStage) -> tuple[ConfigEntry, ...]:
    """Render numbered setup checklist as ``len(_CHECKLIST_STEPS)`` LABELs (#6)."""
    return tuple(
        ConfigEntry(
            key=f"label_auto_create_step_{i}",
            type=ConfigEntryType.LABEL,
            label=f"  {_checklist_marker_for_step(stage, i)}  {i + 1}. {step_text}",
        )
        for i, step_text in enumerate(_CHECKLIST_STEPS)
    )


def _build_idle_intro_entries() -> tuple[ConfigEntry, ...]:
    """Friendly instructional banner for IDLE stage (no clicks yet)."""
    return (
        ConfigEntry(
            key="label_auto_create_idle_intro",
            type=ConfigEntryType.LABEL,
            label=(
                "Click 'Sign in to Yandex Passport' below — Music Assistant "
                "will guide you through Yandex Passport sign-in (a short "
                "verification code on ya.ru/device) and then register the "
                "skill at dialogs.yandex.ru on your behalf."
            ),
        ),
    )


def _build_device_flow_entries(
    user_code: str | None,
    verification_url: str | None,
    expires_at_epoch: float | None,
) -> tuple[ConfigEntry, ...]:
    """User_code visual emphasis + countdown for DEVICE_FLOW_STARTED (#7).

    Multiple LABELs so the user_code lands on its own row at high
    visibility (Vuetify v-alerts are individually styled blocks).
    """
    if not user_code or not verification_url:
        return (
            ConfigEntry(
                key="label_auto_create_device_flow_generic",
                type=ConfigEntryType.LABEL,
                label=(
                    "Device Flow in progress. Click 'I confirmed — continue' "
                    "to check, or 'Cancel' to abort."
                ),
            ),
        )

    countdown = _format_time_remaining(expires_at_epoch)
    countdown_str = f"  ⏱ Code expires in {countdown}" if countdown else ""

    return (
        ConfigEntry(
            key="label_auto_create_device_flow_step1",
            type=ConfigEntryType.LABEL,
            label=f"➊  Open in your browser: {verification_url}",
        ),
        ConfigEntry(
            key="label_auto_create_device_flow_step2",
            type=ConfigEntryType.LABEL,
            label=f"➋  Enter this code: «{user_code}»{countdown_str}",
        ),
        ConfigEntry(
            key="label_auto_create_device_flow_step3",
            type=ConfigEntryType.LABEL,
            label="➌  Confirm in your Yandex account",
        ),
        ConfigEntry(
            key="label_auto_create_device_flow_step4",
            type=ConfigEntryType.LABEL,
            label="➍  Click 'I confirmed — continue' below",
        ),
    )


def _build_done_entries(
    skill_name_for_examples: str,
) -> tuple[ConfigEntry, ...]:
    """Actionable post-DONE LABELs with example voice commands (#10).

    The skill_id link is rendered separately (identity-card in __init__.py),
    here we focus on **what the user can say to Alice** — that's the
    immediate "what now?" answer.
    """
    name = (skill_name_for_examples or "Music Assistant").strip()
    return (
        ConfigEntry(
            key="label_auto_create_done_header",
            type=ConfigEntryType.LABEL,
            label=f"✓ Skill «{name}» is registered. Try saying:",
        ),
        ConfigEntry(
            key="label_auto_create_done_example1",
            type=ConfigEntryType.LABEL,
            label=f"  • «Алиса, попроси {name} включи джаз»",
        ),
        ConfigEntry(
            key="label_auto_create_done_example2",
            type=ConfigEntryType.LABEL,
            label=f"  • «Алиса, попроси {name} что играет»",
        ),
        ConfigEntry(
            key="label_auto_create_done_example3",
            type=ConfigEntryType.LABEL,
            label=f"  • «Алиса, попроси {name} поставь на паузу»",
        ),
        ConfigEntry(
            key="label_auto_create_done_moderation",
            type=ConfigEntryType.LABEL,
            label=(
                "⏳ Yandex moderation queue: 5-15 min. The skill goes live "
                "when the dev console shows it as on-air."
            ),
        ),
    )


def _build_failed_entries(artifacts: SkillCreationArtifacts) -> tuple[ConfigEntry, ...]:
    """Error LABEL with last_error + suggestion to retry."""
    err = (artifacts.last_error or "Unknown error.").strip()
    return (
        ConfigEntry(
            key="label_auto_create_failed_error",
            type=ConfigEntryType.LABEL,
            label=f"✗ Setup failed: {err}",
        ),
        ConfigEntry(
            key="label_auto_create_failed_advice",
            type=ConfigEntryType.LABEL,
            label=(
                "Click 'Try again' to retry from the last completed step, "
                "or 'Reset (start over)' to drop partial state and begin "
                "from scratch."
            ),
        ),
    )


def _build_status_label_entries(
    *,
    stage: LocalAutoCreateStage,
    artifacts: SkillCreationArtifacts,
    action_outcome: AutoCreateOutcome | None,
    pending_user_code: str | None,
    pending_verification_url: str | None,
    pending_expires_at_epoch: float | None,
    skill_name_for_examples: str,
) -> tuple[ConfigEntry, ...]:
    """Compose the section above the auto-create button.

    Priority for ad-hoc one-line message vs structured stage rendering:

    - If a fresh ``action_outcome`` exists AND the message is non-trivial
      (e.g. an exception text from the orchestrator that doesn't map to
      one of the structured stages), render it as a single LABEL banner
      followed by the structured stage entries.
    - Otherwise render the structured stage entries directly.
    """
    entries: list[ConfigEntry] = []

    if (
        action_outcome is not None
        and action_outcome.user_message
        and stage == LocalAutoCreateStage.FAILED
    ):
        # Emphasise just-happened error message above the structured FAILED entries.
        entries.append(
            ConfigEntry(
                key="label_auto_create_outcome_msg",
                type=ConfigEntryType.LABEL,
                label=action_outcome.user_message,
            )
        )

    if stage == LocalAutoCreateStage.IDLE:
        entries.extend(_build_idle_intro_entries())
    elif stage == LocalAutoCreateStage.DEVICE_FLOW_STARTED:
        entries.extend(
            _build_device_flow_entries(
                pending_user_code, pending_verification_url, pending_expires_at_epoch
            )
        )
    elif stage == LocalAutoCreateStage.PIPELINE_RUNNING:
        entries.append(
            ConfigEntry(
                key="label_auto_create_pipeline_running",
                type=ConfigEntryType.LABEL,
                label=(
                    "⏸ Setup was interrupted. Click 'Continue setup' to "
                    f"resume from step {artifacts.state.value}."
                ),
            )
        )
    elif stage == LocalAutoCreateStage.DONE:
        entries.extend(_build_done_entries(skill_name_for_examples))
    elif stage == LocalAutoCreateStage.FAILED:
        entries.extend(_build_failed_entries(artifacts))

    # Numbered checklist appears below the stage-specific banner so the user
    # sees both the "right now" hint and overall progress.
    entries.extend(_build_checklist_entries(stage))

    return tuple(entries)


def build_auto_create_entries(
    *,
    artifacts: SkillCreationArtifacts,
    pending_session_present: bool,
    cached_x_token_present: bool,
    action_outcome: AutoCreateOutcome | None,
    pending_user_code: str | None = None,
    pending_verification_url: str | None = None,
    pending_expires_at_epoch: float | None = None,
    skill_name_for_examples: str = "Music Assistant",
) -> tuple[ConfigEntry, ...]:
    """Render the auto-create cluster: stage banner + checklist + ACTION + Cancel/Reset.

    The Cancel/Reset button is visible only when in DEVICE_FLOW_STARTED or FAILED:

    - **DEVICE_FLOW_STARTED**: ``Cancel`` — short, kills the pending session.
    - **FAILED**: ``Reset (start over)`` — wider scope, drops partial
      progress as well as the failed state. Cached x_token is preserved
      either way (#21).

    ``pending_user_code`` / ``pending_verification_url`` /
    ``pending_expires_at_epoch`` come from the deserialised Device Flow
    session: passing them in lets the LABELs remain self-explanatory after
    a form reload mid-Device-Flow.

    ``skill_name_for_examples`` is used in the post-DONE actionable
    message to interpolate the user's actual skill name into example
    voice commands.
    """
    stage = _derive_stage(
        artifacts=artifacts,
        pending_session_present=pending_session_present,
        cached_x_token_present=cached_x_token_present,
    )

    entries: list[ConfigEntry] = list(
        _build_status_label_entries(
            stage=stage,
            artifacts=artifacts,
            action_outcome=action_outcome,
            pending_user_code=pending_user_code,
            pending_verification_url=pending_verification_url,
            pending_expires_at_epoch=pending_expires_at_epoch,
            skill_name_for_examples=skill_name_for_examples,
        )
    )

    entries.append(
        ConfigEntry(
            key=CONF_ACTION_AUTO_CREATE_DIALOG,
            type=ConfigEntryType.ACTION,
            label="Auto-register skill",
            description=(
                "One click drives the next external-IO step of the skill "
                "creation flow: Yandex Passport sign-in, code confirmation, "
                "or Yandex Dialogs registration. The button label tells you "
                "what the next click will do."
            ),
            action=CONF_ACTION_AUTO_CREATE_DIALOG,
            action_label=_create_button_label(stage),
            required=False,
            default_value="",
        )
    )

    if stage == LocalAutoCreateStage.DEVICE_FLOW_STARTED:
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                type=ConfigEntryType.ACTION,
                label="Cancel sign-in",
                description=(
                    "Aborts the current Yandex Passport sign-in. The cached "
                    "x_token (if any) is preserved."
                ),
                action=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                action_label="Cancel",
                required=False,
                default_value="",
            )
        )
    elif stage == LocalAutoCreateStage.FAILED:
        entries.append(
            ConfigEntry(
                key=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                type=ConfigEntryType.ACTION,
                label="Reset and start over",
                description=(
                    "Drops partial setup state and clears the failed flag, "
                    "so the next click starts a fresh attempt. Cached "
                    "Passport sign-in is kept."
                ),
                action=CONF_ACTION_CANCEL_DIALOG_SKILL_FLOW,
                action_label="Reset (start over)",
                required=False,
                default_value="",
            )
        )

    return tuple(entries)
