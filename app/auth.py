"""Single-user authentication: Argon2 password, login throttling, CSRF tokens."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.storage.atomic import atomic_write_text

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()


class PasswordStore:
    """Argon2 hash of the single user's password, kept in /config/auth.json."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_set(self) -> bool:
        return self._read_hash() is not None

    def _read_hash(self) -> str | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        value = data.get("password_hash")
        return value if isinstance(value, str) and value else None

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Heslo musí mít alespoň {MIN_PASSWORD_LENGTH} znaků.")
        atomic_write_text(self.path, json.dumps({"password_hash": _hasher.hash(password)}))
        self.path.chmod(0o600)

    def verify(self, password: str) -> bool:
        stored = self._read_hash()
        if stored is None:
            return False
        try:
            _hasher.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        if _hasher.check_needs_rehash(stored):
            self.set_password(password)
        return True


class LoginThrottle:
    """Limits failed logins per client and globally within a sliding window.

    The global limit caps guessing even if an attacker rotates client addresses.
    """

    def __init__(
        self,
        per_client: int = 5,
        global_limit: int = 20,
        window_seconds: float = 15 * 60,
        clock: object = time.monotonic,
    ) -> None:
        self.per_client = per_client
        self.global_limit = global_limit
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def _prune(self, q: deque[float], now: float) -> None:
        while q and q[0] <= now - self.window:
            q.popleft()

    def is_blocked(self, client: str) -> bool:
        with self._lock:
            now = self._now()
            q = self._failures[client]
            self._prune(q, now)
            self._prune(self._global, now)
            return len(q) >= self.per_client or len(self._global) >= self.global_limit

    def record_failure(self, client: str) -> None:
        with self._lock:
            now = self._now()
            self._failures[client].append(now)
            self._global.append(now)

    def reset(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def tokens_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())
