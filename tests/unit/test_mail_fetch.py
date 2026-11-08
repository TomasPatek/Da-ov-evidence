"""Mailbox processing with an in-memory mailbox (no network)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from types import TracebackType

import pytest

from app.banks.book import BankBook
from app.config import FirmaConfig, Settings
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceService
from app.mail.fetch import MailProcessor
from app.mail.imap import MailError, RawMessage
from app.mail.scheduler import start_scheduler
from app.received import ReceivedDocs
from app.storage import Storage

AIRBANK = Path(__file__).parents[1] / "fixtures" / "airbank"
DOKLADY = Path(__file__).parents[1] / "fixtures" / "doklady"


class FakeMailbox:
    def __init__(self, messages: list[bytes], fail: bool = False) -> None:
        self.inbox = {str(i + 1): data for i, data in enumerate(messages)}
        self.moved: dict[str, list[str]] = {}
        self.fail = fail

    def __enter__(self) -> FakeMailbox:
        if self.fail:
            raise MailError("Připojení ke schránce selhalo (TimeoutError).")
        return self

    def __exit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        pass

    def messages(self) -> Iterator[RawMessage]:
        for uid, data in list(self.inbox.items()):
            yield RawMessage(uid, data)

    def move(self, uid: str, folder: str) -> None:
        self.moved.setdefault(folder, []).append(uid)
        del self.inbox[uid]


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.firma.ico = "99999994"
    cfg.banka.ucet = "1000000005/3030"
    cfg.evidence.zacatek = "2026-01-01"
    return cfg


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    s.table(KONTAKTY_SCHEMA).insert(
        {
            "id": "K0001",
            "typ": "odběratel",
            "ico": "",
            "dic": "",
            "nazev": "Petr Zákazník",
            "ulice": "",
            "mesto": "",
            "psc": "",
            "email": "",
            "telefon": "",
            "poznamka": "",
            "ares_aktualizovano": None,
        }
    )
    return s


@pytest.fixture
def processor(storage: Storage, firma: FirmaConfig, tmp_path: Path) -> MailProcessor:
    settings = Settings(data_dir=storage.data_dir, config_dir=tmp_path / "config", secret_key="k")
    return MailProcessor(storage, firma, settings)


def other_mail(subject: str = "Pozvánka na veletrh") -> bytes:
    msg = EmailMessage()
    msg["From"] = "obchod@example.cz"
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{abs(hash(subject))}@example.cz>"
    msg.set_content("Dobrý den, zveme vás.")
    return msg.as_bytes()


def doc_mail() -> bytes:
    msg = EmailMessage()
    msg["From"] = "faktury@dily-vzor.example"
    msg["Subject"] = "Faktura 2027000123"
    msg["Message-ID"] = "<faktura-1@dily-vzor.example>"
    msg.set_content("V příloze posíláme fakturu.")
    msg.add_attachment(
        (DOKLADY / "faktura-radky.pdf").read_bytes(),
        maintype="application",
        subtype="pdf",
        filename="faktura.pdf",
    )
    msg.add_attachment(
        b"MZ\x90\x00", maintype="application", subtype="octet-stream", filename="x.exe"
    )
    return msg.as_bytes()


def test_notification_is_imported_matched_and_moved(
    processor: MailProcessor, storage: Storage, firma: FirmaConfig
) -> None:
    svc = InvoiceService(storage, firma)
    inv = svc.issue(
        InvoiceDraft(
            "K0001",
            date(2026, 10, 1),
            date(2026, 10, 15),
            [DraftLine("Práce", Decimal("1"), "ks", Decimal("4100"))],
        )
    )
    assert inv["cislo"] == "20260001"
    box = FakeMailbox([(AIRBANK / "prichozi-uhrada.eml").read_bytes()])
    result = processor.run(box)
    assert (result.notifications, result.matched, result.other) == (1, 1, 0)
    assert box.moved == {"Zpracováno": ["1"]}
    assert svc.get("20260001")["stav"] == "uhrazena"  # type: ignore[index]


def test_all_samples_and_duplicates(
    processor: MailProcessor, storage: Storage, firma: FirmaConfig
) -> None:
    samples = [p.read_bytes() for p in sorted(AIRBANK.glob("*.eml"))]
    # The same notification delivered twice (different Message-ID) is stored once.
    duplicate = samples[0].replace(b"Message-ID: <n", b"Message-ID: <dup-n")
    result = processor.run(FakeMailbox([*samples, duplicate]))
    assert result.notifications == 5
    assert len(BankBook(storage, firma).all()) == 4


def test_attachment_goes_to_review_queue(
    processor: MailProcessor, storage: Storage, firma: FirmaConfig
) -> None:
    box = FakeMailbox([doc_mail()])
    result = processor.run(box)
    assert result.documents == 1 and box.moved == {"Zpracováno": ["1"]}
    (doc,) = ReceivedDocs(storage, firma).queue()
    assert doc["zdroj"] == "e-mail" and doc["castka"] == Decimal("1500.00")


def test_other_mail_stays_and_is_not_read_twice(processor: MailProcessor) -> None:
    box = FakeMailbox([other_mail()])
    assert processor.run(box).other == 1
    assert box.inbox and not box.moved
    assert processor.run(box).other == 0  # remembered


def test_notification_for_other_account_stays(processor: MailProcessor, firma: FirmaConfig) -> None:
    firma.banka.ucet = "2000000018/3030"
    box = FakeMailbox([(AIRBANK / "prichozi-uhrada.eml").read_bytes()])
    result = processor.run(box)
    assert result.notifications == 0 and "jinému účtu" in result.errors[0]
    assert not box.moved


def test_connection_error_is_reported(processor: MailProcessor) -> None:
    result = processor.run(FakeMailbox([], fail=True))
    assert result.errors == ["Připojení ke schránce selhalo (TimeoutError)."]
    assert processor.state()["posledni_beh"]["chyby"] == result.errors


def test_one_broken_message_does_not_stop_the_run(
    processor: MailProcessor, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    original = processor._process

    def flaky(msg, result):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return original(msg, result)

    monkeypatch.setattr(processor, "_process", flaky)
    box = FakeMailbox([other_mail("a"), doc_mail()])
    result = processor.run(box)
    assert result.errors == ["Zpráva 1: RuntimeError"] and result.documents == 1


def test_scheduler_only_when_configured(storage: Storage, tmp_path: Path) -> None:
    base = Settings(data_dir=storage.data_dir, config_dir=tmp_path, secret_key="k")
    assert start_scheduler(base, storage, lambda: FakeMailbox([])) is None
    configured = Settings(
        data_dir=storage.data_dir,
        config_dir=tmp_path,
        secret_key="k",
        imap_host="imap.example.cz",
        imap_user="u",
        imap_password="p",
    )
    scheduler = start_scheduler(configured, storage, lambda: FakeMailbox([]))
    assert scheduler is not None
    try:
        job = scheduler.get_job("posta")
        assert job is not None and job.trigger.interval.total_seconds() == 15 * 60
    finally:
        scheduler.shutdown(wait=False)
