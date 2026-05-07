# Research: replacing the in-house NLU — platform vs. library options

**Date:** 2026-05-07
**Sources:** Yandex Dialogs official docs (`yandex.ru/dev/dialogs/alice/doc/ru/nlu`), web searches across NLU libraries (Rasa, Snips, Yargy/Natasha, pymorphy3, Picovoice Rhino, DeepPavlov, HassIL), code review of `provider/dialogs_nlu.py` + `provider/dialogs_control.py`.

**Goal:** Determine whether our hand-rolled regex NLU (`parse_command`, `parse_control`, `_normalize_player_token`) can be fully or substantially replaced by either (a) Yandex Dialogs' platform-provided NLU or (b) an off-the-shelf library, and at what cost.

**TL;DR:** Full replacement is impossible — player-resolution against the user's dynamic device list and music search are domain logic that lives in MA, not in any NLU. Substantial replacement is possible in two layers, with very different cost/benefit:

- **Quick win (low risk):** Drop in `pymorphy3` for the morphology layer (`_INFLECTION_SUFFIXES` in `dialogs_nlu.py:289` and inflection of search queries). ~50 lines of changes; replaces a hand-rolled stemmer with a real lemmatizer.
- **Architectural lift (medium risk):** Replace `parse_command` + `parse_control` regex catalogues with either **Yargy** (in-repo Russian grammar parser, locally testable) or **Yandex grammar DSL** (platform pre-classification, lives in dev console with 5–15 min moderation latency).

The platform option (Yandex grammar DSL) is more accurate when grammars match but ships with operational drawbacks (no offline tests, undocumented `app-store-api` payload, moderation lag). Yargy is the closest in-process equivalent and is what we'd reach for if we want to outsource the grammar but keep it in the repo.

---

## Part 1 — Current architecture

Two parser modules + a player resolver, all in-process:

- `provider/dialogs_nlu.py:148` — `parse_command()`: regex parser for **play intents**. Output: `kind ∈ {track,artist,album,playlist,my_wave,genre,search}`, `query`, `player_hint`, `radio_mode`, `enqueue_option`.
- `provider/dialogs_control.py:66` — `parse_control()`: ~60 anchored regex patterns for **playback control** (pause/resume/stop/next/prev, volume up/down/set, mute/unmute, list/forget players, now_playing, shuffle/repeat, seek, transfer).
- `provider/dialogs_nlu.py:289` — `_normalize_player_token()`: Russian inflection-suffix stripper for fuzzy player-name matching, with a four-tier resolver (exact → startswith → contains → generic-word fallback).

**No grammar/intent declarations are sent to Yandex Dialogs.** `auto_create.py` and `dialog_skill_meta.py` register the skill without intents — Yandex passes the raw normalised user phrase via `request.command` and we do everything else server-side.

---

## Part 2 — Option A: Replace with platform NLU (Yandex Dialogs)

### What the platform offers (per `yandex.ru/dev/dialogs/alice/doc/ru/nlu`)

**Free, no grammar declared** — every `SimpleUtterance` already includes:

- `request.command` — already normalised (lowercase, punctuation stripped, written numbers→digits: «тридцать»→`30`).
- `request.nlu.tokens` — pre-tokenised words.
- `request.nlu.entities` — typed extractions: `YANDEX.NUMBER`, `YANDEX.DATETIME`, `YANDEX.GEO`, `YANDEX.FIO`.
- `request.markup.dangerous_context` — flag for suicide/violence content.

**With a custom grammar declared in the dev console**:

- `request.nlu.intents.<name>.slots.<slot>.value` ready to use.
- Free morphology via `%lemma` directive (one rule covers all word forms).
- `%exact` for proper names; `%negative` for excluding phrasings.
- `YANDEX.STRING` slot type for free-text capture.
- Custom entities (e.g. `entity ChessPiece: values: queen: ферзь | королева`).

### Coverage analysis per current layer

