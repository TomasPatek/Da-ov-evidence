"""SMTP sender: connection modes, login, error mapping, no secrets in logs."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from app.config import Settings
from app.mail import smtp as smtp_mod
from app.mail.smtp import Attachment, MailError, SmtpSender, build_message

SECRET = "tajne-heslo-123"


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "data_dir": Path("/tmp/x"),
        "config_dir": Path("/tmp/y"),
        "secret_key": "k",
        "smtp_host": "smtp.example.cz",
        "smtp_user": "fakturace@example.cz",
        "smtp_password": SECRET,
    }
    return Settings(**{**base, **kw})


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []
    fail_with: ClassVar[BaseException | None] = None

    def __init__(self, host: str, port: int, timeout: float = 0, context: Any = None) -> None:
        self.host, self.port, self.calls = host, port, []  # type: ignore[var-annotated]
        self.ssl = context is not None
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *a: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        self.calls.append(("login", user))

    def send_message(self, msg: EmailMessage) -> None:
        self.calls.append(("send", msg["To"]))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances, FakeSMTP.fail_with = [], None
    monkeypatch.setattr(smtp_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtp_mod.smtplib, "SMTP_SSL", FakeSMTP)


def message() -> EmailMessage:
    return build_message(
        "Jana Vzorová",
        "fakturace@example.cz",
        "petr@example.cz",
        "Faktura 20260001",
        "Text",
        [Attachment("faktura-20260001.pdf", b"%PDF-1.7", "application", "pdf")],
    )


def test_message_structure() -> None:
    msg = message()
    assert msg["From"] == "Jana Vzorová <fakturace@example.cz>"
    assert msg["Message-ID"].endswith("@example.cz>")
    (att,) = msg.iter_attachments()
    assert att.get_content_type() == "application/pdf"


def test_ssl_mode_logs_in_and_sends() -> None:
    SmtpSender(settings(smtp_port=465, smtp_security="ssl")).send(message())
    (conn,) = FakeSMTP.instances
    assert conn.ssl
    assert conn.calls == [("login", "fakturace@example.cz"), ("send", "petr@example.cz"), "quit"]


def test_starttls_mode() -> None:
    SmtpSender(settings(smtp_port=587, smtp_security="starttls")).send(message())
    assert FakeSMTP.instances[0].calls[0] == "starttls"


def test_not_configured() -> None:
    sender = SmtpSender(settings(smtp_host=""))
    assert not sender.configured
    with pytest.raises(MailError, match="není nastavené"):
        sender.send(message())


def test_from_address_can_differ_from_login() -> None:
    assert (
        SmtpSender(settings(smtp_from="faktury@example.cz")).sender_address == "faktury@example.cz"
    )


def test_auth_error_is_explained() -> None:
    FakeSMTP.fail_with = smtplib.SMTPAuthenticationError(535, b"bad")
    with pytest.raises(MailError, match="SMTP_PASSWORD"):
        SmtpSender(settings()).send(message())


def test_network_error_does_not_leak_secrets(caplog: pytest.LogCaptureFixture) -> None:
    FakeSMTP.fail_with = OSError(f"connection refused for {SECRET} petr@example.cz")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(MailError) as exc:
        SmtpSender(settings()).send(message())
    assert SECRET not in str(exc.value)
    assert SECRET not in caplog.text
    assert "petr@example.cz" not in caplog.text


def test_password_not_in_settings_repr() -> None:
    assert SECRET not in repr(settings())


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"SMTP_PORT": "465"}, "ssl"),
        ({"SMTP_PORT": "587"}, "starttls"),
        ({"SMTP_PORT": "1025", "SMTP_SECURITY": "none"}, "none"),
        ({}, "ssl"),
    ],
)
def test_security_from_env(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for key in ("SMTP_PORT", "SMTP_SECURITY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SECRET_KEY", "k")
    assert Settings.from_env().smtp_security == expected
