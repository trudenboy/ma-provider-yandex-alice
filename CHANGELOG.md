# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] — 2026-05-06

### Added

- **«Создать навык» action.** New button in the provider config form that
  registers a custom Alice skill in `https://dialogs.yandex.ru/developer`
  programmatically. One UX click drives a state machine: Yandex Passport
  Device Flow login (display user_code → user confirms on
  `https://ya.ru/device` → next click polls for confirmation), then a
  single OAuth-free pipeline call via
  `ya_dialogs_api.auto_create_skill(channel="aliceSkill", oauth_*=None)`
  (CSRF fetch → create-app → upload-logo → update-draft → request-deploy).
  On success the `Skill ID` field is populated automatically.

- **Self-resuming Device Flow UX.** The same auto-create button doubles as
  «Подтвердить и продолжить» / «Возобновить» / «Пересоздать» / «Повторить»
  depending on persisted state. Per-click external-IO is bounded
  (`poll_window=8s` per resume) so HTTP / proxy timeouts can't strand the
  flow. Artifacts (skill_id, logo_id, last_known_name) are checkpointed
  between clicks so partial failures resume from the last completed step.

- **«Переименовать навык в Yandex» action.** New button (visible only when
  a skill exists and `x_token` is cached) syncs the current `Skill name`
  to Yandex via `ya_dialogs_api.auto_update_skill(channel="aliceSkill")`.
  Uses the cached `x_token` — no Device Flow re-prompt. Drift detection:
  if MA-side `Skill name` differs from `last_known_name` in artifacts,
  a status hint appears prompting the rename.

- **«Отмена» action.** Visible during pending Device Flow or after FAILED
  outcomes. Drops in-flight session + resets artifacts; cached `x_token`
  is preserved so the next create click can skip Passport login.

- **Cached `x_token`.** First successful Device Flow caches the long-lived
  Yandex Passport `x_token` in encrypted config (`CONF_AUTH_X_TOKEN`,
  SECURE_STRING) for reuse across rename / re-create within the token's
  lifetime (months). Cache is dropped silently on any 401 from Yandex /
  Passport (`InvalidCredentialsError`).

- **Typed-error UX.** `DialogsAuthError` (401 / HTML 403 / 30x) signals
  `x_token` clear; `DialogsValidationError.fields` populates the status
  LABEL with per-field hints; `DialogsSkillNotFoundError` flags missing
  upstream skill so the user can re-create.

### Notes

- The Yandex Dialogs API is **undocumented and private**. If Yandex
  changes the contract this action will fail; manual setup at
  https://dialogs.yandex.ru/developer remains the supported fallback.

- After `request_deploy`, Yandex's moderation queue takes ~5–15 minutes
  for `aliceSkill` skills. The success message links the user to the
  skill's dev-console page for on-air status.

### Dependencies

- `ya-dialogs-api>=2.0.0` (was indirectly `>=1.0.0`; required for the
  OAuth-free `aliceSkill` pipeline shape and typed-error hierarchy).

## [1.0.0] — 2026-05-06

### Added

Initial release. Yandex Alice voice-skill provider extracted from the voice
side of `ma-provider-yandex-smarthome`. The provider exposes Music Assistant
playback to a Yandex Dialogs custom skill — a Russian-NLU voice control
surface invoked via *«Алиса, попроси Music Assistant …»*.

**Voice command surface (inherited from smarthome 1.9.1):**

- **Playback:** *включи Metallica*, *включи джаз*, *включи плейлист*,
  *что играет*, *поставь на паузу*, *продолжи*, *стоп*, *следующий трек*,
  *предыдущий*, *громче*, *тише*, *громкость 50*, *выключи звук*.
- **Queue control:** *перемешай* / *выключи перемешивание*, *повтор песни* /
  *повтор очереди* / *повторяй* / *выключи повтор*, *перемотай вперёд на
  минуту*, *назад на 30 секунд*, *к началу*, *добавь Iron Maiden*.
- **Multi-room:** *переведи на спальню*, *продолжи в спальне*, *включи на
  кухне*, *что играет на кухне*, *список колонок*, *забудь колонку*.
- **Voice-first disambiguation:** when a player name is ambiguous, the skill
  asks *«первая, вторая или третья?»* and resolves the user's spoken ordinal
  reply.
- **Russian NLU resilience:** handles inflected forms (*кухню* → kitchen,
  *спальни* → bedroom), case-insensitive partial matches, fuzzy player-name
  resolution, and Yandex Station's quirky session-state behaviour
  (in-process LRU cache survives the dropped `session.application` field).

**Manual setup in this release:**

1. Create a custom dialog skill in <https://dialogs.yandex.ru/developer>.
2. Point its webhook at MA's ``<base-url>/api/yandex_dialogs/webhook/<secret>``.
3. Paste the skill ID, OAuth token, and webhook secret into the provider's
   config form. Pick the players the skill is allowed to control.

**Architecture:**

- `provider/dialogs.py` (1311 LOC) — webhook handler with TTL-keyed in-process
  state cache, voice-first disambiguation, and ordinal-pick recognition.
- `provider/dialogs_nlu.py` (474 LOC) — Russian NLU: verb stripping, query
  extraction, player-name fuzzy match.
- `provider/dialogs_control.py` (468 LOC) — control verbs (pause / next /
  volume / shuffle / repeat / seek / transfer / now-playing / list-players /
  forget-player / add-to-queue) with parametric pattern matching.
- `provider/dialogs_player.py` (313 LOC) — search-and-resolve, queue dispatch.

### Coming next

- **v1.1.0** — auto-create-skill action (one-click skill registration in the
  dev console via `ya-dialogs-api`); rename-skill action.
- **v1.2.0** — group / ungroup multi-player commands; like / dislike for
  rotor stations; sleep timer.

### Migration

If you previously used the **voice skill section** of
`ma-provider-yandex-smarthome` (`dialog_skill_enabled=true` in your
config): the voice code has been removed from `ma-provider-yandex-smarthome`
in its 2.0.0 release. Install this provider, paste the same skill ID +
token, and re-expose your players. Smart Home device-bridge users (who
never enabled the voice skill) are unaffected.
