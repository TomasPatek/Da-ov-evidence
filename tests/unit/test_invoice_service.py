"""Invoice lifecycle on real CSV files: numbering under a lock, states, job updates."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import FirmaConfig
from app.contacts import KONTAKTY_SCHEMA
from app.invoices.schemas import FAKTURY_SCHEMA, POLOZKY_SCHEMA
from app.invoices.service import DraftLine, InvoiceDraft, InvoiceError, InvoiceService
from app.jobs import ZAKAZKY_SCHEMA
from app.storage import Storage
from app.storage.csvformat import parse_csv

D = Decimal


def contact(cid: str = "K0001") -> dict[str, object]:
    return {
        "id": cid,
        "typ": "odběratel",
        "ico": "",
        "dic": "",
        "nazev": "Petr Zákazník",
        "ulice": "Dlouhá 1",
        "mesto": "Brno",
        "psc": "60200",
        "email": "petr@example.cz",
        "telefon": "",
        "poznamka": "",
        "ares_aktualizovano": None,
    }


def job(
    jid: str = "Z2026-001", stav: str = "rozpracováno", kontakt: str = "K0001"
) -> dict[str, object]:
    return {
        "id": jid,
        "kontakt_id": kontakt,
        "nazev": "Oprava střechy",
        "adresa_realizace": "Dlouhá 1, Brno",
        "stav": stav,
        "datum_zalozeni": date(2026, 1, 5),
        "datum_dokonceni": None,
        "poznamka": "",
    }


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(tmp_path / "data")
    s.ensure_layout()
    s.table(KONTAKTY_SCHEMA).insert(contact())
    s.table(KONTAKTY_SCHEMA).insert(contact("K0002"))
    s.table(ZAKAZKY_SCHEMA).insert(job())
    return s


@pytest.fixture
def firma() -> FirmaConfig:
    cfg = FirmaConfig()
    cfg.banka.iban = "CZ9501000000001234567899"
    return cfg


@pytest.fixture
def svc(storage: Storage, firma: FirmaConfig) -> InvoiceService:
    return InvoiceService(storage, firma)


def draft(day: int = 10, zakazka: str = "", kontakt: str = "K0001", **kw: object) -> InvoiceDraft:
    lines = kw.pop(
        "lines",
        [
            DraftLine("Práce", D("8"), "hod", D("450")),
            DraftLine('Materiál; "střešní" krytina', D("1.5"), "m²", D("333.33")),
        ],
    )
    return InvoiceDraft(
        kontakt_id=kontakt,
        datum_vystaveni=date(2026, 2, day),
        datum_splatnosti=date(2026, 2, day + 14),
        lines=lines,  # type: ignore[arg-type]
        zakazka_id=zakazka,
        **kw,  # type: ignore[arg-type]
    )


def test_issue_writes_invoice_and_items(svc: InvoiceService, storage: Storage) -> None:
    inv = svc.issue(draft(poznamka="Děkuji"))
    assert inv["cislo"] == "20260001"
    assert inv["vs"] == "20260001"
    # 8 * 450 = 3600.00; 1.5 * 333.33 = 499.995 -> 500.00
    assert inv["castka"] == D("4100.00")
    assert inv["stav"] == "vystavena"
    items = svc.items("20260001")
    assert [i["poradi"] for i in items] == [1, 2]
    assert items[1]["celkem"] == D("500.00")
    raw = (storage.data_dir / "2026" / "faktury-vydane-polozky.csv").read_text("utf-8-sig")
    header, *rows = parse_csv(raw)
    assert rows[1][header.index("popis")] == 'Materiál; "střešní" krytina'
    assert rows[1][header.index("mnozstvi")] == "1,5"


def test_numbers_are_sequential(svc: InvoiceService) -> None:
    numbers = [svc.issue(draft(day=d))["cislo"] for d in (1, 2, 2, 3)]
    assert numbers == ["20260001", "20260002", "20260003", "20260004"]


def test_configured_start_applies_only_to_first_invoice_ever(
    storage: Storage, firma: FirmaConfig
) -> None:
    firma.fakturace.pocatecni_cislo = 15
    svc = InvoiceService(storage, firma)
    assert svc.issue(draft())["cislo"] == "20260015"
    assert svc.issue(draft())["cislo"] == "20260016"
    nxt = draft()
    nxt.datum_vystaveni, nxt.datum_splatnosti = date(2027, 1, 2), date(2027, 1, 16)
    assert svc.issue(nxt)["cislo"] == "20270001"


def test_short_format(storage: Storage, firma: FirmaConfig) -> None:
    firma.fakturace.format_cisla = "RRRRNNN"
    assert InvoiceService(storage, firma).issue(draft())["cislo"] == "2026001"


def test_concurrent_issuing_has_no_gaps_or_duplicates(svc: InvoiceService) -> None:
    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(svc.issue(draft())["cislo"])
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(results) == [f"2026{n:04d}" for n in range(1, 9)]
    assert len(svc.items("20260008")) == 2


def test_date_cannot_go_back_within_year(svc: InvoiceService) -> None:
    svc.issue(draft(day=10))
    with pytest.raises(InvoiceError, match="poslední faktury"):
        svc.issue(draft(day=9))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kontakt": "K9999"}, "odběratele"),
        ({"lines": []}, "aspoň jednu"),
        ({"lines": [DraftLine("", D("1"), "ks", D("1"))]}, "chybí popis"),
        ({"lines": [DraftLine("Sleva", D("1"), "ks", D("-5"))]}, "kladná"),
        ({"zakazka": "Z2026-999"}, "neexistuje"),
        ({"zakazka": "Z2026-001", "kontakt": "K0002"}, "jinému"),
    ],
)
def test_validation(svc: InvoiceService, kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(InvoiceError, match=message):
        svc.issue(draft(**kwargs))  # type: ignore[arg-type]
    assert svc.invoices(2026) == []


def test_due_before_issue_rejected(svc: InvoiceService) -> None:
    d = draft()
    d.datum_splatnosti = date(2026, 2, 1)
    with pytest.raises(InvoiceError, match="splatnosti"):
        svc.issue(d)


def test_orphan_items_from_crash_are_replaced(svc: InvoiceService, storage: Storage) -> None:
    storage.table(POLOZKY_SCHEMA, 2026).insert(
        {
            "id": "20260001-1",
            "faktura_cislo": "20260001",
            "poradi": 1,
            "popis": "zbytek po pádu",
            "mnozstvi": D("1"),
            "jednotka": "ks",
            "cena_jednotkova": D("1.00"),
            "celkem": D("1.00"),
        }
    )
    svc.issue(draft())
    assert [i["popis"] for i in svc.items("20260001")] == [
        "Práce",
        'Materiál; "střešní" krytina',
    ]


def test_job_follows_invoice_lifecycle(svc: InvoiceService, storage: Storage) -> None:
    jobs = storage.table(ZAKAZKY_SCHEMA)
    a = svc.issue(draft(zakazka="Z2026-001"))
    assert jobs.get("Z2026-001")["stav"] == "vyfakturováno"  # type: ignore[index]
    b = svc.issue(draft(zakazka="Z2026-001"))
    svc.mark_paid(a["cislo"], date(2026, 2, 20), today=date(2026, 3, 1))
    assert jobs.get("Z2026-001")["stav"] == "vyfakturováno"  # type: ignore[index]
    svc.mark_paid(b["cislo"], date(2026, 2, 21), today=date(2026, 3, 1))
    assert jobs.get("Z2026-001")["stav"] == "uhrazeno"  # type: ignore[index]
    svc.mark_unpaid(b["cislo"])
    assert jobs.get("Z2026-001")["stav"] == "vyfakturováno"  # type: ignore[index]
    # Cancelling the only unpaid invoice leaves just paid ones -> job paid.
    svc.cancel(b["cislo"], "Chybná částka")
    assert jobs.get("Z2026-001")["stav"] == "uhrazeno"  # type: ignore[index]


def test_cancelling_all_invoices_returns_job_to_done(svc: InvoiceService, storage: Storage) -> None:
    inv = svc.issue(draft(zakazka="Z2026-001"))
    svc.cancel(inv["cislo"], "Duplicitní")
    assert storage.table(ZAKAZKY_SCHEMA).get("Z2026-001")["stav"] == "dokončeno"  # type: ignore[index]


def test_paid_and_unpaid(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    svc.mark_sent(inv["cislo"], date(2026, 2, 10))
    paid = svc.mark_paid(inv["cislo"], date(2026, 2, 15), today=date(2026, 2, 16))
    assert paid["stav"] == "uhrazena"
    assert paid["datum_uhrady"] == date(2026, 2, 15)
    with pytest.raises(InvoiceError):
        svc.mark_paid(inv["cislo"], date(2026, 2, 15), today=date(2026, 2, 16))
    with pytest.raises(InvoiceError, match="neuhrazenou"):
        svc.cancel(inv["cislo"], "x")
    back = svc.mark_unpaid(inv["cislo"])
    assert back["stav"] == "odeslana"
    assert back["datum_uhrady"] is None


def test_payment_date_not_in_future(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    with pytest.raises(InvoiceError, match="budoucnosti"):
        svc.mark_paid(inv["cislo"], date(2026, 3, 2), today=date(2026, 3, 1))


def test_cancel_requires_reason_and_keeps_record(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    with pytest.raises(InvoiceError, match="důvod"):
        svc.cancel(inv["cislo"], "  ")
    svc.cancel(inv["cislo"], "Vystaveno omylem")
    stored = svc.get(inv["cislo"])
    assert stored is not None
    assert stored["stav"] == "stornovana"
    assert stored["duvod_storna"] == "Vystaveno omylem"
    with pytest.raises(InvoiceError):
        svc.mark_sent(inv["cislo"], date(2026, 2, 11))
    # The cancelled number stays taken.
    assert svc.issue(draft())["cislo"] == "20260002"
    assert svc.view(inv["cislo"]).spayd is None  # type: ignore[union-attr]


def test_view_has_payment_qr(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    view = svc.view(inv["cislo"])
    assert view is not None
    assert view.customer["nazev"] == "Petr Zákazník"
    assert view.spayd is not None
    assert "*AM:4100.00*" in view.spayd
    assert "*X-VS:20260001*" in view.spayd
    assert "*DT:20260224*" in view.spayd


def test_pdf_is_written_and_linked(svc: InvoiceService, storage: Storage) -> None:
    inv = svc.issue(draft(), render_pdf=lambda v: b"%PDF-" + v.cislo.encode())
    assert inv["soubor_pdf"] == "doklady/20260001.pdf"
    assert (storage.data_dir / "2026" / "doklady" / "20260001.pdf").read_bytes() == b"%PDF-20260001"


def test_years_and_lookup(svc: InvoiceService) -> None:
    assert svc.years() == []
    svc.issue(draft())
    assert svc.years() == [2026]
    assert svc.get("nesmysl") is None
    assert svc.get("20990001") is None
    assert svc.view("20260099") is None
    assert FAKTURY_SCHEMA.per_year


# -- editing -----------------------------------------------------------------------


def test_update_keeps_number_and_replaces_items(svc: InvoiceService, storage: Storage) -> None:
    inv = svc.issue(draft(day=10), render_pdf=lambda v: b"%PDF-old")
    changed = draft(day=11, lines=[DraftLine("Jen práce", D("2"), "hod", D("500"))])
    changed.poznamka = "Opraveno"
    rec = svc.update(inv["cislo"], changed, render_pdf=lambda v: b"%PDF-new")
    assert rec["cislo"] == inv["cislo"] == rec["vs"]
    assert rec["castka"] == D("1000.00")
    assert rec["datum_vystaveni"] == date(2026, 2, 11)
    assert [i["popis"] for i in svc.items(inv["cislo"])] == ["Jen práce"]
    pdf = storage.data_dir / "2026" / "doklady" / f"{inv['cislo']}.pdf"
    assert pdf.read_bytes() == b"%PDF-new"
    changes = [e for e in storage.audit.entries() if e["akce"] == "změna" and e["pole"] == "castka"]
    assert changes and changes[-1]["stara_hodnota"] == "4100,00"


def test_update_keeps_sent_state(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    svc.mark_sent(inv["cislo"], date(2026, 2, 10))
    rec = svc.update(inv["cislo"], draft())
    assert rec["stav"] == "odeslana"
    assert rec["datum_odeslani"] == date(2026, 2, 10)


def test_update_refused_for_paid_and_cancelled(svc: InvoiceService) -> None:
    a, b = svc.issue(draft()), svc.issue(draft())
    svc.mark_paid(a["cislo"], date(2026, 2, 12), today=date(2026, 3, 1))
    svc.cancel(b["cislo"], "Omyl")
    for cislo in (a["cislo"], b["cislo"]):
        with pytest.raises(InvoiceError, match="neuhrazenou"):
            svc.update(cislo, draft())


def test_update_date_must_stay_between_neighbours_and_in_year(svc: InvoiceService) -> None:
    svc.issue(draft(day=5))
    mid = svc.issue(draft(day=10))
    svc.issue(draft(day=12))
    with pytest.raises(InvoiceError, match="předchozí"):
        svc.update(mid["cislo"], draft(day=4))
    with pytest.raises(InvoiceError, match="následující"):
        svc.update(mid["cislo"], draft(day=13))
    other_year = draft()
    other_year.datum_vystaveni, other_year.datum_splatnosti = date(2027, 1, 5), date(2027, 1, 19)
    with pytest.raises(InvoiceError, match="v roce 2026"):
        svc.update(mid["cislo"], other_year)
    assert svc.update(mid["cislo"], draft(day=12))["datum_vystaveni"] == date(2026, 2, 12)


def test_update_validates_like_issue(svc: InvoiceService) -> None:
    inv = svc.issue(draft())
    with pytest.raises(InvoiceError, match="aspoň jednu"):
        svc.update(inv["cislo"], draft(lines=[]))
    assert len(svc.items(inv["cislo"])) == 2


def test_update_moves_invoice_between_jobs(svc: InvoiceService, storage: Storage) -> None:
    jobs = storage.table(ZAKAZKY_SCHEMA)
    jobs.insert(job("Z2026-002", stav="dokončeno"))
    inv = svc.issue(draft(zakazka="Z2026-001"))
    svc.update(inv["cislo"], draft(zakazka="Z2026-002"))
    assert jobs.get("Z2026-001")["stav"] == "dokončeno"  # type: ignore[index]
    assert jobs.get("Z2026-002")["stav"] == "vyfakturováno"  # type: ignore[index]


def test_draft_of_round_trips(svc: InvoiceService) -> None:
    original = draft(poznamka="Pozn.")
    inv = svc.issue(original)
    again = svc.draft_of(inv["cislo"])
    assert again.total == original.total
    assert again.poznamka == "Pozn."
    assert [line.popis for line in again.lines] == [line.popis for line in original.lines]


# -- cash book -----------------------------------------------------------------------


def test_payment_goes_to_cash_book_from_start(storage: Storage, firma: FirmaConfig) -> None:
    from app.journal import Journal, PaymentMethod

    firma.evidence.zacatek = "2026-02-15"
    svc = InvoiceService(storage, firma)
    early, late, cash = svc.issue(draft(day=1)), svc.issue(draft(day=2)), svc.issue(draft(day=3))
    svc.mark_paid(early["cislo"], date(2026, 2, 14), today=date(2026, 3, 1))
    svc.mark_paid(late["cislo"], date(2026, 2, 20), today=date(2026, 3, 1), kod_transakce="5550001")
    svc.mark_paid(
        cash["cislo"], date(2026, 2, 21), today=date(2026, 3, 1), method=PaymentMethod.CASH
    )
    journal = Journal(storage, firma)
    rows = journal.entries(2026)
    assert [r["doklad_id"] for r in rows] == [late["cislo"], cash["cislo"]]
    bank, kasa = rows
    assert (bank["ucet"], bank["smer"], bank["kategorie"], bank["castka"]) == (
        "banka",
        "příjem",
        9,
        D("4100.00"),
    )
    assert bank["cislo_dokladu"] == "5550001"
    assert bank["doklad_id"] == late["cislo"]
    assert bank["popis"] == f"Úhrada faktury {late['cislo']} – Petr Zákazník"
    assert (kasa["ucet"], kasa["cislo_dokladu"], kasa["zpusob_uhrady"]) == (
        "hotovost",
        "PPD1/26",
        "hotovost",
    )
    svc.mark_unpaid(late["cislo"])
    assert [r["doklad_id"] for r in journal.entries(2026)] == [cash["cislo"]]
