"""Runtime settings (environment / .env) and company configuration (firma.toml)."""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import tomli_w

from app.storage.atomic import atomic_write_text

INVOICE_NUMBER_FORMATS = ("RRRRNNNN", "RRRRNNN")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "ano", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    config_dir: Path
    secret_key: str
    cookie_secure: bool = False
    session_max_age: int = 12 * 3600
    setup_token: str | None = None
    log_level: str = "INFO"
    max_upload_bytes: int = 20 * 1024 * 1024
    # Non-secret mail settings, shown in the setup wizard. Passwords stay in env only.
    imap_host: str = ""
    imap_user: str = ""
    smtp_host: str = ""
    smtp_user: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"  # ssl | starttls | none (none only for local test servers)
    smtp_from: str = ""
    # Never printed: excluded from repr so it cannot end up in a log line.
    smtp_password: str = field(default="", repr=False)

    @property
    def branding_dir(self) -> Path:
        return self.config_dir / "branding"

    @property
    def firma_path(self) -> Path:
        return self.config_dir / "firma.toml"

    @property
    def auth_path(self) -> Path:
        return self.config_dir / "auth.json"

    @classmethod
    def from_env(cls) -> Settings:
        config_dir = Path(os.environ.get("CONFIG_DIR", "/config"))
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            config_dir=config_dir,
            secret_key=os.environ.get("SECRET_KEY") or _persisted_secret(config_dir),
            cookie_secure=_env_bool("COOKIE_SECURE", False),
            session_max_age=int(os.environ.get("SESSION_MAX_AGE", 12 * 3600)),
            setup_token=os.environ.get("SETUP_TOKEN") or None,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            imap_host=os.environ.get("IMAP_HOST", ""),
            imap_user=os.environ.get("IMAP_USER", ""),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_port=int(os.environ.get("SMTP_PORT") or 465),
            smtp_security=_smtp_security(),
            smtp_from=os.environ.get("SMTP_FROM", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        )


def _smtp_security() -> str:
    value = os.environ.get("SMTP_SECURITY", "").strip().lower()
    if value in ("ssl", "starttls", "none"):
        return value
    # Default by port: 465 is implicit TLS, anything else upgrades with STARTTLS.
    return "ssl" if (os.environ.get("SMTP_PORT") or "465") == "465" else "starttls"


def _persisted_secret(config_dir: Path) -> str:
    """Fallback when SECRET_KEY is not set: generate once and keep it in /config."""
    path = config_dir / ".secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    atomic_write_text(path, key)
    path.chmod(0o600)
    return key


@dataclass
class Firma:
    nazev: str = ""
    ico: str = ""
    dic: str = ""
    ulice: str = ""
    mesto: str = ""
    psc: str = ""
    email: str = ""
    telefon: str = ""
    web: str = ""
    zapis_rejstrik: str = ""


@dataclass
class Banka:
    ucet: str = ""
    iban: str = ""


@dataclass
class Fakturace:
    format_cisla: str = "RRRRNNNN"
    pocatecni_cislo: int = 1
    splatnost_dni: int = 14
    text_dph: str = "Nejsem plátce DPH."


@dataclass
class Aplikace:
    pruvodce_dokoncen: bool = False


@dataclass
class FirmaConfig:
    firma: Firma = field(default_factory=Firma)
    banka: Banka = field(default_factory=Banka)
    fakturace: Fakturace = field(default_factory=Fakturace)
    aplikace: Aplikace = field(default_factory=Aplikace)

    @classmethod
    def load(cls, path: Path) -> FirmaConfig:
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(
            firma=_section(Firma, data.get("firma")),
            banka=_section(Banka, data.get("banka")),
            fakturace=_section(Fakturace, data.get("fakturace")),
            aplikace=_section(Aplikace, data.get("aplikace")),
        )

    def save(self, path: Path) -> None:
        header = "# Konfigurace firmy pro Daňovou evidenci. Popis v docs/konfigurace.md.\n\n"
        atomic_write_text(path, header + tomli_w.dumps(asdict(self)))


def _section[T](cls: type[T], data: Any) -> T:
    if not isinstance(data, dict):
        return cls()
    known = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    values = {}
    for key, value in data.items():
        if key in known:
            values[key] = value
    return cls(**values)
