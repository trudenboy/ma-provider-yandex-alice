# Voice command logic — Yandex Dialogs «Навык» (custom skill)

This document describes how the experimental dialog-skill webhook
parses Russian voice commands from Alice and resolves them to MA
playback actions. Implementation lives in
[`provider/dialogs_nlu.py`](../provider/dialogs_nlu.py),
[`provider/dialogs_player.py`](../provider/dialogs_player.py),
[`provider/dialogs_control.py`](../provider/dialogs_control.py), and
[`provider/dialogs.py`](../provider/dialogs.py) (HTTP handler).

## Wire format

Yandex sends a POST to
`{external_base_url}/api/yandex_dialogs/webhook/{secret}` with a JSON
envelope shaped like:

```json
{
  "session": {
    "skill_id": "<our-skill-uuid>",
    "session_id": "<per-conversation>",
    "user_id":   "<deprecated; always present, per-app-instance>",
    "new":       true | false,
    "user":      { "user_id": "<account-scoped; only when account-linked>" }
  },
  "request": {
    "type":              "SimpleUtterance" | "ButtonPressed",
    "command":           "включи металлику на проигрывателе",
    "original_utterance": "Алиса, попроси Музыкальный Ассистент …",
    "payload":           { "player_id": "..." }   // ButtonPressed only
  },
  "state": {
    "session":     { "last_player_id": "...", "pending_command": {...}, "awaiting_query": true },
    "application": { "last_player_id": "..." },
    "user":        { "preferred_player_id": "..." }
  },
  "version": "1.0"
}
```

We respond with a matching envelope that may set `response.buttons`,
`response.end_session`, and updated `session_state` /
`application_state` / `user_state_update` blocks. Everything we
remember about the user lives in those state buckets — there is no
in-process LRU cache.

## Webhook flow

The handler runs in this order; each step can short-circuit:

1. **Auth** — secret in URL path + `body.session.skill_id` match.
2. **Greeting** if `session.new=true` and command is empty.
3. **Awaiting-query re-entry** (P0.4): if previous turn set
   `state.session.awaiting_query=true`, prepend `включи ` to the new
   utterance unless it already starts with a play verb.
4. **Control parser** (`parse_control`, see below): if it matches,
   execute via `execute_control` and return a confirmation.
5. **Pending-command re-entry** (P0.3): if previous turn set
   `state.session.pending_command`, treat the new utterance (or button
   press) as the missing player choice and replay the saved play
   intent.
6. **Play parser** (`parse_command`, see below) → `ParsedCommand`.
7. **Slot elicitation** (P0.4): if `kind=search`, query empty, hint
   empty → ask "Что включить?" with `awaiting_query=true`.
8. **Player resolution** (`resolve_player_candidates`):
   - 0 candidates → "Не нашёл колонку …"
   - 1 candidate → continue to play.
   - 2+ candidates → disambiguation prompt with buttons +
     `pending_command` saved in `session_state`.
9. **Search + play** (`resolve_query` → `play_for_alice`).

## Parse pipeline (`parse_command`)

Steps applied in order to `request.command`:

1. **Punctuation normalisation** — strip `! ? . , ; : « » " „ "` and
   collapse whitespace. Apostrophes and hyphens inside words are kept
   (`rock'n'roll`, `rock-n-roll`).
2. **Defensive `Алиса,` prefix strip** — Yandex usually does this on
   its side, but we drop a leading vocative if present.
3. **Trailing player-hint extraction** — regex `\s+на\s+(?P<hint>.+?)\s*$`
   pulls the suffix introduced by the Russian preposition `на`. The
   hint can be multi-word (e.g. `на кухонной колонке`).
