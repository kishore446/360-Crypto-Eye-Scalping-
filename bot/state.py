"""Thread-safe singleton for bot-wide mutable state."""
from __future__ import annotations
import threading

try:
    from config import AUTO_SCAN_ENABLED_ON_BOOT as _AUTO_SCAN_ENABLED_ON_BOOT
except Exception:  # pragma: no cover
    _AUTO_SCAN_ENABLED_ON_BOOT = True


class BotState:
    """All mutable bot-level state guarded by a lock."""
    _instance: "BotState | None" = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "BotState":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._state_lock = threading.Lock()
                    inst._news_freeze = False
                    inst._trail_active = False
                    inst._auto_scan_active = bool(_AUTO_SCAN_ENABLED_ON_BOOT)
                    inst._market_regime = "UNKNOWN"
                    cls._instance = inst
        return cls._instance

    @property
    def news_freeze(self) -> bool:
        with self._state_lock:
            return self._news_freeze

    @news_freeze.setter
    def news_freeze(self, value: bool) -> None:
        with self._state_lock:
            self._news_freeze = value

    @property
    def trail_active(self) -> bool:
        with self._state_lock:
            return self._trail_active

    @trail_active.setter
    def trail_active(self, value: bool) -> None:
        with self._state_lock:
            self._trail_active = value

    @property
    def auto_scan_active(self) -> bool:
        with self._state_lock:
            return self._auto_scan_active

    @auto_scan_active.setter
    def auto_scan_active(self, value: bool) -> None:
        with self._state_lock:
            self._auto_scan_active = value

    @property
    def market_regime(self) -> str:
        """Current market regime: 'BULL', 'BEAR', 'SIDEWAYS', or 'UNKNOWN'."""
        with self._state_lock:
            return self._market_regime

    @market_regime.setter
    def market_regime(self, value: str) -> None:
        valid = ("BULL", "BEAR", "SIDEWAYS", "UNKNOWN")
        if value not in valid:
            raise ValueError(f"market_regime must be one of {valid}, got {value!r}")
        with self._state_lock:
            self._market_regime = value
