"""Run the app with demo data of a fictional company.

Used by E2E tests and the screenshot script; can also be run by hand:
``python scripts/demo.py /tmp/demo`` then open http://127.0.0.1:8765 (heslo: demo-heslo-1234).
"""

from __future__ import annotations

import email
import shutil
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from email import policy
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import date, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402
from typing import ClassVar  # noqa: E402

from app.ares.client import AresSubjekt  # noqa: E402
from app.auth import PasswordStore  # noqa: E402
from app.banks.airbank import AirBankParser  # noqa: E402
from app.banks.book import BankBook  # noqa: E402
from app.config import FirmaConfig, Settings  # noqa: E402
from app.contacts import KONTAKTY_SCHEMA  # noqa: E402
from app.invoices.pdf import render_pdf  # noqa: E402
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceService  # noqa: E402
from app.jobs import ZAKAZKY_SCHEMA  # noqa: E402
from app.main import create_app  # noqa: E402
from app.received import Confirmation, ReceivedDocs  # noqa: E402
from app.storage import Storage  # noqa: E402

DEMO_DIR = ROOT / "scripts" / "demo-data"
DEMO_PASSWORD = "demo-heslo-1234"
DEMO_SETUP_TOKEN = "DEMO0001"


class DemoAres:
    """Offline ARES with fictional subjects (IČO with a valid checksum, not real firms)."""

    SUBJECTS: ClassVar[dict[str, AresSubjekt]] = {
        "99990024": AresSubjekt(
            ico="99990024",
            nazev="Truhlářství Pokus s.r.o.",
            dic="CZ99990024",
            ulice="Dřevařská 8",
            mesto="Vzorov",
            psc="54321",
            datum_aktualizace=None,
        ),
    }

    def lookup(self, ico: str) -> AresSubjekt | None:
        return self.SUBJECTS.get(ico.zfill(8))


def _contact(cid: str, typ: str, nazev: str, **kw: str) -> dict[str, object]:
    base: dict[str, object] = dict.fromkeys(
        ("ico", "dic", "ulice", "mesto", "psc", "email", "telefon", "poznamka"), ""
    )
    return {**base, "id": cid, "typ": typ, "nazev": nazev, "ares_aktualizovano": None, **kw}


def _job(jid: str, kontakt: str, nazev: str, stav: str, started: date) -> dict[str, object]:
    return {
        "id": jid,
        "kontakt_id": kontakt,
        "nazev": nazev,
        "adresa_realizace": "Vzorov",
        "stav": stav,
        "datum_zalozeni": started,
        "datum_dokonceni": None,
        "poznamka": "",
    }