4. **Verb strip** — leading imperative / infinitive verb of the
   "play / find / open / show" family is removed (matches end-of-string
   too, so a lone verb is fully stripped):
   - `включи` / `включите` / `включай` / `включайте` / `включить`
   - `поставь` / `поставьте` / `поставить`
   - `запусти` / `запустите` / `запустить`
   - `сыграй` / `сыграйте` / `сыграть`
   - `играй` / `играйте`
   - `послушай` / `послушайте` / `послушать`
   - `найди` / `найдите` / `найти`
   - `открой` / `откройте` / `открыть`
   - `покажи` / `покажите` / `показать`

5. **Kind classification** — the remaining text is matched against
   ordered prefix patterns. First match wins:

   | Marker prefix              | `kind`     | `radio_mode` | Notes                                     |
   |----------------------------|------------|--------------|-------------------------------------------|
   | `мою/свою/нашу волну`      | `my_wave`  | `True`       | yandex_music rotor `user:onyourwave`      |
   | `моё/мое радио`            | `my_wave`  | `True`       | same                                      |
   | `плейлист X` / `подборку X`| `playlist` | `False`      |                                           |
   | `альбом X` / `пластинку X` | `album`    | `False`      |                                           |
   | `исполнителя/группу X`     | `artist`   | `True`       | starts artist radio                       |
   | `песню/трек/композицию X`  | `track`    | `False`      |                                           |
   | `радио X`                  | `genre`    | `True`       | yandex_music genre rotor (artist fallback)|
   | `жанр X`                   | `genre`    | `True`       | same                                      |
   | *(no marker)*              | `search`   | `True`       | catch-all; see *Search prioritisation*    |

## Control commands (`parse_control`)

Runs **before** the play parser. If matched, the handler dispatches to
the matching `mass.player_queues` / `mass.players` call and returns a
short confirmation. If no pattern matches, returns `None` and the
handler falls through to the play flow.

Supported phrases (case-insensitive; trailing `на <player>` accepted):

