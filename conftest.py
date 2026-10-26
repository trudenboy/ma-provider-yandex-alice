"""Root conftest: make provider/ importable as music_assistant.providers.yandex_alice."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Tests run against the real Music Assistant server and models packages (the
# ``test`` extra installs them), exactly like the inlined provider upstream.
import music_assistant.providers  # noqa: F401

_provider_path = Path(__file__).parent / "provider"
_PACKAGE = "music_assistant.providers.yandex_alice"

if _PACKAGE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _PACKAGE,
        _provider_path / "__init__.py",
        submodule_search_locations=[str(_provider_path)],
    )
    assert _spec is not None
    assert _spec.loader is not None
    _pkg_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_PACKAGE] = _pkg_mod
    _spec.loader.exec_module(_pkg_mod)
