# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.7.1] - 2026-07-09

### Added

- **Yandex account source**: the Authorization step can now borrow the Yandex account of a configured Yandex Music provider instead of running its own sign-in — one login for the whole household. Pick the source in the dropdown; "Use own credentials" remains the default and behaves exactly as before. When borrowing, the Sign-in/Sign-out buttons disappear, skill actions run on the linked account read-only (nothing is stored or rotated by this plugin), and an unavailable Yandex Music instance shows an actionable message instead of breaking the form.

## [1.6.2] - 2026-07-09

### Changed

- The Yandex Passport sign-in page now comes from the shared `ya-passport-auth[ma]` layer used by all Music Assistant yandex providers: Russian/English localization, dark-theme support, tap-to-copy code, an honest countdown of the code's remaining lifetime, and clear terminal states explaining why a sign-in failed (expired / denied / error). The page keeps its skill-registration explanation.
- The sign-in action returns the moment the outcome is known instead of pausing for a grace period; the page keeps polling in the background and closes itself.
- Transient Yandex Passport failures (network, rate limiting) now surface as "temporarily unavailable" instead of a sign-in failure.

## [1.6.1] - 2026-05-09

### Fixed

- Music Assistant failed to start with the provider installed —
  bundled-resource lookup hardcoded the source-tree package name
  (`provider.data`), which doesn't exist after the upstream sync
  renames the package to `music_assistant.providers.yandex_alice`.
  The lookup now resolves through `__package__` so it works in both
  the source tree and the upstream-synced layout.

## [1.6.0] - 2026-05-09

### Added

- **Runtime mapping in the skill manifest.** Each `[[intents]]` block
  in `skill.toml` now carries an `[intents.runtime]` section that
  declares how the matched intent translates to a player action —
  `kind`, `action`, optional `[[intents.runtime.mapping]]` rules
  (clamp / abs_clamp ranges, default values, sign, multiplicative
  unit conversion, reject thresholds). Adding or tuning an intent no
  longer requires Python changes; the manifest is the single source
  of truth.
- **File-based manifest override.** Drop a fully-formed manifest at
  `<storage>/yandex_alice/skill.toml` and the provider uses it
  instead of the bundled default for both grammar deployment to
  Yandex and runtime intent dispatch. Invalid overrides fall back to
  the bundled default with a warning rendered in the UI.
- **Manifest UI section** (under Settings) exposes manifest status
  (bundled / override active / override invalid + parse error) plus
  four actions:
  - *Export manifest* — write the bundled default to the override
    path so it can be edited in an external editor.
  - *Import manifest* — paste full TOML into the form and have it
    validated and written to the override path. Supports a
    `data:base64,<base64>` prefix for browsers that strip newlines
    from text inputs.
  - *Validate manifest* — re-parse the override file and report
    structural / schema errors without redeploying to Yandex.
  - *Reset manifest* — delete the override file and revert to the
    bundled default. Idempotent.

### Changed

- **Bump `ya-dialogs-api` → 2.4.0** for the new `ManifestRuntime` /
  `ManifestMapping` schema and the `apply_runtime_mapping` runtime
  dispatcher.
- **Skill grammar / entity builders are now class-based.** The
  module-level `build_grammar()` / `build_entities()` /
  `parse_platform_intent` functions in `dialogs_grammar.py` are gone;
  the new `SkillManifestProvider` (constructed from `mass`) is the
  single entry point for reading the effective manifest, dispatching
  intents, and managing override-file lifecycle.

### Removed

- Hard-coded `_CONTROL_INTENT_MAP`, `_DEFAULT_VOLUME_DELTA`,
  `_MAX_SEEK_SECONDS`, and the slot-extraction helpers
  (`_slot_int` / `_slot_str`) from `dialogs_grammar.py` — every
  numeric constant and dispatch rule now lives in the manifest.

## [1.5.0] - 2026-05-09

### Added

