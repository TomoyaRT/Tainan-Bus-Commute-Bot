from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.models import UserSettings, DayRuntime


class Store(Protocol):
    async def get_user(self, chat_id: int) -> UserSettings | None: ...
    async def save_user(self, settings: UserSettings) -> None: ...
    async def list_users(self) -> list[UserSettings]: ...
    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime: ...
    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None: ...
    async def get_tdx_token(self) -> tuple[str, datetime] | None: ...
    async def save_tdx_token(self, token: str, expires_at: datetime) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._users: dict[int, dict] = {}
        self._runtime: dict[tuple[int, str], dict] = {}
        self._token: tuple[str, datetime] | None = None

    async def get_user(self, chat_id: int) -> UserSettings | None:
        raw = self._users.get(chat_id)
        return UserSettings.from_dict(raw) if raw else None

    async def save_user(self, settings: UserSettings) -> None:
        self._users[settings.chat_id] = settings.to_dict()

    async def list_users(self) -> list[UserSettings]:
        return [UserSettings.from_dict(raw) for raw in self._users.values()]

    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime:
        raw = self._runtime.get((chat_id, date_str))
        return DayRuntime.from_dict(raw) if raw else DayRuntime()

    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None:
        self._runtime[(chat_id, date_str)] = runtime.to_dict()

    async def get_tdx_token(self) -> tuple[str, datetime] | None:
        return self._token

    async def save_tdx_token(self, token: str, expires_at: datetime) -> None:
        self._token = (token, expires_at)


class FirestoreStore:
    """正式環境用，注入 google.cloud.firestore.AsyncClient。"""

    def __init__(self, db) -> None:
        self.db = db

    async def get_user(self, chat_id: int) -> UserSettings | None:
        snap = await self.db.collection("users").document(str(chat_id)).get()
        return UserSettings.from_dict(snap.to_dict()) if snap.exists else None

    async def save_user(self, settings: UserSettings) -> None:
        await self.db.collection("users").document(str(settings.chat_id)).set(settings.to_dict())

    async def list_users(self) -> list[UserSettings]:
        users = []
        async for snap in self.db.collection("users").stream():
            users.append(UserSettings.from_dict(snap.to_dict()))
        return users

    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime:
        snap = await (
            self.db.collection("users").document(str(chat_id))
            .collection("runtime").document(date_str).get()
        )
        return DayRuntime.from_dict(snap.to_dict()) if snap.exists else DayRuntime()

    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None:
        await (
            self.db.collection("users").document(str(chat_id))
            .collection("runtime").document(date_str).set(runtime.to_dict())
        )

    async def get_tdx_token(self) -> tuple[str, datetime] | None:
        snap = await self.db.collection("system").document("tdxToken").get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return data["access_token"], datetime.fromisoformat(data["expires_at"])

    async def save_tdx_token(self, token: str, expires_at: datetime) -> None:
        await self.db.collection("system").document("tdxToken").set(
            {"access_token": token, "expires_at": expires_at.isoformat()}
        )