| Our layer | Replaceable by platform? | Notes |
|---|---|---|
| `parse_command` (play intents + free-text query) | **Partially** — via grammar DSL | Can describe `play.track`/`play.album`/`play.playlist`/`play.artist`/`play.my_wave`/`play.genre`/`play.search` with slots `kind`, `query`, `player`. Morphology of verbs/markers becomes free via `%lemma`. But `query` is `YANDEX.STRING` (substring capture) — the platform doesn't *understand* track names, just delineates them. Music search stays ours. |
| `parse_control` (~60 patterns) | **Yes, ideal fit** | Closed set of control phrasings, no free text — exactly what grammar DSL is for. `%lemma включить` collapses every `(?:включи(?:те)?\|включай(?:те)?\|…)` regex branch. |
| Numeric parameters (volume_set, seek N сек/мин) | **Yes, better via platform** | Today `_VOLUME_SET_RE` catches «громкость 30» but misses «прибавь на двадцать». `YANDEX.NUMBER` surfaces the integer regardless of phrasing — works against the implicit entity set, no grammar needed. (P1.7 in `VOICE_UX_RESEARCH.md`.) |
| `_normalize_player_token` (Russian declensions on player names) | **No** | `YANDEX.FIO` is for people, `YANDEX.GEO` for cities. Player names are user-defined — could declare them as a `entity Player` in the grammar, but every device add/rename would require `PATCH /draft` + 5–15 min moderation per change. Operationally unworkable. |
| `parse_command`'s false-split detector ("включи песню На заре" → mis-split «На заре» as player hint, `dialogs_nlu.py:225`) | **No** | Semantic disambiguation against the *user's* device list — platform doesn't know who has a speaker named «спальня». |

### Operational drawbacks (already documented in `VOICE_UX_RESEARCH.md:146,338`)

1. **Grammar lives in the dev console**, not in the repo. Every change = `PATCH /draft` via `app-store-api` + `request_deploy` + **5–15 min moderation** for our private `aliceSkill`.
2. **The grammar payload field in `app-store-api` is undocumented.** Programmatic updates need a Playwright DevTools probe of a manually-grammar-edited skill (same approach we used for `structuredExamples`).
3. **No offline NLU runner** → ~350 lines of unit tests in `tests/test_dialogs_nlu.py` + `tests/test_dialogs_control.py` would have to convert to E2E against a live draft.
4. **Player names are dynamic per user** — can't be declared as entities in a shared grammar.
5. **`YANDEX.STRING` captures substrings, doesn't understand them** — search/inflection logic stays ours regardless.

### Verdict on Option A

**Full replacement: impossible.** Player resolution and music search are not NLU-shaped problems.

**Recommended scope (gradual):**

1. Use `YANDEX.NUMBER` from `request.nlu.entities` for relative-volume phrasings («прибавь на двадцать») — implicit entity set, no grammar needed. ~30 LoC. (P1.7.)
2. Honour `request.markup.dangerous_context` with a graceful fallback. (P1.6.)
3. Custom intents grammar (P1.1) — defer until regex parser shows real-world coverage gaps. As of v1.2.3 it hasn't.

---

## Part 3 — Option B: Replace with an off-the-shelf NLU library

Constraints from our deployment:

- **Russian language** required (drops Snips, Picovoice Rhino — no Russian in their open tiers).
- **In-process Python** inside the MA server (drops Rasa NLU server-mode, drops 100MB+ DL models).
- **Declarative rules**, no labelled corpus (drops DeepPavlov, drops Rasa supervised classifiers).
- **Domain**: ~30 control intents + 7 play intents with one free-text slot.

### Category A — Russian morphology helpers (drop-in replacements for the suffix stripper)

| Library | Footprint | Fit |
|---|---|---|
| **pymorphy3** | Pure Python; OpenCorpora dict ~30 MB; >5000 words/sec | ⭐ **Direct replacement for `_INFLECTION_SUFFIXES`** in `dialogs_nlu.py:289`. Real lemmatizer covers all Russian declensions correctly, not just the 17 suffixes we hand-listed. Drop-in: `morph.parse('кухню')[0].normal_form == 'кухня'`. Active fork of unmaintained `pymorphy2`. |
| **razdel** | Pure Python, no models | Russian tokeniser/sentence splitter. Replaces `_PUNCT_RE` + `_SPACE_RE`. Low ROI on its own, free addition if pymorphy3 is already pulled in. |
| **mawo-pymorphy3** | Fork of pymorphy3, OpenCorpora 2025 dict | Drop-in compatible; newer dictionary with more brand names. Equivalent to pymorphy3 for our use case. |