- **`provider/data/skill.toml` — declarative skill manifest.** All
  24 intents and the single `time_unit` custom entity that used to
  live as Python string constants in `provider/dialogs_grammar.py`
  now live in a TOML file. Each `grammar = """…"""` block carries
  the Granet `sourceText` byte-for-byte, so phrasings can be
  copy-pasted to and from the dev-console editor at
  `https://dialogs.yandex.ru/developer/skills/<id>/draft/settings/intents`.
  Field names mirror Yandex API names in snake_case
  (`form_name` ↔ `formName`, `human_readable_name` ↔
  `humanReadableName`, etc.).

  The TOML format and its validator live in `ya_dialogs_api.manifest`
  (added in lib v2.3.0). If Yandex changes the on-the-wire shape
  the absorption point is in the library, not here.

### Changed

- **Bump `ya-dialogs-api` → 2.3.0** for the new
  `SkillManifest` / `parse_manifest_text` / `iter_intent_matches`
  APIs.
- **`build_grammar()` and `build_entities()` now load from the
  manifest.** Behaviour is identical to v1.4.4; the change is purely
  storage-layer (Python constants → TOML file).
- **`parse_platform_intent` consumes `IntentMatch.slot_int` /
  `slot_str`** from `ya_dialogs_api.nlu` instead of reaching into
  the raw `nlu.intents.<form>.slots[name].value` dict. Provider no
  longer depends on the wire shape of slot payloads.

### Removed

- Provider-local `_*_GRAMMAR` string constants and the
  `TIME_UNIT_ENTITY` literal — replaced by the TOML manifest.
- Provider-local `_slot_int` / `_slot_str` helpers — moved to the
  library as `IntentMatch.slot_int` / `IntentMatch.slot_str`.

## [1.4.4] - 2026-05-09

### Fixed

- **«Какие колонки видишь?» didn't classify as `control.list_players`**
  on a live skill. The v1.4.0 grammar covered only `какие колонки`
  without the trailing `видишь` / `знаешь` / `есть` qualifier that
  most users actually say, so the phrase fell through to the play
  parser, hit a multi-player disambiguation prompt, and then
  contaminated session state for the next utterance. Extended
  `_LIST_PLAYERS_GRAMMAR` with the missing variants:
  `сколько колонок видишь / ты видишь / знаешь / ты знаешь`,
  `какие колонки видишь / ты видишь / знаешь / ты знаешь / есть`.
  Pinned `%lemma` standalone at the top so morphology of `видеть`
  / `знать` is matched too.
- **`now_playing` grammar likewise broadened.** Added `что за
  композиция`, `какой трек`, `какой сейчас трек`, `какая песня`,
  `какая сейчас песня` — phrasings that already existed in the
  pre-v1.4.0 regex parser but didn't make it into the platform
  grammar.

## [1.4.3] - 2026-05-09

### Fixed

- **Skill creation failed with «`[control.volume_set] Некорректный
  аргумент`»** during the auto-create / auto-update pipeline (after
  the v1.4.2 fix landed). Yandex's Granet validator rejects `%lemma`
  morphology directives placed **after `|` in an alternation** — only
  a standalone `%lemma` line at the top of `root:` is accepted (it
  then applies to every verb / noun in the alternation below; the
  long-stable `_PAUSE_GRAMMAR` uses this shape).

  Five v1.4.0 grammars used the rejected pattern: `control.volume_set`,
  `control.volume_increase`, `control.volume_decrease`,
  `control.seek_forward`, `control.seek_back`. Rewrote each so the
  `%lemma` directive sits standalone at the top of `root:`. Surface
  coverage is identical.

  Granet DSL is now empirically pinned to one shape for verb
  morphology: `%lemma` standalone first, alternation second. v1.4.1
  + v1.4.2 + v1.4.3 collectively cover all three failure modes
  (multi-line `|`, `[%lemma … ]`, `| %lemma …`).

## [1.4.2] - 2026-05-09

### Fixed