| Phrase | Action |
|--------|--------|
| `пауза` / `на паузу` / `поставь на паузу` / `останови музыку` | `pause` |
| `продолжи` / `продолжить` / `включи снова` / `возобнови` | `resume` |
| `стоп` / `останови` / `выключи` / `выключи музыку` | `stop` |
| `следующая` / `следующий трек` / `дальше` / `переключи` | `next` |
| `предыдущая` / `предыдущий трек` / `назад` / `вернись` | `previous` |
| `громче` / `сделай громче` / `прибавь` / `прибавь громкость` | `volume_up` |
| `тише` / `сделай тише` / `убавь` / `убавь громкость` | `volume_down` |
| `громкость 50` / `громкость на 30` / `сделай громкость 75` / `громкость на 30 процентов` | `volume_set` (clamped 0–100) |
| `приглуши` / `выключи звук` / `беззвучно` | `mute` |
| `включи звук` / `сделай звук` | `unmute` |
| `сколько колонок (ты)? (видишь\|знаешь)?` / `какие колонки (ты)? (видишь\|знаешь\|есть)?` / `какие у тебя колонки` / `перечисли колонки` / `список колонок` / `покажи колонки` / `назови колонки` | `list_players` (informational — replies with count + names) |
| `забудь колонку` / `сбрось колонку` / `забудь плеер` / `забудь выбор` / `сбрось выбор` / `выбери колонку заново` / `поменяй колонку` / `сменить колонку` | `forget_player` — clears the saved default-player so the next ambiguous command asks again (replies *"Хорошо, забыл колонку. В следующий раз спрошу."*) |
| `что (сейчас)? играет` / `что (мы)? слушаем` / `что за песня\|трек\|композиция` / `какой (сейчас)? трек\|играет` | `now_playing` — info — replies with `queue.current_item.name` (already pre-formatted as "Artist - Title" or stream title for radio) |
| `перемешай` / `включи перемешивание` / `случайный порядок` / `в случайном порядке` | `shuffle_on` |
| `выключи перемешивание` / `не перемешивай` / `по порядку` | `shuffle_off` |
| `повтор песни\|трек\|эту` / `повтори песню\|трек` | `repeat_one` |
| `повтор всё\|очередь\|плейлист` / `повторяй` / `включи повтор` | `repeat_all` |
| `выключи повтор` / `не повторяй` | `repeat_off` |
| `(перемотай\|промотай)? вперёд (на)? N (секунд\|минут)?` (digit + optional unit; minutes × 60) | `seek_forward(N seconds)` |
| `(перемотай\|промотай)? назад (на)? N (секунд\|минут)?` | `seek_back(N seconds)` |
| `(перемотай)? к началу` / `в начало` / `начни (трек)? заново` | `seek_start` (absolute seek to 0) |
| `(переведи\|перенеси) (музыку)? на <player>` / `продолжи (музыку)? в\|на <player>` | `transfer` — moves the queue from the saved default player (SOURCE) to the named target player. Replies *"Перевожу на <name>"* and updates `last_player_id` to the target. Replies *"Уже играет на <name>"* if target = current, *"Сначала включи музыку на колонке"* if no source is saved yet. |
| `добавь[те] / добавить <query>` (treats the rest as a normal play parser input — kind/marker/hint all still work) | **add-to-queue** — uses `play_media(option=QueueOption.ADD)` instead of REPLACE. Replies *"Добавил <query> в очередь на <player>"*. `radio_mode` is forced off (you don't add a station, you add a track). |

Note: bare `выключи` maps to `stop` (safer / reversible). Saying
"выключи колонку" to actually power-off the player is not yet
implemented (planned).

`на <player>` resolution iterates from the rightmost `на` boundary so
phrases that contain `на` inside the action keyword work too:
*"поставь на паузу на кухне"* → action=pause, hint=кухне (split at the
last `на`).

## Player resolution (`resolve_player_candidates` / `resolve_player`)

Filters all `mass.players.all_players()` to candidates that are
**available**, **enabled**, **not synced to a leader**, and (optionally)
inside the user's `Exposed Players` list. Then matches the hint:

1. **Both sides normalised** — lowercase, strip punctuation, strip a
   trailing Russian inflection suffix (longest first; suffix list:
   `-ого -ому -ыми -ая -ой -ом -ым -ы -е -у -а -и -й -ь -я`). So
   *"Кухня маленькая"* and *"на кухне маленькой"* both reduce to
   *"кухн маленьк"*.
2. **Tier order**: exact normalised match → starts-with → contains.
   Best non-empty tier is returned in full.
3. **Generic-word fallback** — if the hint contains a generic Russian
   stem for "speaker" / "player" (`колонк`, `плеер`, `проигрыватель`,
   `динамик`, `акустик`, `устройств`, etc.) and no specific name
   matched, fall through to:
   - the *default player* (last-used per state-tier priority);
   - the only exposed player when there's just one.
4. **No hint at all** — same fallback (default → single exposed),
   useful for follow-up commands in the same session.
5. **Multiple matches** — returned to the handler, which asks the user
   to pick (P0.3 disambiguation prompt with buttons).
6. **Otherwise** — empty list; handler responds *"Не нашёл колонку
   «<hint>». Скажи, например: на кухне."*

`resolve_player(...)` is a thin wrapper that returns the only
candidate iff exactly one matched, else `None` — used where ambiguity
isn't surfaced (e.g. control commands fall back to "не нашёл колонку"
in that case).

> Player names match against MA's `player.name`, *not* aliases set in
> the Yandex Smart Home app — Yandex does not forward those into the
> dialog skill payload. To use a custom voice name, rename the player
> in MA itself.

## Content resolution (`resolve_query`)

Dispatches by `parsed.kind`:

