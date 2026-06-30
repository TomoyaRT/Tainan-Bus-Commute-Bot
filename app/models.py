from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

VALID_INTERVALS = (5, 10, 15, 20)
DEFAULT_ENABLED_DAYS = [2, 3, 4, 5, 6]


@dataclass
class SlotConfig:
    bus: str
    stop_name: str
    window_start: str
    window_end: str
    default_interval: int

    def to_dict(self) -> dict:
        return {
            "bus": self.bus,
            "stop_name": self.stop_name,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "default_interval": self.default_interval,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SlotConfig":
        return cls(
            bus=d["bus"],
            stop_name=d["stop_name"],
            window_start=d["window_start"],
            window_end=d["window_end"],
            default_interval=d["default_interval"],
        )


SLOT_DEFAULTS = {
    "morning": SlotConfig("70左", "台南高工", "08:00", "09:30", 10),
    "evening": SlotConfig("70右", "中華西路二段", "18:30", "21:00", 5),
}


@dataclass
class UserSettings:
    chat_id: int
    enabled_days: list[int]
    slots: dict[str, SlotConfig]

    @classmethod
    def default(cls, chat_id: int) -> "UserSettings":
        return cls(
            chat_id=chat_id,
            enabled_days=list(DEFAULT_ENABLED_DAYS),
            slots={name: SlotConfig.from_dict(cfg.to_dict()) for name, cfg in SLOT_DEFAULTS.items()},
        )

    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "enabled_days": list(self.enabled_days),
            "slots": {name: cfg.to_dict() for name, cfg in self.slots.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserSettings":
        return cls(
            chat_id=d["chat_id"],
            enabled_days=list(d["enabled_days"]),
            slots={name: SlotConfig.from_dict(cfg) for name, cfg in d["slots"].items()},
        )


@dataclass
class SlotRuntime:
    stopped: bool = False
    interval_override: int | None = None
    last_push_at: datetime | None = None
    fail_count: int = 0

    def to_dict(self) -> dict:
        return {
            "stopped": self.stopped,
            "interval_override": self.interval_override,
            "last_push_at": self.last_push_at.isoformat() if self.last_push_at else None,
            "fail_count": self.fail_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SlotRuntime":
        raw = d.get("last_push_at")
        return cls(
            stopped=d.get("stopped", False),
            interval_override=d.get("interval_override"),
            last_push_at=datetime.fromisoformat(raw) if raw else None,
            fail_count=d.get("fail_count", 0),
        )


@dataclass
class DayRuntime:
    morning: SlotRuntime = field(default_factory=SlotRuntime)
    evening: SlotRuntime = field(default_factory=SlotRuntime)

    def slot(self, name: str) -> SlotRuntime:
        return getattr(self, name)

    def to_dict(self) -> dict:
        return {"morning": self.morning.to_dict(), "evening": self.evening.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "DayRuntime":
        return cls(
            morning=SlotRuntime.from_dict(d.get("morning", {})),
            evening=SlotRuntime.from_dict(d.get("evening", {})),
        )