- **Skill creation failed with «`[control.volume_set] Некорректный
  символ`»** during the auto-create / auto-update pipeline. Yandex's
  Granet validator rejects `%lemma` morphology directives placed
  inside `[...]` optional blocks (`[%lemma сделать]`,
  `[%lemma перемотать]`). Three v1.4.0 grammars used that pattern
  (`control.volume_set`, `control.seek_forward`,
  `control.seek_back`) and would not pass moderation. Rewrote each
  to express the optional verb as a top-level alternation branch
  (bare-noun / verb-led) so the directive sits at root level.

  Phrases like "сделай громкость 50", "перемотай вперёд на 30
  секунд" and bare "громкость 50", "вперёд 30 секунд" all still
  match — same surface coverage, just expressed differently in DSL.

## [1.4.1] - 2026-05-09

### Fixed

- **Skill creation failed with «`[control.list_players] Пустой
  элемент`»** during the auto-create / auto-update pipeline.
  Yandex's Granet validator rejects intent grammars whose
  alternations span multiple lines with `|` opening a continuation
  line — it sees an empty operand at the line break. Four v1.4.0
  intent grammars (`control.list_players`,
  `control.forget_player`, `control.volume_increase`,
  `control.volume_decrease`) were authored that way and would not
  pass moderation. Collapsed every alternation onto a single root
  line. No behavioural change to the runtime parser; affects only
  the DSL the library ships to Yandex.

## [1.4.0] - 2026-05-09

### Added

- Расширены платформенные intents Яндекс.Диалогов: 13 новых форм
  закрывают почти весь регулярный control-домен — приглушить /
  включить звук, перемотать к началу, повторить песню / всё /
  выключить повтор, перечислить / забыть колонки, установить
  громкость на N процентов, прибавить / убавить на N (через
  слот `YANDEX.NUMBER`), перемотать вперёд / назад на N
  секунд или минут (через слот `YANDEX.NUMBER` плюс кастомную
  сущность `time_unit`). Платформенный NLU быстрее и устойчивее
  к шуму ASR, чем локальный regex.
- Кастомная сущность `time_unit` (секунды / минуты), на которую
  ссылаются intent-грамматики `control.seek_forward` /
  `control.seek_back`. Сущность объявляется через `build_entities()`
  и синхронизируется на скилле автоматически из плагина при
  «Apply skill changes».

### Changed

- Бамп зависимости `ya-dialogs-api` → 2.2.0 — типизированные слоты
  в `IntentDraft`, поддержка кастомных сущностей через
  `set_entities`, проброс `entities` через
  `auto_create_skill` / `auto_update_skill`.

### Removed

- Локальные regex-парсеры для команд, перенесённых в платформенные
  intents. Распознавание этих фраз идёт исключительно через
  `request.nlu.intents` от Яндекса. Что осталось на regex —
  `transfer` («переведи на кухню»; цель — динамический enum
  плееров пользователя, не помещается в статическую грамматику)
  и весь play-домен (artist / album / playlist / track / genre с
  free-text запросом). После апгрейда нужно нажать «Apply skill
  changes» в плагине и дождаться завершения moderation Яндекса
  (обычно минуты, иногда часы для приватных навыков). До
  прохождения moderation голосовые команды, чьи regex-ы удалены,
  временно не работают.

## [1.3.7] - 2026-05-09

### Fixed

- **Skill update click failed with «Form name already exists».** The
  rename / drift-sync flow listed existing intents on the skill but
  Yandex's bulk listing endpoint omits `formName` from the response,
  so every server-side intent was invisible to the diff/upsert
  protocol. The library treated each declared intent as new, POSTed a
  fresh empty shell, then PATCHed the shell with a `formName` that
  another (already-named) intent had reserved on the server — the API
  rejected the PATCH. Picks up `ya-dialogs-api==2.1.2` which fans out
  to the per-intent endpoint to populate `formName` / `sourceText` /
  tests, so updates are now idempotent on a populated skill: matching
  intents are PATCHed in place and stale empty intents from earlier
  failed attempts are pruned.

