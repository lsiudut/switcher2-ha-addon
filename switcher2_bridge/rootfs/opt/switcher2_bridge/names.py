"""Persistent store for user-assigned channel and input display names.

Names are saved as JSON next to the bridge config (or wherever configured).
All methods are thread-safe — safe to call from Flask threads and the asyncio
executor simultaneously.
"""
import json
import logging
import threading
from pathlib import Path

import sw2lib

log = logging.getLogger(__name__)


class NamesStore:
    """Loads/saves channel and input names from a JSON file."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._channels: list[str] = [''] * sw2lib.CHANNEL_MAX
        self._inputs:   list[str] = [''] * sw2lib.INPUT_MAX
        self._load()

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def channel_name(self, i: int) -> str:
        """Return the user-assigned name for channel i, or 'Light <n>' fallback."""
        with self._lock:
            n = self._channels[i] if 0 <= i < len(self._channels) else ''
        return n or f'Light {i + 1}'

    def input_name(self, i: int) -> str:
        """Return the user-assigned name for input i, or 'Input <n>' fallback."""
        with self._lock:
            n = self._inputs[i] if 0 <= i < len(self._inputs) else ''
        return n or f'Input {i + 1}'

    def all_channel_names(self) -> list[str]:
        with self._lock:
            return [self._channels[i] or f'Light {i + 1}' for i in range(sw2lib.CHANNEL_MAX)]

    def all_input_names(self) -> list[str]:
        with self._lock:
            return [self._inputs[i] or f'Input {i + 1}' for i in range(sw2lib.INPUT_MAX)]

    # ------------------------------------------------------------------
    # Public write API (save immediately)
    # ------------------------------------------------------------------

    def set_channel(self, i: int, name: str) -> None:
        with self._lock:
            if 0 <= i < sw2lib.CHANNEL_MAX:
                self._channels[i] = name.strip()
                self._save()

    def set_input(self, i: int, name: str) -> None:
        with self._lock:
            if 0 <= i < sw2lib.INPUT_MAX:
                self._inputs[i] = name.strip()
                self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self._path) as f:
                data = json.load(f)
            ch  = list(data.get('channels', []))
            inp = list(data.get('inputs',   []))
            self._channels = (ch  + [''] * sw2lib.CHANNEL_MAX)[:sw2lib.CHANNEL_MAX]
            self._inputs   = (inp + [''] * sw2lib.INPUT_MAX)  [:sw2lib.INPUT_MAX]
            log.info(f"Names loaded from {self._path}")
        except FileNotFoundError:
            log.info(f"Names file not found ({self._path}), using defaults")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load names from {self._path}: {e}")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, 'w') as f:
                json.dump({'channels': self._channels, 'inputs': self._inputs},
                          f, indent=2, ensure_ascii=False)
        except OSError as e:
            log.warning(f"Failed to save names to {self._path}: {e}")