- `track` → `mass.music.search(media_types=[TRACK])` → first track
- `artist` → `mass.music.search(media_types=[ARTIST])` → first artist
- `album` → `mass.music.search(media_types=[ALBUM])` → first album
- `playlist` → `mass.music.search(media_types=[PLAYLIST])` → first playlist
- `my_wave` → yandex_music rotor `user:onyourwave`; first track URI
- `genre` → yandex_music genre rotor; falls back to artist search
- `search` → all four media types; **picker order:
  artists > albums > tracks > playlists**

### Stemmed-query retry (P0.7)

If the first search returns nothing **and** the original query
contains Cyrillic letters, the resolver retries once with the same
suffix-stripping the player resolver uses. Examples:

- `включи металлику` → first search for `металлику` empty → retry with
  `металлик` → matches `Металлика`.
- `включи песню утреннюю` → retry with `утренн` → matches an item.
- `включи Iron Maiden` (ASCII-only) → no retry; the original is fine.

### Search prioritisation rationale

For unqualified queries (`включи Iron Maiden`) users typically say a
band / artist name. Picking the artist first (with `radio_mode=True`)
matches that intent: MA starts an artist radio that keeps playing
related music. Playlists are de-prioritised — when the user wants a
playlist they say `плейлист <name>` explicitly.

If the user says a song name (`включи Yesterday`) the artists tier is
empty, so we fall through to `albums > tracks > playlists` — typically
landing on the track.

## Playback (`play_for_alice`)

After resolving:

1. If the player has a `power` feature and is currently `powered=False`,
   send `mass.players.cmd_power(player_id, True)`.
2. `mass.player_queues.play_media(queue_id=player_id, media=media,
   radio_mode=parsed.radio_mode)`. The call is fired via
   `self._mass.create_task(...)` so the webhook returns within
   Yandex's 4.5 s response budget; the actual stream start happens in
   the background.

## State persistence (Yandex `state` envelope)

The handler does **not** keep an in-process LRU. The "last player
used" default is round-tripped through Yandex's three state buckets:

| Bucket | Lifetime | Key we use |
|--------|----------|------------|
| `state.session` | one Alice conversation (~5 min idle, Yandex-side) | `last_player_id`, `pending_command`, `awaiting_query` |
| `state.application` | per device/app instance, persists across plugin reloads + MA restarts | `last_player_id` |
| `state.user` | per Yandex account, persists across devices (only set if `session.user.user_id` is present) | `preferred_player_id` |

When a command has no `на <player>` hint, the resolver picks the
default in this priority: `session > application > user`. After a
successful play or control action, all three are updated (where
applicable).

## Disambiguation flow (P0.3, voice-first since 1.8.2)

Most Yandex Stations are screenless. The disambiguation prompt is
therefore voice-first; buttons stay on the response for surfaces with a
screen but the user is expected to answer with their voice.

When `resolve_player_candidates` returns more than one match, the
handler:

1. Saves `{kind, query, radio_mode, candidate_ids}` into
   `session_state.pending_command`. `candidate_ids` is the ordered list
   of player IDs we offered (capped at 5 — Yandex `ItemsList` limit).
2. Returns `end_session=False` with prompt
   *"На какой колонке? Первая — A, вторая — B. Скажи название или номер."*
   plus one suggestion button per candidate (visible only on screen
   surfaces).
3. On the next turn, `_try_resume_pending` tries three resolution
   strategies in order:
   1. **Voice ordinal** — *"первая"* / *"вторая"* / *"номер три"* / *"3"*
      (recognises feminine / masculine / neuter forms; cardinals;
      digits; `четвёртая`/`четвертая` spelling variants) → looks up
      `candidate_ids[index]` and resolves the player.
   2. **Button press** — `request.payload.player_id` validated against
      the currently exposed-player set (defence-in-depth against stale
      payloads).
   3. **Free-text** — utterance is parsed and resolved against a
      *narrowed* exposed set restricted to `candidate_ids`. This means
      a short distinguisher like *"большая"* picks the right player even
      when an unrelated *"Гостиная большая"* exists outside the
      disambiguation set.