### Changed

- **Bumps `ya-dialogs-api==2.1.2`.**

## [1.3.6] - 2026-05-09

### Fixed

- **Custom-intent grammars rejected by Yandex with «Некорректный
  аргумент».** *Create skill* failed at the very first intent
  (`control.pause`) because every grammar declared the `%lemma`
  directive inline (`%lemma пауза`), a form the Yandex Dialogs
  grammar parser does not accept — the directive must appear on its
  own line and is then scoped to the indented alternatives that
  follow. All 11 declared grammars are reformatted to put `%lemma` on
  its own line and to separate alternatives with the canonical pipe
  (`|`). The first grammar (control.pause) was test-validated in the
  Yandex dev console: 100% precision / 100% recall against the
  shipped positive/negative tests. The skill now provisions all 11
  intents in one *Create skill* / *Apply changes* round-trip.

## [1.3.5] - 2026-05-09

### Changed

- **Bumps `ya-dialogs-api==2.1.1`.** Version 2.1.1 enriches the
  validation-error message that surfaces when Yandex rejects an intent
  grammar at *Create skill* time — the error now identifies which
  intent and where in its source text the problem is, instead of
  collapsing every failure to a generic «Некорректный аргумент». The
  on-screen log line for failed skill provisioning now points
  directly at the offending grammar so it can be fixed without trial
  and error.

## [1.3.4] - 2026-05-09

### Fixed

- **Auto-update error wording points at the wrong action.** When the
  cached Yandex Passport authentication is missing or rejected during
  a rename / drift-sync click, the resulting error told the user to
  click *Create skill* — but that action is hidden until sign-in
  succeeds, so the suggested recovery led nowhere. Both messages now
  direct the user to the *Sign in to Yandex Passport* action that is
  actually available in that state.

## [1.3.3] - 2026-05-09

### Changed

- `parse_command` docstring (`provider/dialogs_nlu.py`) reformatted from a Google-style `Examples:` block to Sphinx-style `:param:` per the upstream music-assistant/server CLAUDE.md docstring rule.

## [1.3.2] — 2026-05-08

### Fixed

- **Device-flow popup `/status` 404 race**: the auth flow tore down
  the `/yandex_alice/device_code/<id>/status` route 3 s after the
  state flipped to `"done"`, but the popup HTML polls every 2.5 s
  with an additional ~800 ms close timer — slow tabs / throttled
  background windows / brief network hiccups landed their next poll
  *after* the route was gone and saw repeated 404s instead of the
  terminal `"done"` state. Replaced the synchronous unregister-in-
  `finally` with `schedule_unregister_device_code_route(...)` which
  schedules the teardown 30 s later via `mass.create_task`. The
  `state_provider` closure (which the route handler reads) keeps
  returning `"done"` / `"failed"` for the full window so the popup
  always sees the terminal state and closes itself; the route is
  reaped automatically afterwards. Also adds DEBUG logging of
  register / unregister with `session_id` for future diagnostics.

### Internal

- Bumps `ya-dialogs-api>=2.1.1` (when published) — release 2.1.1
  enriches `DialogsIntentValidationError.__str__` with the offending
  `form_name` and error position, and adds per-intent INFO progress
  in `set_intents`. The provider-side log line stays unchanged but
  now points at which grammar in our 11-intent set tripped Yandex's
  validator.

## [1.3.1] — 2026-05-07

### Fixed