### Category B — Rule-based grammar parsers for Russian

| Library | Architecture | Fit |
|---|---|---|
| **Yargy** (`natasha/yargy`) | Earley parser, grammar built on top of pymorphy, pure Python. Used in production at Sberbank, Interfax, RIA Novosti | ⭐ **The closest in-process equivalent to Yandex grammar DSL.** Describe rules with predicates over lemmas (`gram('VERB')`, `dictionary({'включить'})`); morphology, declensions, synonyms come for free without regex combinatorics. Could replace both `parse_command` and `parse_control`. **Locally testable** (the platform DSL isn't). |
| **Natasha** | pymorphy + razdel + slovnet (DL NER/syntax) | NER layer doesn't help foreign band names (same blind spot as `YANDEX.FIO`). Worth pulling in only if we want pymorphy + razdel + Yargy under one umbrella. |

### Category C — General-purpose NLU frameworks

| Library | Russian | Verdict |
|---|---|---|
| **Rasa NLU** | Via spaCy `ru_core_news_*` | ❌ Heavy: PyTorch + transformer models, hundreds of MB. Designed as a **server** with REST API, not a library. Requires labelled training data (~50–200 utterances/intent). Mismatch for in-process plugin. |
| **Snips NLU** | ❌ no Russian | en/fr/de/es/it/ja/ko/pt/zh only. **Project unmaintained** since Sonos acquired Snips in 2020. |
| **DeepPavlov** | ✅ native Russian focus | Heavy DL models, GPU recommended, requires training data. Research-pipeline tool, not embedded library. |

### Category D — Embedded speech-to-intent / on-device intent engines

| Library | Russian | Verdict |
|---|---|---|
| **Picovoice Rhino** | ❌ (en/fr/de/it/ja/ko/pt/es/zh; Russian only via commercial custom contract) | Speech-to-Intent — combines ASR + NLU. We don't need ASR (Yandex provides text). Russian unavailable in open tier. |
| **Mycroft Adapt** | ❌ English-centric | Keyword-based intent matcher. **Project dead** — Mycroft AI shut down in 2023. |

### Category E — Smart-home intent matchers

| Library | Russian | Verdict |
|---|---|---|
| **HassIL** (Home Assistant) | ✅ in-progress (`home-assistant/intents`) | YAML template matcher, conceptually similar to Yandex grammar DSL. Built on Lark. From HA 2025.9 includes a fuzzy-matcher pre-trained per language. **Drawback**: Russian sentence support flagged as needing a "Russian Language Leader" — case agreement is hard. Worth tracking if MA-team aligns with HA-voice ecosystem; for now our regex layer is more mature. |

### Category F — LLM / embeddings

Multilingual embedding models (`paraphrase-multilingual-MiniLM-L12-v2`, ~120 MB) could do semantic intent classification. Rejected: (a) overkill for 30 deterministic intents; (b) ~120 MB model bundled with the plugin; (c) slot extraction would still need rules.

---

## Part 4 — Decision matrix

| Goal | Approach | Effort | Risk | When to do it |
|---|---|---|---|---|
| Better morphology for player names + query | **pymorphy3** + razdel | ~50 LoC + tests | Low | Anytime; obvious win, dependency footprint is tiny. |
| Better number capture in volume commands | **`request.nlu.entities` (`YANDEX.NUMBER`)** | ~30 LoC + mocked-payload tests | Low | P1.7; independent of any grammar work. |
| Replace regex catalogues with declarative rules, in-repo | **Yargy** | Substantial — re-architect both parsers; tests rewrite | Medium | If regex flexibility starts to bottleneck; today it doesn't. |
| Replace regex catalogues with declarative rules, on platform | **Yandex grammar DSL** (P1.1) | Substantial + ops complexity (moderation lag, undocumented payload, E2E-only tests) | Medium-high | Only if we want platform-side pre-classification benefits AND accept the ops trade-offs. Yargy is preferable for keeping things in-repo. |
| Replace player resolver | — | — | — | Not feasible — domain logic, not NLU. |

### Recommended sequence

1. **pymorphy3 drop-in** for inflection (immediate, low risk).
2. **`YANDEX.NUMBER` for relative-volume** (immediate, low risk; independent of #1).
3. **Defer** Yargy / Yandex grammar — premature until the regex parser shows concrete user-visible coverage gaps.

---

## Part 5 — Deep dive: platform NLU ecosystem (2026-05-07 follow-up)

This section adds findings from a second-pass investigation focused on (a) full grammar DSL specification, (b) the `AlexxIT/YandexDialogs` precedent, (c) Python ecosystem around Yandex Dialogs, (d) real-world auto-moderation timing.

### 5.1 Grammar DSL — complete directive list

| Directive | Purpose | Notes |
|---|---|---|
| `%lemma` | Match without word-form variation | One rule covers «включи / включите / включай / включить / включим». |
| `%exact` | Exact string match, no morphology | For proper nouns. |
| `%negative` | Negative rules | **Must be more specific than positive rules to function correctly.** |
| `%positive` | Switch back to positive rules | Found in deeper docs; not in our previous survey. |

**Quantifiers:** `?` (0 or 1), `*` (≥0), `+` (≥1).

**`[]` operator** ignores word order — `[включи свет]` matches both «включи свет» and «свет включи». **No regex equivalent in our `parse_command`.**

### 5.2 Free built-in intents

When we declare any custom intent, the platform automatically classifies these alongside ours:

- `YANDEX.CONFIRM` — yes/agreement («да», «хорошо», «давай»)
- `YANDEX.REJECT` — no/refusal («нет», «не надо», «отмена»)
- `YANDEX.HELP` — help requests
- `YANDEX.REPEAT` — «повтори»

**Critical implication for our P0.3 / P0.4 disambiguation flows** (`VOICE_UX_RESEARCH.md`): yes/no/cancel handling becomes free as soon as we declare *any* custom intent, even an empty one. Today these are hand-rolled regex in `dialogs_control.py`. This is a **cheap intermediate step** between "all in-house" and "full grammar migration".

### 5.3 Auto-moderation timing — refined

Previously we cited "5–15 min". Reality from community sources (forum posts, Yandex blog comments):

- **Public skills:** up to 3 days per official docs.
- **Private skills:** auto-moderation, **«минуты до нескольких часов»**. Email notification on completion.
- **Every grammar update = re-moderation.** Confirmed by `AlexxIT/YandexDialogs`: "Intent modifications require skill republication, requiring several minutes per update."

**New constraint:** *«Интенты можно настраивать только после публикации навыка»* — intents cannot be edited on a fresh draft, only **after first publication**. This changes our `auto_create.py` bootstrap sequence: publish a minimal draft first, then PATCH grammar, then re-submit for auto-moderation.

### 5.4 Direct precedent — `AlexxIT/YandexDialogs`

The same architecture pattern (programmatic creation of a private skill via `app-store-api` + grammar DSL declaration + webhook receiving pre-classified intents) is in **production** as a Home Assistant component for the Russian smart-home community. README confirms:

- Auto-creates a private skill, publishes it (similar to our `auto_create.py` flow).
- Declares intents via the platform DSL.
- Webhook fires `yandex_intent` events with pre-classified `intent` + extracted slots.
- Confirms our predicted moderation cost: "several minutes per update".

**Grammar examples from their README:**

Calculator with `YANDEX.NUMBER` slots:
```
root:
    сколько будет $x $action $y
slots:
    x: { source: $x, type: YANDEX.NUMBER }
    y: { source: $y, type: YANDEX.NUMBER }
    action: { source: $action }
$x: $YANDEX.NUMBER
$y: $YANDEX.NUMBER
$action: плюс | минус | умножить на | разделить на
```

Room enum with custom values (analogous to what we'd want for player names *if* the list were static):
```
root:
    [(какая)? температура $room]
    [сколько градусов $room]
slots:
    room: { source: $room }
$room:
    в зале | в ванной | на балконе
```

**Applicability to our case:** the room enum is the closest analogue to our player resolver. It works for `AlexxIT/YandexDialogs` because room names are static per-installation. **Our player list is dynamic per Music Assistant install** — we can't bake names into a shared grammar without per-user grammar generation, which means PATCH+re-moderation on every device add/rename. Confirms the existing recommendation to keep player resolution in-house.

### 5.5 Python ecosystem inventory

| Project | Role | Relevance to us |
|---|---|---|
| `mahenzon/aioalice` | Asyncio wrapper for the Dialogs protocol | Duplicates what `dialogs.py` already does. ROI ~0. |
| `K1rL3s/aliceio` | Python 3.8+ alternative | Same. |
| `LazyDeus/alice_types` | Pydantic v2 models for request/response | **Worth evaluating** — could replace ad-hoc `dict[str, Any]` typing in our handler with proper types. Independent of any NLU decision. |
| `avidale/dialogic` | **Hybrid framework** explicitly supporting "built-in intent classifiers or third-party NLU tools, including grammars from Yandex or any Python-available models". Cascade handler routing with priorities. | Conceptually mirrors the hybrid (platform NLU + our parsers as fallback) we'd build for P1.1. Reference design, not a drop-in. |
| `denismosolov/alice-entities-library` | Community entity definitions (FIGI, languages, car makes, parts of speech) | **No music entities** today. If we go grammar route, the format is established for contributing `entity Genre` / `entity Artist`. |
| `vb64/test.helper.yandex.alice.flask` | **Only Python-side test emulator** | Worth probing — if it covers `request.nlu.intents` emission, we'd have local grammar-test capability. Likely envelope-only. |

### 5.6 Local grammar testing — confirmed dead-end in Python

| Tool | Language | What it does |
|---|---|---|
| `vitalets/alice-tester` | Node.js | E2E against live skill |
| `popstas/yandex-dialogs-tester` | Node.js | CLI for CI |
| Yandex Test Proxy | Browser | Official, uses real grammar |
| `alice-dev.vitalets.xyz` | Browser | Live device debugging without publish |
| `alice-cloud-proxy` | Cloud Function | Webhook proxy to dev box |
| `vb64/test.helper.yandex.alice.flask` | Python | Envelope emulator (extent of NLU coverage unverified) |

**No tool runs Yandex grammar offline in Python.** All grammar validation requires either publication or live skill round-trip. This was already the leading reason to prefer Yargy in-repo over platform DSL; the second-pass research only reinforces it.

### 5.7 Tomita → Yargy lineage

`popstas` blog post (2020): *«Под конец простые регулярные выражения перестали хватать для понимания запросов пользователей, и я начал экспериментировать с Tomita-parser»*. Tomita was Yandex's closed-source C++ rule-based parser; **Yargy is its open-source successor** built on top of pymorphy. The historical evolution `regex → Tomita/Yargy → platform grammar DSL` is independently documented by another developer hitting the same scaling wall we're approaching.

### 5.8 Updated decision sequence

Changes to recommendations from Part 4:

1. **Unchanged:** pymorphy3 drop-in (low risk, immediate).
2. **Unchanged:** `YANDEX.NUMBER` for relative-volume (low risk, immediate).
3. **New cheap step:** declare a **single trivial custom intent** to enable free `YANDEX.CONFIRM` / `YANDEX.REJECT` / `YANDEX.HELP` / `YANDEX.REPEAT` classification. ~1 round of moderation, gets ~10 lines of regex out of `dialogs_control.py`. Enables cleaner disambiguation prompts (P0.3/P0.4).
4. **Defer with confidence:** full grammar migration (P1.1) — `AlexxIT/YandexDialogs` precedent confirms feasibility but also confirms ops cost (re-moderation per change, no offline tests). Yargy remains the in-repo alternative for when/if regex coverage breaks.
5. **Possible future:** evaluate `LazyDeus/alice_types` for type-safety improvements independent of NLU decisions.

---

## Sources

### Yandex Dialogs platform NLU

- [NLU — токены, сущности, кастомные интенты](https://yandex.ru/dev/dialogs/alice/doc/ru/nlu)
- [Формат запроса (request.nlu structure)](https://yandex.ru/dev/dialogs/alice/doc/ru/request)
- [SimpleUtterance](https://yandex.ru/dev/dialogs/alice/doc/ru/request-simpleutterance)

### Russian morphology libraries

- [pymorphy3 (PyPI)](https://pypi.org/project/pymorphy3/)
- [pymorphy3 GitHub (no-plagiarism/pymorphy3)](https://github.com/no-plagiarism/pymorphy3)
- [mawo-pymorphy3 (OpenCorpora 2025 dictionary)](https://github.com/mawo-ru/mawo-pymorphy3)
- [spaCy Russian lemmatizer (uses pymorphy3)](https://spacy.io/api/lemmatizer)

### Russian NLP toolkits

- [Natasha project](https://github.com/natasha/natasha)
- [Yargy parser](https://github.com/natasha/yargy)
- [Yargy examples (Jupyter notebooks)](https://github.com/natasha/yargy-examples)

### General NLU frameworks (rejected for our case)

- [Rasa NLU](https://github.com/RasaHQ/rasa)
- [Snips NLU (unmaintained, no Russian)](https://github.com/snipsco/snips-nlu)
- [DeepPavlov classifiers](https://docs.deeppavlov.ai/en/0.1.6/components/classifiers.html)
- [Picovoice Rhino — Speech-to-Intent](https://picovoice.ai/platform/rhino/)
- [Rhasspy intent recognition (Snips/Rasa comparison)](https://rhasspy.readthedocs.io/en/latest/intent-recognition/)

### Smart-home intent matchers

- [HassIL — Intent parsing for Home Assistant](https://github.com/OHF-Voice/hassil)
- [HA template sentence syntax](https://developers.home-assistant.io/docs/voice/intent-recognition/template-sentence-syntax/)
- [HA intents — Russian Language Leader discussion](https://github.com/home-assistant/intents/discussions/1074)

### Cross-references in this repo

- `docs/VOICE_UX_RESEARCH.md` § 1.2 (NLU primitives we already considered)
- `docs/VOICE_UX_RESEARCH.md` § 4 P1.1 (custom intents trade-offs)
- `docs/VOICE_UX_RESEARCH.md` § 4 P1.7 (`YANDEX.NUMBER` for relative-volume)
- `provider/dialogs_nlu.py` (current parse_command + player resolver)
- `provider/dialogs_control.py` (current parse_control catalogue)

### Part 5 — Additional sources (deep-dive follow-up)

Official documentation:
- [Модерация навыков](https://yandex.ru/dev/dialogs/alice/doc/ru/moderation)
- [Управление доступом / приватные навыки](https://yandex.ru/dev/dialogs/alice/doc/access.html)
- [Полезные ссылки и примеры](https://yandex.ru/dev/dialogs/alice/doc/ru/guides-and-examples)

Direct precedent:
- [AlexxIT/YandexDialogs (Home Assistant component using Yandex grammar)](https://github.com/AlexxIT/YandexDialogs)
- [AlexxIT/YandexDialogs README](https://github.com/AlexxIT/YandexDialogs/blob/master/README.md)

Community resources and ecosystem:
- [sameoldmadness/awesome-alice — catalogue of libraries and tools](https://github.com/sameoldmadness/awesome-alice)
- [popstas — practical experience building Alice skills (regex → Tomita)](https://blog.popstas.ru/blog/2020/04/14/yandex-dialogs/)
- [vc.ru — Dev Preview Яндекс.Диалогов](https://vc.ru/dev/121751-dev-preview-yandeksdialogov-novye-vozmozhnosti-i-novyi-format)

Python SDKs and adjacent libraries:
- [mahenzon/aioalice](https://github.com/mahenzon/aioalice)
- [K1rL3s/aliceio](https://github.com/K1rL3s/aliceio)
- [avidale/dialogic — hybrid platform/custom NLU framework](https://github.com/avidale/dialogic)
- [denismosolov/alice-entities-library — shared grammar entities](https://github.com/denismosolov/alice-entities-library)
- [LazyDeus/alice_types — Pydantic v2 protocol models](https://github.com/sameoldmadness/awesome-alice)

Testing tools:
- [vitalets/alice-tester (Node.js)](https://github.com/vitalets/alice-tester)
- [vitalets/alice-cloud-proxy](https://github.com/vitalets/alice-cloud-proxy)