4. If the follow-up itself is still ambiguous, the handler re-asks once
   more with the new (narrower) candidate set.

## Slot elicitation (P0.4)

Triggered when `parse_command` returns `kind=search` with empty query
*and* no player hint (user said only the bare verb, e.g. *"Включи."*).

Response: *"Что включить? Можно сказать имя артиста, песни или
плейлиста."* with `session_state.awaiting_query=true`.

On the next turn, if `awaiting_query=true` is set and the new
utterance doesn't itself start with a play verb, the handler
synthesises `включи <utterance>` and re-enters the parse pipeline. So
the next-turn user can say either a bare query (*"Metallica"*), a
qualified one (*"песню Yesterday"*), or a complete sentence (*"включи
альбом Black Album"*) — all are handled.

## Examples

| Voice command                                  | `kind`     | `query`           | `radio_mode` | `player_hint`     |
|------------------------------------------------|------------|-------------------|--------------|-------------------|
| `включи Metallica`                             | `search`   | `metallica`       | `True`       | (none)            |
| `включи Metallica на кухне`                    | `search`   | `metallica`       | `True`       | `кухне`           |
| `включить Iron Maiden на проигрывателе`        | `search`   | `iron maiden`     | `True`       | `проигрывателе`   |
| `включи песню Yesterday`                       | `track`    | `yesterday`       | `False`      | (none)            |
| `включи альбом Black Album на спальне`         | `album`    | `black album`     | `False`      | `спальне`         |
| `включи группу Beatles`                        | `artist`   | `beatles`         | `True`       | (none)            |
| `включи плейлист утренний джаз`                | `playlist` | `утренний джаз`   | `False`      | (none)            |
| `включи мою волну`                             | `my_wave`  | (empty)           | `True`       | (none)            |
| `включи жанр джаз на кухне`                    | `genre`    | `джаз`            | `True`       | `кухне`           |
| `сыграй Metallica на колонке`                  | `search`   | `metallica`       | `True`       | `колонке`         |
| `послушать рок`                                | `search`   | `рок`             | `True`       | (none)            |
| `найди группу Beatles`                         | `artist`   | `beatles`         | `True`       | (none)            |
| `открой плейлист утренний джаз`                | `playlist` | `утренний джаз`   | `False`      | (none)            |
| `покажи альбом Black Album`                    | `album`    | `black album`     | `False`      | (none)            |

Control commands have their own dispatch (no `kind`/`query` —
direct mapping table above).

## Debug

Enable DEBUG for the two dialog loggers to see the full pipeline:

- `music_assistant.providers.yandex_smarthome.dialogs` — handler-side
  events: one summary line per incoming webhook (`Webhook recv: cmd=…
  req_type=… is_new=… pending=… awaiting=… default_player=…
  session_id=…`), then one line per branch decision (awaiting-query
  synthesis, pending-command resume or fall-through, slot-elicit prompt,
  play-branch resolution outcome, control-branch outcome incl.
  `list_players` count).
- `music_assistant.providers.yandex_smarthome.dialogs_nlu` —
  resolver-side events: one summary line per `resolve_player_candidates`
  call (`resolve_player: hint=… default=… exposed=N -> M candidate(s) […]
  [reason]`) where `reason` is `exact` / `startswith` / `contains` /
  `generic word, …` / `no exposed players` / `no hint, ambiguous` /
  `no tier matched`. So a "Не нашёл колонку «<hint>»" reply has a paired
  DEBUG line above it explaining *why* it didn't match.

INFO-level events surface only the rarer "no player resolved" failures
so users get a signal without needing DEBUG. WARN/ERROR are kept for
real misconfiguration (e.g. a generic player word matching no specific
player when there are multiple candidates).

To list the exposed speakers without inspecting logs, just ask Alice
*"Алиса, попроси \<skill\> сколько колонок видишь"* — that's the
`list_players` action documented in the control table above.