- **Upstream CI codespell**: the `pyproject.toml` codespell ignore-list
  added in 1.3.0 only applied locally — `music-assistant/server` uses
  its own codespell config and re-flagged `sting` (the artist Стинг in
  `tts_dictionary.py`, not a typo of `string`) on
  [PR #3843](https://github.com/music-assistant/server/pull/3843)
  ([run](https://github.com/music-assistant/server/actions/runs/25521399342)).
  Replaced with an inline `# codespell:ignore sting` directive that
  works regardless of repo-level config.

## [1.3.0] — 2026-05-07

Maximum-integration release for Yandex Dialogs platform features (Phases
0–2 of `docs/NLU_RESEARCH.md`). Six commits delivered on
`feat/platform-integration` and merged via PR
[#18](https://github.com/trudenboy/ma-provider-yandex-alice/pull/18).

### Added

- **Platform NLU consumption (Phase 0).** Read the rest of the Yandex
  Dialogs request envelope:
    - `meta.interfaces.screen` gates `buttons` emission so voice-only
      surfaces (Mini, Pro) get the same ordinal-based prompt without
      button payload.
    - `request.markup.dangerous_context` short-circuits with a generic
      "Не понял команду" + `end_session=true`; flagged content never
      lands in `mass.music.search`.
    - `request.nlu.entities[YANDEX.NUMBER]` feeds a new
      `volume_relative` `ParsedControl` action: «прибавь на 20» / «убавь
      5» / «на 15 громче» reads current volume, applies signed delta,
      clamps `[0, 100]`, dispatches `cmd_volume_set`.
    - `request.original_utterance` logged alongside the normalised
      `command` for misclassification post-mortems (DEBUG only).

- **Response polish for screened surfaces (Phase 1).**
    - `card` parameter plumbed through `_yandex_response` (BigImage /
      ItemsList / ImageGallery shapes documented; emission deferred to
      Phase 1.5 — needs separate image-upload infrastructure).
    - Suggestion buttons (Следующая / Пауза / Громче / Тише) appended
      to play- and control-success responses on screened surfaces.
    - `provider/tts_dictionary.py` carries ~26 single-word foreign
      artist transliterations (Metallica → мет+аллика, Coldplay →
      к+олдплей, …) plus 16 multi-word phrases (Iron Maiden, Pink
      Floyd, …); `_tts_for` now matches both Latin and Cyrillic words
      so foreign band names get pronounced correctly while `text`
      stays clean.
    - `voice_continuation` opt-in toggle (`CONF_DIALOG_VOICE_CONTINUATION`,
      default off): when enabled, play- and control-success responses
      keep the conversation open. `стоп / останови / выключи` always
      close the session.

- **Custom-intent grammar (Phase 2).** Eleven grammars declared on the
  skill and dispatched at runtime via `request.nlu.intents`:
    - `control.{pause, resume, next, previous, stop, volume_up,
      volume_down, shuffle_on, shuffle_off, now_playing}`
    - `play.my_wave`
    - Each carries `positiveTests` for the dev-console "Протестировать"
      button and uses `%lemma` directives to absorb morphology.
    - Yandex's built-in `YANDEX.REJECT` (cancel pending prompt) and
      `YANDEX.HELP` (contextual hint) are unlocked automatically once
      any custom grammar is declared and now have runtime handlers.
    - Regex parsers (`parse_command` / `parse_control`) remain as the
      fallback when `request.nlu.intents` is empty — purely additive
      coverage, no regression risk.
    - Bumps `ya-dialogs-api==2.1.0` for the new `IntentDraft` API and
      `set_intents` diff-based sync.

- **Root `CLAUDE.md`** aligned with upstream Music Assistant
  `CLAUDE.md` — Sphinx-style docstrings, sync workflow, network-input
  validation contract, debugging notes.

### Fixed

- **Webhook handler error handling**: post-auth dispatch is now wrapped
  in `try / except` so a parser / resolver / MA-dispatch raise surfaces
  as a Russian fallback ("Что-то пошло не так. Попробуй ещё раз.")
  instead of HTTP 500 → Alice silence. Flagged in upstream
  [music-assistant/server#3843](https://github.com/music-assistant/server/pull/3843)
  by [@chrisuthe](https://github.com/chrisuthe).
- **Docstring style**: six existing Google-style docstrings (`Args:` /
  `Raises:` / `Returns:`) converted to Sphinx-style (`:param:` /
  `:raises:` / `:returns:`) per the upstream `CLAUDE.md` convention.
  Flagged in the same upstream review.

### Fixed (review on PR [#18](https://github.com/trudenboy/ma-provider-yandex-alice/pull/18))

- **Logs no longer leak flagged content.** When
  `request.markup.dangerous_context=true`, the structured "Webhook recv"
  DEBUG log was still emitting the `command` and `original_utterance`
  fields *before* the refusal branch ran. Both are now redacted to
  `<redacted: dangerous_context>` so flagged phrases never reach
  `$HOME/.musicassistant/musicassistant.log`. Found by Copilot
  ([#18 thread](https://github.com/trudenboy/ma-provider-yandex-alice/pull/18#discussion_r3204562269)).
- **`volume_relative` magnitude clamp accepts zero.** Previously
  `max(1, …)` silently promoted "прибавь на 0" to a +1 bump. The
  clamp is now `max(0, …)` so the parsed delta matches the spoken
  number — `0` becomes a no-op rather than an unwanted volume change.
  Found by Copilot
  ([#18 thread](https://github.com/trudenboy/ma-provider-yandex-alice/pull/18#discussion_r3204562328)).
- **`CONF_DIALOG_VOICE_CONTINUATION` comment accuracy.** The doc-comment
  promised that "спасибо" closes the session via the `stop` control
  intent, but `parse_control` does not match it. Comment corrected to
  the actual matched phrases: «стоп / останови / выключи / выключи
  музыку». Found by Copilot
  ([#18 thread](https://github.com/trudenboy/ma-provider-yandex-alice/pull/18#discussion_r3204562358)).

### Internal

- 466 unit tests (was 411). Coverage spans every new code path
  including the dangerous-content log redaction, zero-magnitude
  volume parse, suggestion-button gating, voice-continuation toggle,
  platform-intent dispatch, REJECT / HELP handlers, and the
  webhook-error-recovery fallback.
- `pyproject.toml`: `codespell` ignores `sting` (the artist Стинг in
  `tts_dictionary.py`, not a typo of `string`).

## [1.2.3] — 2026-05-07

### Fixed

- **HA add-on ingress**: the device-code page URL handed to the
  `AuthenticationHelper` popup was a path-from-root
  (`/yandex_alice/device_code/<id>`), so a browser sitting on the
  Home Assistant ingress URL `https://<host>/<addon-slug>/`
  resolved it against the origin and dropped the add-on prefix —
  the popup landed on `https://<host>/yandex_alice/device_code/<id>`
  (404). Both the popup URL and the in-page status-poll URL are
  now built from `mass.webserver.base_url`, which already includes
  the ingress prefix in HA add-on mode (matches the pattern used
  by the `yandex_music` provider's Device Flow auth page).

## [1.2.2] — 2026-05-07

### Fixed

- `build_backend_uri` (`dialog_skill_meta.py`) and the webhook reachability
  probe (`webhook_probe.py`) previously only checked for an `https://`
  prefix. Both now route the URL through `is_public_https_url`, so private
  IPs, loopback and link-local hosts (e.g. `https://localhost`,
  `https://192.168.1.10`) are rejected up front with a clear error
  before auto-create / update touches Yandex or the probe loops back
  to the same machine. Found by Copilot review on
  [music-assistant/server#3843](https://github.com/music-assistant/server/pull/3843)
  ([#1](https://github.com/music-assistant/server/pull/3843#discussion_r3202494295),
  [#2](https://github.com/music-assistant/server/pull/3843#discussion_r3202494389)).

## [1.2.1] — 2026-05-07

### Fixed

- Three lint findings flagged by Music Assistant's stricter upstream
  pre-commit (no behaviour change):
  - `provider/auth_page.py` — converted the `StateProvider` type-alias
    docstring into a regular comment so `check-docstring-first` does
    not flag it as a second module docstring.
  - `tests/test_auto_create.py` — narrowed the file-level `noqa` to
    `D102` only (`PLW0108` was unused under upstream config) and
    inlined the `lambda x: _raising_factory(x)` wrapper that
    triggered `PLW0108` locally.
  - `tests/test_auto_create.py` — annotated the unreachable `yield`
    inside the `_raising_factory` async-context-manager with
    `# type: ignore[unreachable]` so mypy stops reporting it; the
    `yield` is required for `@asynccontextmanager` to treat the
    function as a generator even though execution never reaches it.

## [1.2.0] — 2026-05-07

UX overhaul of the provider settings form. 20 of 22 recommendations from
the v1.1.x audit landed; #16 (i18n via translation_key) and #18
(cross-plugin x_token share with yandex_smarthome) are deferred to v1.3.0.

### Added

- **Numbered setup checklist** (#6) above the auto-create button: 4 rows
  (Sign in → Confirm code → Register skill → Wait for moderation) with
  ✓/→/☐/✗ markers showing live progress through the flow.
- **Visual user_code emphasis** (#7) during Device Flow: code rendered on
  its own LABEL row with `«guillemets»`, ⏱ countdown to expiry, and
  separate rows per instruction step.
- **Actionable post-DONE message** (#10) with three example voice
  commands interpolating the user's actual skill name (e.g. *«Алиса,
  попроси <skill name> включи джаз»*).
- **Identity card** (#5) replacing the bare Skill ID input after a
  successful auto-create: read-only summary with skill name, Skill ID,
  full webhook URL, and a `help_link` shortcut to the Yandex Dialogs
  dev console.
- **Test webhook reachability** action (#11) — outgoing POST with a
  sentinel envelope, classifies the response across DNS / TLS / 401 /
  502 / timeout. Catches reverse-proxy issues *before* the user spends
  a Device Flow + moderation cycle. New module: `provider/webhook_probe.py`.
- **Drift-detection LABELs with preview + revert** (#13). When the
  MA-side Skill name diverges from `last_known_name`, the rename
  cluster now shows the activation-phrase change (*«Алиса, попроси
  Old …» → «Алиса, попроси New …»*), the moderation timeline, and a
  Revert button to discard the half-typed rename.
- **Regenerate webhook secret** action (#3) in the Advanced section —
  rotates the secret and resets the auto-create state, so a stray
  manual edit can't silently orphan the registered URL.
- **Diagnostics LABEL** (#17) in Advanced: webhook hit count, valid
  intent count, and "last webhook N sec ago". Counters live on the
  loaded plugin instance and reset per process.
- **Skill name validation** (#9) — `≥ 2 words` + 2-64 chars enforced
  via `ConfigEntry.validate` *before* the Device Flow starts (Yandex
  rejects single-word names server-side; pre-check spares the user a
  failed pipeline).
- **External Base URL inline HTTPS warning** (#8) — description text
  flips to a ✗ error when the value is `http://`, a private IP, or a
  loopback host. Optional autodetect via `mass.streams.base_url` /
  `mass.webserver.base_url` (only when those are *publicly* HTTPS).
  New module: `provider/url_helpers.py`.
- **Categories** (#15): Setup / Voice control / Advanced — entries are
  now grouped via `ConfigEntry.category` for progressive disclosure.
- **Instance-name split toggle** (#1) — by default the Skill name doubles
  as the MA-side instance name; flip
  `CONF_USE_DIFFERENT_INSTANCE_NAME` in Advanced to expose a separate
  `Instance name` field.

### Changed

- **Action button label flip** (#19): every label now says what *will
  happen* on the next click ("Sign in to Yandex Passport", "I confirmed
  — continue", "Continue setup", "Create another skill", "Try again")
  rather than what just happened. The Cancel button morphs into "Reset
  (start over)" in FAILED state to signal the wider scope (#21).
- **Auto-clear stale Device Flow session** (#14) — when the form opens
  with a persisted `device_session_blob` whose `expires_at_epoch` is in
  the past, drop it silently and render a clean IDLE state instead of
  a "Confirm and continue" button against an already-expired code.
- **Auto-enable voice control on first DONE** (#2) — the "Enable dialog
  skill" toggle moves to the Voice section and flips to True
  automatically after a successful auto-create. Power users can still
  switch it off afterwards.
- **OAuth token + Skill ID + Webhook URL secret** moved to Advanced and
  marked `read_only` once the skill is configured (#3, #4, #5). The
  fields are still editable in Advanced for manual recovery.
- **Voice-controllable players** moved up into a dedicated Voice
  control section (#12) so the user notices it during initial setup.
- **Markdown-free rendering** (#22). Phase 0 confirmed Music
  Assistant's frontend renders `ConfigEntry(LABEL)` as plain text
  (Vuetify v-alert with `white-space: normal`). All markdown-style
  emphasis was replaced with multi-LABEL splits (each row on its own
  v-alert block) + Unicode emoji + `«guillemets»` for visual structure.

### Notes

- Form rendering style is plain text + Unicode emoji throughout.
  Markdown / HTML is *not* supported by the MA frontend.
- Cross-plugin `x_token` share with `yandex_smarthome` (#18) is deferred
  to v1.3.0 — it requires a sibling refactor of the token store.
- i18n via `translation_key` (#16) is deferred to v1.3.0 — it requires
  Lokalise infra + RU/EN translation tables.

## [1.1.2] — 2026-05-06

### Fixed

- **Critical: provider settings page froze and triggered an infinite
  `--- Logging error ---` storm in MA's stdout** when the user opened the
  Yandex Alice config form (~93 markers/sec; in dev container a 7,000-line
  spam blew up before the user could close the dialog).

  Root cause: the `_resolve_saved_value` helper introduced in v1.1.0 (as a
  code-review fix for SECURE_STRING fields the frontend doesn't echo back)
  called `await mass.config.get_provider_config(instance_id)` inside
  `get_config_entries`. MA invokes `get_config_entries` *while* it holds
  the config-controller lock, so our recursive read deadlocked against
  the same lock. The deadlocked task starved the queue-listener thread,
  which started swallowing log records and emitting handler-error markers
  in a tight loop.

  Fix: drop the `mass.config` fallback. `_resolve_saved_value` now reads
  only from the form `values` dict (which the frontend always populates
  for non-secret keys, and which our dispatcher writes secrets back into
  early in the call so subsequent action clicks within the same session
  see stable values). Helper is sync again; its three callers no longer
  need `await`.

  Webhook-secret stability across action clicks (the original concern of
  the v1.1.0 code-review thread) is preserved — the secret is generated
  once in the dispatcher and immediately written back into `values`, so
  any `backend_uri` assembled below uses the same value as the form will
  save on Save.

  Verified locally in a Music Assistant dev container: the form opens
  instantly, no log-error spam, no log-file stall.

## [1.1.1] — 2026-05-06

### Changed

- **Tests now use the upstream import path.** All `from provider import ...`
  / `import provider` switched to `music_assistant.providers.yandex_alice.*`
  (with constants pulled from the `.constants` sub-module rather than
  re-exported via `__init__.py`). Matches the convention sibling provider
  test suites use in `music-assistant/server`. `conftest.py`'s alias-magic
  registers both names, so the source-repo test run keeps working.
- **Strict mypy compliance in tests** — added missing return-type and
  parameter annotations on inner async helpers (`_capture(**kwargs: Any) ->
  AutoCreateOutcome`, `_fake_refresh(self: Any, x_token: SecretStr) ->
  None`, `_FakePassportClient.__init__/close` typed). Guarded `await_args`
  with explicit `is not None` asserts before `.kwargs` access.
- **Form `values` dicts are typed `dict[str, Any]`** in tests — previously
  inferred as `dict[str, str]`, which mypy strict (in upstream MA) rejects
  against `get_config_entries`'s `dict[str, ConfigValueType] | None`
  signature.

### Fixed

- Upstream `music-assistant/server` CI (Lint & Type Check + Pytest) — the
  test suite now passes both jobs out of the box. No provider-runtime
  changes; this release is test-and-tooling only.

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
