# Research: Yandex Alice custom skill capabilities + voice UX best practices

**Date:** 2026-05-05
**Source:** Yandex Dialogs official docs (yandex.ru/dev/dialogs/alice/doc), browsed via Playwright; Cathy Pearl *Designing Voice User Interfaces* (O'Reilly), Amazon Alexa Skills Kit conversational design docs, Google VUI guidelines; competitor analysis of music-category skills in dialogs.yandex.ru/store; DevTools captures of live skill traffic.

**Goal:** Identify which Yandex Dialogs features the MA dialog skill is *not* using, and which voice-UX patterns from Alexa/Google apply, so we can prioritise improvements that maximise everyday usability.

---

## Part 1 — Yandex Dialogs custom-skill capabilities

### 1.1 Webhook protocol (verified)

Request envelope (`POST {backend_uri}`):

```json
{
  "meta": {
    "locale": "ru-RU",
    "timezone": "Europe/Moscow",
    "client_id": "ru.yandex.searchplugin/...",
    "interfaces": { "screen": {}, "account_linking": {}, "audio_player": {} }
  },
  "request": {
    "type": "SimpleUtterance | ButtonPressed | Show.Pull",
    "command": "<normalised: lowercase, no punct, numbers as digits>",
    "original_utterance": "<raw, ≤1024 chars>",
    "markup": { "dangerous_context": true },          // optional, only on flagged content
    "payload": {},                                     // ButtonPressed only
    "nlu": {
      "tokens": ["слово1", "слово2", ...],
      "entities": [
        { "tokens": {"start": 2, "end": 6}, "type": "YANDEX.GEO|FIO|NUMBER|DATETIME", "value": {...} }
      ],
      "intents": { "<custom_intent_name>": { "slots": { "<slot>": {...} } } }
    }
  },
  "session": {
    "session_id": "...", "message_id": 0, "skill_id": "...",
    "user":        { "user_id": "<account-scoped, only if logged in>", "access_token": "<oauth>" },
    "application": { "application_id": "<device+app-instance>" },
    "new": true | false
  },
  "state": {
    "session":     { ... },                            // ≤1KB, our previous response.session_state
    "user":        { ... },                            // ≤1KB, persisted across sessions per Yandex account
    "application": { ... }                             // ≤1KB, persisted per device/app instance
  },
  "version": "1.0"
}
```

Response envelope:

```json
{
  "response": {
    "text": "≤1024 chars, what the screen + non-screen surfaces show",
    "tts":  "≤1024 chars, with TTS markup (+ accents, sil pauses, phonemes); <speaker> tags free",
    "card": { "type": "BigImage | ItemsList | ImageGallery", ... },
    "buttons": [
      { "title": "≤64 chars", "url": "≤1024 bytes", "payload": "≤4096 bytes", "hide": true|false }
    ],
    "end_session": false,                              // true ends the conversation
    "directives": { "start_account_linking": {} }      // triggers OAuth flow on screen-capable surfaces
  },
  "session_state":      { ... },                       // overwrite session-scoped state
  "user_state_update":  { ... },                       // merge into user-scoped state (null clears keys)
  "application_state":  { ... },                       // overwrite application-scoped state
  "analytics": { "events": [{ "name": "...", "value": {...} }] },  // AppMetrica
  "version": "1.0"
}
```

**Hard limits:**
- Total request → response round-trip: **≤4.5 s** (covers network in + skill processing + network out). Above this, Alice tells the user the skill didn't reply.
- `text` and `tts` **≤1024 chars each** (`<speaker>` audio-tag refs are not counted).
- Each of session/user/application state JSON: **≤1 KB**.
- Buttons: title ≤64, url ≤1024 bytes, payload ≤4096 bytes.
- Cards: `BigImage` (1), `ItemsList` (1–5 items), `ImageGallery` (1–7 items).
- `original_utterance` ≤1024 chars.

### 1.2 NLU — what we get for free

Even **without** declaring intents in the dev console, every `SimpleUtterance` request includes:

- `request.command` — **already normalised** by Yandex: lowercase, punctuation stripped, written numbers converted to digits (*"тридцать"* → `"30"`).
- `request.original_utterance` — raw user phrase (≤1024 chars), kept verbatim.
- `request.nlu.tokens` — pre-tokenised words (the parser already split on whitespace + punctuation).
- `request.nlu.entities` — typed extractions, each with `tokens: {start, end}` (token offsets into `nlu.tokens`) and a typed `value` block:

  | Entity type | `value` shape | Triggers / examples |
  |---|---|---|
  | `YANDEX.NUMBER` | `<integer or float>` (single scalar) | "тридцать процентов" → 30; "пять с половиной" → 5.5. Captures both numerals and spelled-out numbers. |
  | `YANDEX.DATETIME` | `{year, month, day, hour, minute, year_is_relative, …}` | "завтра", "в 6 утра", "через 2 часа", "14:00". Relative fields flagged with `*_is_relative`. |
  | `YANDEX.GEO` | `{country, city, street, house_number, airport}` (subset present) | Addresses, cities, airport codes. |
  | `YANDEX.FIO` | `{first_name, patronymic_name, last_name}` (subset present) | Russian personal names. Foreign names typically *not* picked up. |
  | `YANDEX.STRING` | `<arbitrary substring>` | **Only emitted when declared as a slot type in a custom-intent grammar** — not present in the implicit set. |

- `request.markup.dangerous_context: true` — flag set by Yandex when the phrase contains suicide / hate / threat content (we should respond gracefully).

If we *do* declare custom intents in the dev console (grammar-based, with slots), Yandex's NLU pre-classifies and gives us `request.nlu.intents.<name>.slots.<slot>.value` ready to go — we don't have to write our own regex parser. This is a meaningful refactor opportunity (see § 4.2).

#### 1.2.1 Custom-intent grammar DSL

Declared in the **dev console**, not in the request payload. Sketch:

```
intent: play.search

root:
    $Verb $Query
    $Verb $Query на $Player
    $Verb $Marker $Query
    $Verb $Marker $Query на $Player

slots:
    kind:    { source: $Marker, type: YANDEX.STRING }
    query:   { source: $Query,  type: YANDEX.STRING }
    player:  { source: $Player, type: YANDEX.STRING }

filler: пожалуйста | мне | сейчас

$Verb:   включи | поставь | запусти | сыграй | найди | открой | покажи
$Marker: песню | трек | альбом | плейлист | подборку | артиста | группу
```

Available directives inside grammar rules:
- `%lemma` — match without word-form variation (`%lemma включить` matches *включи / включите / включай / включить / включим*).
- `%exact` — precise string match (no morphology — useful for proper names).
- `%negative` — exclude phrasings.

Slots accept `type:` of any built-in entity (`YANDEX.NUMBER`, etc.) or `YANDEX.STRING` for free text.

#### 1.2.2 Applicability to music skill — what we use vs. leave on the table

| NLU feature | We use it? | Music-skill applicability |
|---|---|---|
| `request.command` (normalised) | ✅ | This is what our regex parser consumes. Correct choice — `original_utterance` is rarely useful (we don't need the raw casing/punctuation). |
| `request.nlu.tokens` | ❌ | Low value. We re-tokenise via `_PUNCT_RE` + `_SPACE_RE` ourselves; the duplication isn't material. |
| `YANDEX.NUMBER` entity | ❌ | **Notable miss for relative-volume.** "Громкость 30" works because Yandex normalises *тридцать* → `30` in `command` — our regex catches that. But "**прибавь на двадцать**" / "**сделай громче на пять**" don't carry the keyword *громкость*, so our `_VOLUME_SET_RE` misses them. `YANDEX.NUMBER` would surface the integer regardless of surrounding phrasing. See § 4 P1.7. |
| `YANDEX.DATETIME` | ❌ | Nothing in MA's current command surface needs a date or time. Future "включи через 5 минут" / sleep-timer would benefit, but that's feature creep, not UX-fix. |
| `YANDEX.GEO` | ❌ | Irrelevant — addresses/cities don't appear in music commands. |
| `YANDEX.FIO` | ❌ | Tempting for artist names but the entity is trained on *Russian* personal-name patterns. Foreign band names ("Iron Maiden", "Metallica") won't trigger; native artists ("Цой", "Гребенщиков") work fine through `mass.music.search` already. Net: not worth wiring. |
| `YANDEX.STRING` (declared in grammar) | ❌ | Only useful in combination with custom intents (§ 1.2.1). |
| Custom intents (grammar DSL) | ❌ | Replaces our regex parser with Yandex pre-classification. **Big architectural change**, see § 4 P1.1. Pros: free morphology, free synonyms, free filler-word handling. Cons: grammar lives in dev-console (outside repo), requires `auto_skill.py` extension to PATCH the grammar in draft, every grammar change = new `request_deploy` (5–15 min for private aliceSkill moderation), local testing impossible, harder to debug than regex. |
| `%lemma` / `%exact` / `%negative` directives | ❌ | Only relevant inside the grammar. |
| `request.markup.dangerous_context` | ❌ | We just blindly search for whatever the user said. See § 4 P1.6. |
| NLU block on `ButtonPressed` | n/a | `payload` is what we sent verbatim — no NLU needed. |

**Bottom line:** the only NLU primitive that pays off without going all-in on grammar is **`YANDEX.NUMBER` for relative-volume phrasings**. Custom intents are a P1 architectural lift, valuable but premature until the regex parser shows real-world coverage gaps (which it hasn't yet).

### 1.3 Persistent state (verified)

Three storage tiers, each ≤1 KB JSON:

| Tier | Lives in | Lifetime | When to use |
|------|----------|----------|-------------|
| `session_state` | `state.session` | Current conversation; ends on `end_session: true` or N-min inactivity timeout | Cross-turn context: "the player they just selected", "the search query they're refining" |
| `user_state` | `state.user` | Persists across sessions, **per Yandex account** (only if logged in) | User preferences: "default player", "preferred radio mode", "voice variations seen" |
| `application_state` | `state.application` | Persists per device/app instance (works without auth) | Surface-specific defaults: "this colonka should default to this player" |

We currently use **none** of these — our 200-entry in-memory `_last_player` LRU is a poor substitute that loses state on plugin reload. This is the single biggest correctness gap (see § 4.1).

### 1.4 Surface / interface detection (verified)

`meta.interfaces` is a dict of capability flags. Common flags:

- `screen` — device has a display (mobile, station-max, station-2, navigator, smart-screen, tv-app)
- `account_linking` — surface can run the OAuth dialog inline (mobile, screened stations)
- `audio_player` — surface has an audio player (most surfaces; absent on `tv-app` etc.)

We currently ignore this entirely. We always send `text` (not just `tts`), but never use `card` or `buttons`. On screened surfaces (mobile, station-max), we could surface clickable suggestions (see § 4.2).

### 1.5 TTS markup (verified)

Inside `response.tts` (separate from `response.text`):

- `+` before a vowel = stress mark, e.g. `"+атлас"` → "А́тлас"
- `sil <[ms]>` = explicit pause, e.g. `"включаю sil <[300]> рок"`
- `<[phonemes]>` = phoneme transcription override, e.g. `"транскрипция <[t r a n s k rr ii p c y j schwa]>"`
- Spaces between punctuation and the next word add 50–100 ms passive pauses.
- `<speaker audio="...">` plays a sound from the Yandex library or our uploaded sounds; not counted in the 1024-char limit.

Important nuance: `tts` is a **separate string** from `text`. The user sees `text` on screen; the user *hears* `tts`. So the typical pattern is:

```python
response = {
    "text": "Включаю Metallica на колонке Кухня.",
    "tts":  "Включ+аю металика sil <[200]> на кол+онке к+ухня.",
}
```

This lets us drop accent marks for English transliteration, add micro-pauses to make the response feel natural, and pronounce trade names correctly. We currently ship the same string for both.

### 1.6 Account linking & user identification

Three identifiers, each with different scope:

- `session.user.user_id` — Yandex-account-scoped, **per skill** (different across skills). Only present if the user is logged in to a Yandex account on the surface. Stable across devices.
- `session.application.application_id` — device+app-instance-scoped, **per skill**. Always present. Same Yandex account on phone vs station = two different `application_id`s.
- `session.skill_id` — our skill's UUID; useful only as a sanity check (verifies the payload came for *this* skill).
- `session.user.access_token` — appears only when the skill has account-linking configured AND the user has linked. OAuth Bearer token from our authorization endpoint.

For our use case (private, single-user MA install), we don't need OAuth account linking. Identifying the user as "the MA owner" via skill_id is sufficient. But `user_id` is the right key for `user_state` if we want per-account persistent prefs (e.g. "this Yandex user prefers DLNA player by default").

### 1.7 Buttons & cards (verified, partially used)

Buttons: array of `{title, url?, payload?, hide?}`. Three flavours:

- *Suggestion button* — `title` only. Click sends `title` back as a follow-up `SimpleUtterance` (so the skill processes it like the user said it).
- *Link button* — `title + url`. Opens browser. (Useful for "open MA UI" or skill home page.)
- *Payload button* — `title + payload`. Click triggers a `ButtonPressed` request with `request.payload` in the body. Lets us short-circuit NLU for known-disambiguation cases (e.g. "Did you mean Kitchen or Living Room?" → buttons with payloads `{"player_id": "p1"}` and `{"player_id": "p2"}`).

Cards: visual content for screen surfaces. Three layouts:

- `BigImage` — single image with optional title/description and a button overlay.
- `ItemsList` — 1–5 image+text rows (e.g. "Last 5 played albums" picker).
- `ImageGallery` — 1–7 horizontally scrollable images.

We don't use cards. On a station-max or phone screen, showing the resolved track's album art via `BigImage` would be a clear UX win.

### 1.8 Directives

`response.directives.start_account_linking` — kicks off the OAuth flow. The user is prompted ("Свяжите аккаунт, чтобы продолжить"); on success Alice re-asks the original utterance. We don't need this for v1 (no OAuth) but it's the standard mechanism if we ever add user-specific preferences gated by login.

### 1.9 Analytics & quality signals

- AppMetrica integration (`analytics.events` in the response) for custom event reporting.
- Yandex tracks built-in metrics: success rate (skill returned 200), satisfaction (👍/👎 votes from store page), session length.
- Skill catalog rating drives discoverability — even private skills can collect ratings from their authorised users.

### 1.10 Activation modes

- *«Алиса, попроси \<skill name\> …»* — explicit activation, what we use today. Robust but verbose.
- *Smart skill activation* — Yandex routes utterances **without** the prefix to the most-relevant skill if the user has the skill enabled and the utterance matches a registered intent + matches against Yandex's discovery model. Requires public publishing or explicit invitation; out of scope for our private skill.
- *Activation phrases* (`activationPhrases` field) — additional phonetic variants of the skill's name (e.g. for "Music Assistant" we could add "Музыка Ассистент", "Музыкальный Ассистент") so Alice's ASR has more chances to catch the activation. We currently set this to `[skill_name]` only.

---

## Part 2 — Voice UX best practices

Drawing from Cathy Pearl's *Designing Voice User Interfaces* (the canonical reference; she's now Head of Conversation Design at Google), Amazon Alexa Skills Kit interaction-model docs, and Google Assistant conversation design guidelines.

### 2.1 Foundational principles

**Voice is linear and fleeting.** The user can't re-read a spoken sentence and can't see what's coming. Long enumerated lists in voice fail catastrophically — Pearl's rule: **never read more than 3 options aloud**. Beyond that, prompt for a constraint ("В каком жанре?") or offer the most-likely option as a default.

**Cognitive load is the bottleneck.** Working memory holds ~3-4 items for ~15 seconds. Every additional clause in the response burns that budget. Bias to the shortest possible confirmation.

**Conversational expectations are inherited.** Users will say "пожалуйста", "будь добра", "сейчас давай-ка"; they expect graceful handling of false starts, repairs, and reformulations. They will *not* re-read the manual to find the magic phrase.

**Feedback latency matters more than throughput.** A 200 ms acknowledgement ("включаю…") feels alive; the same response delivered as a 1.5 s monolithic reply feels broken. Yandex's 4.5 s budget is generous *only if you fill it.*

### 2.2 Conversation-design patterns

| Pattern | Description | Our gap |
|---------|-------------|---------|
| **One-shot intent** | User packs everything into one utterance (`включи Metallica на кухне`). Skill resolves and acts; no follow-up. | Already supported. |
| **Slot elicitation** | User omits a required slot; skill asks for it, holds context, resumes when filled. ("Включи." → "Что включить?" → "Metallica" → playback starts.) | Not supported — we just respond «Не понял команду». |
| **Confirmation prompt** | For high-stakes actions (destructive, or ambiguous), confirm before acting. Soft confirmations ("Включаю Metallica…") often sufficient; hard prompts ("Подтвердите?") only when guess is uncertain. | We do soft confirmations correctly; never reach for hard. |
| **Disambiguation** | Multiple plausible matches → enumerate up to 3 ("Нашёл двух исполнителей: Bee Gees и Bee Gees Tribute. Какой включить?"). | Not supported — fuzzy match silently picks the first. |
| **Re-prompt** | First failure: helpful re-prompt ("Скажите название артиста или плейлиста"). Second: shortest possible help. Third: graceful exit. | We respond once and end the session. |
| **Implicit context carry** | "Включи Metallica на кухне" → "Поставь следующий" (no `на …` repeated, but skill remembers kitchen player). | Partially — our LRU does this **per session**, but loses state on plugin reload. |
| **Persona consistency** | Same brand voice across all responses. Our brand: helpful, brief, music-loving. | Inconsistent — error strings, success strings, hint strings have different tones. |
| **Alternative phrasings** | Accept synonyms users actually use (`сделай громче` = `volume up`; `следующая` = `next`; `громче на кухне` = `включи громче на кухне`). | Verb regex covers many forms; gap on volume/next/pause/stop verbs (no support for those at all in dialog skill). |
| **Surface-aware response** | Use card on screen, voice-only on speaker. | Not implemented. |

### 2.3 Russian-language specifics

- **Падежные формы** are the norm — users say "включи Металлику" (accusative) more often than "Metallica" (nominative). Our parser strips a small set of inflection suffixes for *player names* but not for *queries* — a query of "металлику" hits `mass.music.search` as-is and may miss exact-name index lookups.
- **Foreign band names** (Iron Maiden, Rammstein, Beatles) are voiced as Russian transliterations by Yandex's ASR — `айрон мейден`, `раммштайн`, `битлз`. Our search query becomes the transliterated form, which yandex_music's search handles well, but library-search (other providers) might not.
- **Verb of motion / aspect** — Russian distinguishes perfective ("включить, поставить, запустить") from imperfective ("включать, ставить, запускать"). Yandex's voice-to-text leans perfective. We now cover both (v1.7.21).
- **Diminutives and slang** are common — "включи металличку", "поставь свежак", "включи моих". Our parser misses these; better-than-fuzzy-search would need either Yandex's intent grammars or a thin synonym map.

### 2.4 Specific voice anti-patterns to avoid

- **Long acknowledgements.** "Я слушаю вас. Скажите, какую песню или какой альбом вы хотите включить, и в какой комнате это должно играть, или оставьте пустым для текущей колонки." — that's a wall. Pearl's rule: max one clause per response.
- **Echoing the whole utterance back.** "Вы сказали 'включи Metallica на кухне'. Я включаю Metallica на кухне." — redundant.
- **Yes/no questions with non-obvious answers.** "Включить?" without context fails. Either confirm with a soft echo ("Включаю") or offer 2 named options ("Включить Metallica или нашу любимую волну?").
- **Mode confusion.** Once we end a session, the user can't say "следующий" without re-saying the activation prefix. Either keep `end_session: false` and cap with a short "...скажи 'выход'" or accept that one-shot is the cost of brevity.

---

## Part 3 — Competitor analysis (Yandex Dialogs music-category skills)

Browsed `dialogs.yandex.ru/store/categories/music_audio` (318 skills total). Most are *content* skills (audiobooks, an artist tribute, instrument tuners). Two skills are functionally similar to ours:

### 3.1 Кубик Медиа — closest analog

- "Музыкальный сервис для бизнеса. Позволяет легально озвучивать коммерческие объекты через умную колонку. Доступ — по подписке."
- Activation: «попроси Кубик Медиа включить кофейню» / «включить лаунж»
- Intent shape: their slots are *typed by category* (cafe / lounge / party / etc.) with no free-form artist names. Simpler search space, fewer ambiguities.
- Lessons for us: their structuredExamples confirm the `{marker: "попроси", activationPhrase: ..., request: ...}` shape we're now using. They keep request phrases short and category-like (not full sentences) — this matches Yandex's NLU expectations.

### 3.2 Аудиокниги ЛитРес — content delivery patterns

- Featured launch phrases listed on store page ("How to launch"):
  - «Запусти ЛитРес»
  - «Запусти Буратино на ЛитРес»
  - «Продолжи последнюю книгу на ЛитРес»
  - «Открой популярное на ЛитРес»
  - «Найди Стругацких на ЛитРес»
  - «Покажи мои книги на ЛитРес»
- Verbs they support: **запусти, продолжи, открой, найди, покажи** in addition to **включи, поставь** that we cover.
- Second-position phrasing: "на ЛитРес" — our trailing "на \<player\>" pattern collides with their trailing "на \<skill name\>" pattern. Yandex strips the skill-name part automatically (it's the activation marker), so this is only a concern for *our own* `на …` parser; we already handle it correctly.
- Lesson: **users expect a wider verb set**. Adding `найди`, `открой`, `покажи` (esp. for screened surfaces with cards) is a small, high-value addition.

### 3.3 Top-rated skills (4.5★+) common patterns

- **Catalog-style tutorial** in description ("How to launch") with 4–6 example phrases. We currently ship 3 in `structuredExamples`.
- **Branded TTS** — most use `+` accent marks on their name to ensure pronunciation. We don't (we just send raw `skill_name`).
- **Card on screen surfaces** — even simple skills include a `BigImage` for the response when on screen. We don't.
- **End-session strategy** — most one-shot skills set `end_session: true` after the action; multi-turn skills keep `false` and prompt for next step.

---

## Part 4 — Recommendations for our MA skill

Ranked by **impact × effort**, with trade-offs noted. Status as of v1.7.21.

### Priority 0 — High impact, low effort (do first)

| # | Recommendation | Why | Sketch |
|---|----------------|-----|--------|
| **P0.1** | **Use `user_state` / `application_state` for last-player memory instead of in-memory LRU.** | Plugin reload, MA restart, even a config save wipes the in-memory cache → "включи Metallica" stops resolving to the previously-used player. State persists across these. ≤1KB easily fits per-session and per-application records. | Replace `_last_player` OrderedDict with reads/writes against `state.application.last_player_id` (always present) plus `state.user.preferred_player_id` (when logged in). Drop the LRU. |
| **P0.2** | **Split `text` from `tts`.** | Yandex's TTS mispronounces English band names (`металлика`, `айрон майден`); accent marks fix this. Costs 5 lines of code. | `tts` = `text` + accent annotations. For known bands, ship a small phoneme map (`Iron Maiden` → `<[a j r ə n m e j d ə n]>`). |
| **P0.3** | **Disambiguation prompt when multiple players match.** | Currently we silently pick the first alphabetically — that's the bug Pearl explicitly warns against ("never silently guess between options the user didn't see"). | If `len(tier) > 1`, return a question + suggestion buttons (`title=player.name`, `payload={"player_id": p.player_id}`). Set `end_session: false` and `session_state.pending_query`. On next request, if `request.type == "ButtonPressed"`, resolve via payload; if `SimpleUtterance`, retry resolve_player against the new utterance. |
| **P0.4** | **Slot-elicitation for missing query.** | "Включи." (silence on what to play) currently → "Не понял команду". Should → "Что включить? Можно сказать имя артиста, песни или плейлиста." Sets `session_state.awaiting_query=true`; next utterance is treated as the missing slot. | Add a tiny state machine in `dialogs.py:_handle_webhook` keyed off `session_state.awaiting_*`. |
| **P0.5** | **Add the verb set the catalog skills use:** `найди X`, `открой X`, `покажи X`, `продолжи` (≈ "resume current queue"). | Free coverage of patterns users learned from other Alice skills; they will try these reflexively. | Extend `_VERB_RE`. `продолжи` maps to `mass.player_queues.resume(player_id)` (no query). |
| **P0.6** | **Verb set for playback control:** `пауза / поставь на паузу`, `стоп / останови`, `громче / тише / громкость X`, `следующая / предыдущая`, `выключи`. | Currently the dialog skill is *play-only*. Smart Home skill covers these for Smart Home flow but not via the conversational skill — users learn one model and want it everywhere. | New `kind=control` family. Map to `mass.player_queues.pause()`, `mass.player_queues.next()`, etc. Keep `radio_mode=False`; no search needed. |
| **P0.7** | **Inflect query when searching.** | `включи металлику` (accusative) → `mass.music.search("металлику")` → exact-name index miss. Strip the same inflection suffixes we use for player names from the query before searching. | Single line change in `resolve_query` — call `_normalize_player_token` on `parsed.query` and pass that as a fallback if the literal query returns no results. |

### Priority 1 — Medium impact, medium effort

| # | Recommendation | Why | Sketch |
|---|----------------|-----|--------|
| **P1.1** | **Declare custom intents in the dev console grammar.** | Replaces our hand-rolled regex with Yandex's NLU pre-classification. Free benefit: handles synonyms, declensions, filler words ("пожалуйста, мне, сейчас"), and morphology automatically — none of which our suffix-stripper covers. Status as of v1.8.0: not blocking any concrete user complaint, but the upper bound on regex flexibility is being approached. | Define intents `play.specific` (slots: `kind`, `query`, `player`), `play.my_wave`, `play.genre`, `control.*`. **Trade-offs to accept first**: (a) grammar lives in Yandex dev console, outside the repo — every change is a `PATCH /draft` + `request_deploy`, with 5–15 min moderation latency per change for a private aliceSkill; (b) the API field name for the grammar block in `app-store-api`'s draft payload is undocumented — needs a Playwright DevTools probe of a manually-grammar-edited skill, same as we did for `structuredExamples`; (c) local unit-testing impossible (no offline NLU runner), so regression tests would have to be E2E against a real skill draft; (d) keep `parse_command` + `parse_control` regex parsers as fallback for when `request.nlu.intents` is empty (Yandex returns nothing when grammar doesn't match). |
| **P1.2** | **Rich responses on screen surfaces.** | On `meta.interfaces.screen` present, attach a `BigImage` card with album art for the resolved item. Voice-only surfaces fall back to text gracefully (Yandex auto-handles this). | After resolving media, fetch its `image` attribute and include `card: {type: "BigImage", image_id: <upload>, title: track.name, description: artist.name}`. |
| **P1.3** | **Suggestion buttons for likely follow-ups.** | After `включи Metallica`, the most likely follow-up is "следующая", "пауза", "громче". Adding suggestion buttons short-circuits the activation-phrase requirement on screen surfaces. | Always append `[{"title": "Следующая", "hide": false}, {"title": "Пауза"}, {"title": "Громче"}]` to playback responses on `meta.interfaces.screen`. |
| **P1.4** | **Session continuation (`end_session: false`) + 30 s window.** | Lets the user issue follow-ups without saying "Алиса, попроси \<name\>" again. Trade-off: voice surfaces enter a "listening" indicator that some users find intrusive. Make it opt-in via plugin config. | Keep session open after playback action; close on explicit "выход / стоп / спасибо". |
| **P1.5** | **Activation-phrase variants** (`activationPhrases` array). | More variants = better ASR catch rate. Today we ship `[skill_name]` only. | Submit `[skill_name, skill_name + " plus"]` plus user-configurable additional phrases via plugin config. |
| **P1.6** | **Graceful response for `markup.dangerous_context`.** | Yandex flags suicide/violence content. Music skill responding "Не нашёл такую музыку: убей себя" is bad PR. | If `markup.dangerous_context` is set, respond with a generic "Не понял команду." and end session. |
| **P1.7** | **Use `YANDEX.NUMBER` entity for relative-volume phrasings.** | Phrases like *"прибавь на двадцать"*, *"сделай громче на пять"*, *"на 10 тише"* don't include the keyword *громкость*, so the existing `_VOLUME_SET_RE` regex doesn't capture the digit. `YANDEX.NUMBER` in `request.nlu.entities` surfaces the integer regardless of surrounding phrasing — the only NLU primitive that pays off without going all-in on grammar (P1.1). Independent of P1.1: works against the implicit entity set Yandex always emits. | Extend `parse_control` signature with `entities: list[Entity] | None`. New action `volume_relative(delta: int, sign: +1/-1)`. New patterns: `^прибавь(?:\s+на\s+\d+)?$`, `^убавь(?:\s+на\s+\d+)?$`, `^на\s+\d+\s+(?:громче\|тише)$`. When pattern matches but no digit captured, look up `YANDEX.NUMBER` from entities. Executor: `cmd_volume_set(player_id, current_volume + sign * delta)` with clamping. ~30 lines of code + tests with mocked NLU payloads. |

### Priority 2 — Future / lower priority

| # | Recommendation | Why | Sketch |
|---|----------------|-----|--------|
| **P2.1** | **Use `request.nlu.entities` for parsed track positions.** | "Включи третий трек" → `YANDEX.NUMBER:3` extracted automatically. Lets us index into a list returned in a previous response (saved in `session_state.last_results`). | Combine with P0.4 (slot elicitation). |
| **P2.2** | **AppMetrica analytics events.** | Self-monitoring of misclassifications, popular phrasings, error rates — feeds back into improving the parser. | Wire `analytics.events` for every parsed `kind`, every resolution outcome. Costs nothing if AppMetrica not configured. |
| **P2.3** | **Custom phoneme dictionary for music.** | Build a lookup of common foreign band names → IPA transcriptions. Improves TTS pronunciation when the response has to read the resolved item back. | Static dict of ~200 popular artists + manual additions. |
| **P2.4** | **Per-user preferred-player when `user_state` is available.** | If the user has linked OAuth (P2.5) or even just opted into a `user_state` write, we can store their preferred player as a persistent default, surviving session changes. | One bool: `user_state.preferred_player_id`. |
| **P2.5** | **OAuth account-linking** for multi-user MA installs. | For shared-MA installs (e.g., a household where each person has their own Yandex account), let each Yandex user have their own preferred player and search history. | Implement OAuth endpoints separately from Smart Home's. Significant effort; only worthwhile if multi-user becomes a real use case. |
| **P2.6** | **TTS branded-name pronunciation.** | Inject `+` stress marks into the activation name dynamically, e.g. *Музыкальный Ассистент* → `муз+ыкальный ассист+ент` in `tts`. | Static stress dictionary OR offload to a Russian phonemizer library (heavyweight). |
| **P2.7** | **Response time budget instrumentation.** | We have 4.5 s for the round-trip. Logging actual time per stage (NLU parse, resolve_player, mass.music.search) catches slow-search regressions before they cause user-visible failures. | Add `time.monotonic()` boundaries; log on >2 s end-to-end. |

### Anti-recommendations (intentionally not pursued)

- **Smart-skill activation (no prefix).** Requires public publishing + Yandex's discovery model. Would also create cross-skill conflicts on common verbs ("включи джаз" matched by 5 different skills). Stay private + explicit.
- **Long card galleries.** `ImageGallery` showing 7 search results: fine on phone, terrible on station-mini (no screen at all, response truncates). Better: top-1 result + "сказать 'дальше' для следующего" (linear navigation).
- **Hard yes/no confirmation prompts.** Pearl: "Confirmation prompts annoy 80% of users to fix the 20% case." Reach for them only when the action is destructive (removing from queue). Music playback is reversible — `Включаю Metallica` is enough.

---

## Sources

- Yandex Dialogs official documentation, Russian (browsed via Playwright):
  - [Обзор протокола](https://yandex.ru/dev/dialogs/alice/doc/ru/protocol)
  - [Формат запроса](https://yandex.ru/dev/dialogs/alice/doc/ru/request)
  - [Формат ответа](https://yandex.ru/dev/dialogs/alice/doc/ru/response)
  - [SimpleUtterance](https://yandex.ru/dev/dialogs/alice/doc/ru/request-simpleutterance)
  - [Настройка генерации речи](https://yandex.ru/dev/dialogs/alice/doc/ru/speech-tuning)
  - [Хранение состояния](https://yandex.ru/dev/dialogs/alice/doc/ru/session-persistence)
  - [NLU — токены, сущности, кастомные интенты](https://yandex.ru/dev/dialogs/alice/doc/ru/nlu)
- Cathy Pearl, *Designing Voice User Interfaces: Principles of Conversational Experiences* (O'Reilly, 2017) — VUI fundamentals; cognitive load, error recovery, persona design.
- Amazon Alexa Skills Kit:
  - [Conversational Voice Design Principles](https://developer.amazon.com/en-US/blogs/alexa/post/57d0bb9c-19a6-4c51-bfa2-fc6753d14b68/4-principles-of-conversational-voice-desig)
  - [Define the Dialog](https://developer.amazon.com/en-US/docs/alexa/custom-skills/define-the-dialog-to-collect-and-confirm-required-information.html) — slot elicitation, confirmation patterns.
  - [Design the Prompts](https://developer.amazon.com/en-US/docs/alexa/interaction-model-design/design-the-prompts-for-your-skill.html) — re-prompting strategy.
- Google Design — [Speaking the Same Language: Voice UI](https://design.google/library/speaking-the-same-language-vui).
- Competitor skills DevTools captures from `dialogs.yandex.ru/store/categories/music_audio` (Кубик Медиа, Аудиокниги ЛитРес, Память о Викторе Цое, Моцарт навсегда).
- Live PATCH/GET captures from our `2c22b323-…` and `6ccd006c-…` skills in the dev console (DevTools Network tab).
