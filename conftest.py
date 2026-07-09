"""Root conftest: ensure provider/ is importable and mock MA dependencies for tests."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from enum import Enum
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Mock music_assistant_models so provider imports don't fail
# ---------------------------------------------------------------------------

# StrEnum shim for Python < 3.11
try:
    from enum import StrEnum as _StrEnum
except ImportError:

    class _StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of StrEnum for Python < 3.11."""


def _ensure_module(name: str, attrs: dict | None = None) -> types.ModuleType:
    """Create and register a stub module if not already present."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__package__ = name
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    # Set __path__ for packages (allows sub-imports)
    mod.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


# Create music_assistant_models namespace
_ensure_module("music_assistant_models")


# music_assistant_models.enums
class _PlaybackState(_StrEnum):
    IDLE = "idle"
    PAUSED = "paused"
    PLAYING = "playing"
    UNKNOWN = "unknown"


class _EventType(_StrEnum):
    PLAYER_ADDED = "player_added"
    PLAYER_UPDATED = "player_updated"
    PLAYER_REMOVED = "player_removed"
    AUTH_SESSION = "auth_session"


class _ConfigEntryType(_StrEnum):
    STRING = "string"
    SECURE_STRING = "secure_string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    LABEL = "label"
    ALERT = "alert"
    ACTION = "action"


class _ProviderFeature(_StrEnum):
    pass


class _MediaType(_StrEnum):
    ARTIST = "artist"
    ALBUM = "album"
    TRACK = "track"
    PLAYLIST = "playlist"
    RADIO = "radio"
    UNKNOWN = "unknown"


class _RepeatMode(_StrEnum):
    OFF = "off"
    ONE = "one"
    ALL = "all"
    UNKNOWN = "unknown"


class _QueueOption(_StrEnum):
    PLAY = "play"
    REPLACE = "replace"
    NEXT = "next"
    REPLACE_NEXT = "replace_next"
    ADD = "add"
    UNKNOWN = "unknown"


class _ProviderType(_StrEnum):
    MUSIC = "music"
    PLAYER = "player"
    METADATA = "metadata"
    PLUGIN = "plugin"


_ensure_module(
    "music_assistant_models.enums",
    {
        "PlaybackState": _PlaybackState,
        "EventType": _EventType,
        "ConfigEntryType": _ConfigEntryType,
        "ProviderFeature": _ProviderFeature,
        "MediaType": _MediaType,
        "RepeatMode": _RepeatMode,
        "QueueOption": _QueueOption,
        "ProviderType": _ProviderType,
    },
)


# music_assistant_models.config_entries
class _ConfigEntry:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _ConfigValueOption:
    # Mirrors music_assistant_models.config_entries.ConfigValueOption:
    # ``value`` first, optional ``title``.
    def __init__(self, value=None, title=None):
        self.value = value
        self.title = title


_ensure_module(
    "music_assistant_models.config_entries",
    {"ConfigEntry": _ConfigEntry, "ConfigValueOption": _ConfigValueOption, "ConfigValueType": str},
)

# music_assistant_models.provider
_ensure_module(
    "music_assistant_models.provider",
    {"ProviderManifest": MagicMock},
)

# music_assistant_models.player
_ensure_module("music_assistant_models.player", {"Player": MagicMock})


# music_assistant_models.event
class _MassEvent:
    def __init__(self, event=None, data=None):
        self.event = event
        self.data = data


_ensure_module("music_assistant_models.event", {"MassEvent": _MassEvent})


# music_assistant_models.constants
_ensure_module(
    "music_assistant_models.constants",
    {"SECURE_STRING_SUBSTITUTE": "this_value_is_encrypted"},
)


# music_assistant_models.errors
class _LoginFailed(Exception):
    """Stub of music_assistant_models.errors.LoginFailed."""


class _ResourceTemporarilyUnavailable(Exception):
    """Stub of music_assistant_models.errors.ResourceTemporarilyUnavailable."""


class _InvalidDataError(Exception):
    """Stub of music_assistant_models.errors.InvalidDataError."""


_ensure_module(
    "music_assistant_models.errors",
    {
        "LoginFailed": _LoginFailed,
        "ResourceTemporarilyUnavailable": _ResourceTemporarilyUnavailable,
        "InvalidDataError": _InvalidDataError,
    },
)

# ---------------------------------------------------------------------------
# 2. Mock music_assistant server modules
# ---------------------------------------------------------------------------

_ensure_module("music_assistant")
_ensure_module("music_assistant.models")
_ensure_module("music_assistant.mass", {"MusicAssistant": MagicMock})


class _PluginProvider:
    """Minimal stub of music_assistant.models.plugin.PluginProvider."""

    def __init__(self, mass=None, manifest=None, config=None, supported_features=None):
        self.mass = mass
        self.manifest = manifest
        self.config = config or MagicMock()
        self.supported_features = supported_features or set()
        self.logger = MagicMock()

    async def handle_async_init(self):
        pass

    async def loaded_in_mass(self):
        pass

    async def unload(self, is_removed=False):
        pass


_ensure_module("music_assistant.models.plugin", {"PluginProvider": _PluginProvider})
_ensure_module("music_assistant.models", {"ProviderInstanceType": MagicMock})

# ---------------------------------------------------------------------------
# 3. Make provider/ importable as both 'provider' and
#    'music_assistant.providers.yandex_alice'
# ---------------------------------------------------------------------------

_provider_path = Path(__file__).parent / "provider"

# Ensure parent namespace packages exist
for _pkg in ("music_assistant.providers",):
    if _pkg not in sys.modules:
        _mod = types.ModuleType(_pkg)
        _mod.__path__ = []  # type: ignore[attr-defined]
        _mod.__package__ = _pkg
        sys.modules[_pkg] = _mod

# Insert provider/ into sys.path so its modules are importable
if str(_provider_path) not in sys.path:
    sys.path.insert(0, str(_provider_path))

# Register a package alias so `from music_assistant.providers.yandex_alice.X import Y` works
_spec = importlib.util.spec_from_file_location(
    "music_assistant.providers.yandex_alice",
    _provider_path / "__init__.py",
    submodule_search_locations=[str(_provider_path)],
)
if _spec and "music_assistant.providers.yandex_alice" not in sys.modules:
    _pkg_mod = importlib.util.module_from_spec(_spec)
    _pkg_mod.__path__ = [str(_provider_path)]  # type: ignore[attr-defined]
    _pkg_mod.__package__ = "music_assistant.providers.yandex_alice"
    sys.modules["music_assistant.providers.yandex_alice"] = _pkg_mod
    with contextlib.suppress(
        Exception
    ):  # provider __init__ may have MA-specific imports; best-effort
        _spec.loader.exec_module(_pkg_mod)  # type: ignore[union-attr]