def seed(settings: Settings, today: date | None = None) -> None:
    """Fictional contacts, jobs and invoices so screens are not empty."""
    today = today or date.today()
    storage = Storage(settings.data_dir)
    contacts = storage.table(KONTAKTY_SCHEMA)
    contacts.insert(
        _contact(
            "K0001",
            "odběratel",
            "Petr Novák",
            ulice="Lipová 3",
            mesto="Vzorov",
            psc="54321",
            email="petr@example.cz",
        )
    )
    contacts.insert(
        _contact(
            "K0002",
            "obojí",
            "Obec Vzorov",
            ico="99990016",
            ulice="Náměstí 1",
            mesto="Vzorov",
            psc="54321",
            email="podatelna@example.cz",
        )
    )
    contacts.insert(
        _contact(
            "K0003",
            "dodavatel",
            "Stavebniny Vzor s.r.o.",
            ico="99990008",
            dic="CZ99990008",
            ulice="Průmyslová 5",
            mesto="Vzorov",
            psc="54321",
        )
    )
    jobs = storage.table(ZAKAZKY_SCHEMA)
    y = (today - timedelta(days=60)).year
    for n, kontakt, nazev, stav, days_ago in (
        (1, "K0001", "Oprava střechy", "rozpracováno", 60),
        (2, "K0002", "Rekonstrukce koupelny v MŠ", "rozpracováno", 50),
        (3, "K0002", "Výměna okapů na hasičárně", "dokončeno", 45),
    ):
        jobs.insert(_job(f"Z{y}-{n:03d}", kontakt, nazev, stav, today - timedelta(days=days_ago)))

    cfg = FirmaConfig.load(settings.firma_path)
    cfg.evidence.zacatek = date(y, 1, 1).isoformat()
    cfg.evidence.pocatecni_hotovost = "3500,00"
    cfg.evidence.pocatecni_banka = "42000,00"
    cfg.save(settings.firma_path)
    svc = InvoiceService(storage, cfg)
    pdf = lambda view: render_pdf(view, settings.branding_dir)  # noqa: E731
    d = Decimal

    def issue(days_ago: int, kontakt: str, job: str, lines: list[DraftLine]) -> str:
        issued = today - timedelta(days=days_ago)
        draft = InvoiceDraft(kontakt, issued, issued + timedelta(days=14), lines, job)
        return str(svc.issue(draft, render_pdf=pdf)["cislo"])

    first = issue(
        40,
        "K0001",
        f"Z{y}-001",
        [
            DraftLine("Oprava střešní krytiny", d("16"), "hod", d("450")),
            DraftLine("Střešní tašky", d("35"), "ks", d("42.50")),
        ],
    )
    svc.mark_paid(first, today - timedelta(days=30), today=today)
    issue(
        25,
        "K0002",
        f"Z{y}-002",
        [
            DraftLine("Bourací práce", d("24"), "hod", d("420")),
            DraftLine("Odvoz suti", d("1"), "paušál", d("2500")),
        ],
    )
    issue(3, "K0002", f"Z{y}-002", [DraftLine("Obklady a dlažba", d("18.5"), "m²", d("690"))])

    # Received documents from the fictional samples used by the parser tests.
    docs = ReceivedDocs(storage, cfg)
    samples = ROOT / "tests" / "fixtures" / "doklady"
    paid = docs.upload((samples / "faktura-radky.pdf").read_bytes(), today=today)
    docs.confirm(
        paid["id"],
        Confirmation(
            typ="faktura",
            dodavatel_ico="99990032",
            dodavatel_nazev="Díly Vzor s.r.o.",
            cislo_dodavatele="2027000123",
            datum_vystaveni=today - timedelta(days=20),
            datum_splatnosti=today - timedelta(days=6),
            castka=d("1500"),
            vs="2027000123",
            ucet="19-2000145399/0800",
            popis="Topné těleso a těsnění",
            kategorie=15,
            zakazka_id=f"Z{y}-002",
            zpusob_uhrady="převod",
            datum_uhrady=today - timedelta(days=10),
        ),
        today=today,
    )
    docs.upload((samples / "faktura-sloupce.pdf").read_bytes(), today=today)
    docs.upload((samples / "faktura.isdoc").read_bytes(), today=today)

    # Bank notifications (anonymized Air Bank samples) waiting for matching.
    book = BankBook(storage, cfg)
    for eml in sorted((ROOT / "tests" / "fixtures" / "airbank").glob("*.eml")):
        msg = email.message_from_bytes(eml.read_bytes(), policy=policy.default)
        movement = AirBankParser().parse_email(msg)  # type: ignore[arg-type]
        if movement is not None:
            book.auto_match(book.import_movement(movement)[0])


def prepare(target: Path, configured: bool = True) -> Settings:
    """Copy demo config into ``target``; ``configured=False`` gives a fresh install."""
    config, data = target / "config", target / "data"
    if configured:
        shutil.copytree(DEMO_DIR / "config", config, dirs_exist_ok=True)
        PasswordStore(config / "auth.json").set_password(DEMO_PASSWORD)
    data.mkdir(parents=True, exist_ok=True)
    settings = _settings(config, data)
    if configured:
        seed(settings)
    return settings


def _settings(config: Path, data: Path) -> Settings:
    return Settings(
        data_dir=data,
        config_dir=config,
        secret_key="demo-secret-key-not-for-production",
        cookie_secure=False,
        setup_token=DEMO_SETUP_TOKEN,
        log_level="WARNING",
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def serve(settings: Settings, port: int | None = None) -> Iterator[str]:
    """Run the app in a background thread; yields the base URL."""
    port = port or free_port()
    app = create_app(settings, ares=DemoAres())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-run")
    with serve(prepare(target), port=8765) as url:
        print(f"Demo běží na {url}, heslo: {DEMO_PASSWORD}. Ukončete Ctrl+C.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
