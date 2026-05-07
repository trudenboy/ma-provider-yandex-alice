# CLAUDE.md

Yandex Alice voice-skill provider for Music Assistant. Source repo for the
`yandex_alice` plugin provider that lives at
`music_assistant/providers/yandex_alice/` upstream — code is authored here
and synced to `music-assistant/server` via `ma-provider-tools`.

This file aligns with the upstream Music Assistant `CLAUDE.md` so that
provider code authored locally is shaped exactly like provider code in
the upstream tree (Sphinx docstrings, Behaviour rules, branching).

## Behaviour

- NEVER automatically reply on GitHub (PRs, issues, discussions) without
  explicit consent from the developer.

## Layout

- `provider/` — plugin source (mirrored to `music_assistant/providers/yandex_alice/` on sync)
- `tests/` — pytest suite (mirrored to `tests/providers/yandex_alice/`)
- `docs/` — research notes (`NLU_RESEARCH.md`, `VOICE_UX_RESEARCH.md`, `VOICE_COMMANDS.md`); not synced
- `provider/manifest.json` — provider metadata + runtime requirements
- `pyproject.toml` — dev-time deps + lint config; not synced

## Development Commands

- `.venv/bin/python -m pytest tests/` — run all tests
- `.venv/bin/python -m pytest tests/test_dialogs.py -k <pattern>` — single file / pattern
- `.venv/bin/python -m ruff check provider/ tests/` — lint
- `.venv/bin/python -m ruff format provider/ tests/` — auto-format
- `.venv/bin/python -m mypy provider/` — type check (strict mode)
- `pre-commit run --all-files` — full pre-commit gate

Always run lint + tests + mypy before committing. Pre-commit hooks
mirror these checks plus gitleaks. CI runs `ruff format --check`, so
pushing without `ruff format` is the most common red build.

## Code Style

### Comments

Only use comments to explain complex, multi-line blocks of code. Do not
comment obvious operations.

### Docstring Format

Use Sphinx-style docstrings with `:param:` / `:returns:` / `:raises:`
syntax. For simple functions, a single-line docstring is fine.

Don't explain inner workings of the code in the docstrings (use inline
comments for that if/when needed). The docstring should provide clarity
to the **caller** of the function/method, not explain how it works
technically/internally.

```python
def my_function(param1: str, param2: int, param3: bool = False) -> str:
    """
    Brief one-line description of the function.

    :param param1: Description of what param1 is used for.
    :param param2: Description of what param2 is used for.
    :param param3: Description of what param3 is used for.
    """
```

Do **not** use Google-style (`Args:`) or bullet-style (`- param:`)
docstrings. AI assistants tend to generate Google-style by default —
explicitly steer them to Sphinx, and rewrite anything that slips
through.

### Provider style

- Match the layering of `provider/dialogs*.py`: webhook handler →
  parsers (`dialogs_nlu.py`, `dialogs_control.py`, `dialogs_grammar.py`)
  → resolvers (`dialogs_player.py`). Keep network I/O in the handler;
  parsers and resolvers are pure or take `mass: MusicAssistant` as a
  dependency.
- Public-network inputs (URLs, hostnames, host headers) MUST go through
  `is_public_https_url` from `provider/url_helpers.py` — both
  `build_backend_uri` and the webhook probe rejected this in code
  review (PR #3843, v1.2.2 fix). Never gate on scheme alone.
- `from __future__ import annotations` at the top of every Python file.

## Branching and PRs

- Default branch: `dev`. All work-in-progress PRs target `dev`.
- Long-lived feature branches: `feat/<topic>` (e.g. `feat/platform-integration`).
  Merge to `dev` once the feature lands.
- Versioned bugfixes go through `dev` too; tags / releases happen on
  `dev` after sync to upstream completes.

## Sync to upstream

`ma-provider-tools` runs the sync workflow that propagates `provider/`
and `tests/` from this repo into `music-assistant/server` under their
canonical paths. Do not edit files inside `music-assistant/server/`
directly — changes there are overwritten on the next sync.

CI in upstream `music-assistant/server` is the moderation gate; review
threads (e.g. PR #3843) drive bug fixes here, then a re-sync clears
them upstream. The CHANGELOG entries in this repo are the source of
truth for what landed.

## Debugging

- Music Assistant data: `$HOME/.musicassistant/`
- MA logs: `$HOME/.musicassistant/musicassistant.log` (current),
  `musicassistant.log.1` etc. for older rotated logs
- MA database: `$HOME/.musicassistant/library.db` — query via `sqlite3`.
  **Only execute SELECT queries** — never write to a live database.
- Webhook traffic during local testing: tail the MA log filtered by
  `Webhook recv:` (the structured DEBUG line emitted on every Yandex
  request). Bumping the dialog logger to DEBUG via
  `python -m music_assistant --log-level debug` is enough.

## Other notes

- The plugin reuses Yandex Passport cookies via `ya-passport-auth` and
  the `app-store-api` REST surface via `ya-dialogs-api`. Both packages
  are owned by this same author; bump versions in `pyproject.toml` +
  `provider/manifest.json` together.
- Tests never make live Yandex calls. Mock `aiohttp.ClientSession` per
  the pattern in `tests/test_auto_create.py` if a new test needs HTTP.
- Webhook handler error handling (PR #3843 review thread): the
  post-auth dispatch is wrapped in `try / except` (`_handle_webhook` →
  `_handle_authenticated_request`) so a parse / dispatch error surfaces
  as a Russian "что-то пошло не так" reply instead of HTTP 500 → Alice
  silence. Keep this guarantee intact when modifying the handler — any
  new branch should also satisfy the
  `test_unexpected_inner_exception_returns_graceful_fallback` test.
