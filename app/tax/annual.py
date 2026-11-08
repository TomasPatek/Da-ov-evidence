"""Annual overview: documents for the income tax return and the ČSSZ / health insurance reports.

* Income from business activity and expenses: § 7 zákona č. 586/1992 Sb. (cash basis,
  columns 9–10 and 15–19 of the cash book) plus tax depreciation (§§ 26–32).
* Assessment base of the self-employed (orientational):
  social insurance 55 % of the profit (zákon č. 589/1992 Sb., § 5b, from 2024),
  health insurance 50 % of the profit (zákon č. 592/1992 Sb., § 3a).
  Minimum assessment bases and rates change every year and are not applied here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.assets import AssetBook
from app.config import FirmaConfig
from app.invoices.schemas import InvoiceState
from app.invoices.service import InvoiceService
from app.jobs import ZAKAZKY_SCHEMA
from app.journal import Journal
from app.money import ZERO, format_display_amount, round_money, sum_money
from app.received import DocState, ReceivedDocs
from app.storage import Record, Storage

SOCIAL_SHARE = Decimal("0.55")
HEALTH_SHARE = Decimal("0.50")


@dataclass
class AnnualReport:
    year: int
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    depreciation: Decimal = ZERO
    not_affecting_income: Decimal = ZERO
    not_affecting_expenses: Decimal = ZERO
    columns: dict[int, Decimal] = field(default_factory=dict)
    opening_cash: Decimal = ZERO
    opening_bank: Decimal = ZERO
    closing_cash: Decimal = ZERO
    closing_bank: Decimal = ZERO
    receivables: list[Record] = field(default_factory=list)
    payables: list[Record] = field(default_factory=list)
    jobs: list[dict[str, object]] = field(default_factory=list)
    assets: list[tuple[Record, Decimal]] = field(default_factory=list)
    checks_ok: bool = True
    journal_ready: bool = True

    @property
    def tax_base(self) -> Decimal:
        return self.income - self.expenses - self.depreciation

    @property
    def expenses_with_depreciation(self) -> Decimal:
        return self.expenses + self.depreciation

    @property
    def vz_social(self) -> Decimal:
        return round_money(max(self.tax_base, ZERO) * SOCIAL_SHARE)

    @property
    def vz_health(self) -> Decimal:
        return round_money(max(self.tax_base, ZERO) * HEALTH_SHARE)


def _unpaid_at(record: Record, end: date) -> bool:
    paid = record.get("datum_uhrady")
    return paid is None or paid > end


def annual_report(storage: Storage, firma: FirmaConfig, year: int) -> AnnualReport:
    report = AnnualReport(year=year)
    end = date(year, 12, 31)
    journal = Journal(storage, firma)
    report.journal_ready = journal.ready
    if journal.ready:
        et = journal.et_report(year)
        t = et.totals
        report.columns = dict(t)
        report.income = t[9] + t[10]
        report.expenses = sum_money(t[c] for c in range(15, 20))
        report.not_affecting_income = t[11] + t[12] + t[13]
        report.not_affecting_expenses = sum_money(t[c] for c in range(20, 24))
        report.opening_cash, report.opening_bank = et.opening_cash, et.opening_bank
        report.closing_cash, report.closing_bank = et.closing_cash, et.closing_bank
        report.checks_ok = et.checks_ok

    assets = AssetBook(storage)
    report.assets = assets.depreciation(year)
    report.depreciation = sum_money(amount for _, amount in report.assets)

    invoices = InvoiceService(storage, firma).all_invoices()
    report.receivables = sorted(
        (
            i
            for i in invoices
            if i["datum_vystaveni"] <= end
            and i["stav"] != InvoiceState.CANCELLED
            and _unpaid_at(i, end)
        ),
        key=lambda i: i["cislo"],
    )
    docs = ReceivedDocs(storage, firma).all()
    report.payables = sorted(
        (
            d
            for d in docs
            if d["stav"] != DocState.REVIEW
            and d["datum_vystaveni"]
            and d["datum_vystaveni"] <= end
            and _unpaid_at(d, end)
        ),
        key=lambda d: d["id"],
    )

    entries = journal.entries(year) if journal.ready else []
    for job in storage.table(ZAKAZKY_SCHEMA).all():
        rows = [e for e in entries if e["zakazka_id"] == job["id"]]
        if not rows:
            continue
        income = sum_money(e["castka"] for e in rows if e["smer"] == "příjem")
        costs = sum_money(e["castka"] for e in rows if e["smer"] == "výdaj")
        report.jobs.append(
            {
                "id": job["id"],
                "nazev": job["nazev"],
                "prijmy": income,
                "naklady": costs,
                "rozdil": income - costs,
            }
        )
    report.jobs.sort(key=lambda j: str(j["id"]))
    return report


def _kc(value: Decimal) -> str:
    return format_display_amount(value).replace("\u00a0", " ")


def to_markdown(r: AnnualReport, firma: FirmaConfig) -> str:
    f = firma.firma
    lines = [
        f"# Roční přehled {r.year}",
        "",
        f"{f.nazev}, IČO {f.ico}. Daňová evidence, neplátce DPH.",
        "",
        "> Orientační podklad. Nenahrazuje daňové přiznání ani daňového poradce.",
        "",
        "## Podklady k přiznání k dani z příjmů (příloha č. 1)",
        "",
        "| Položka | Částka |",
        "| --- | ---: |",
        f"| Příjmy z podnikání (sloupce 9 + 10) | {_kc(r.income)} |",
        f"| Výdaje (sloupce 15–19) | {_kc(r.expenses)} |",
        f"| Daňové odpisy majetku | {_kc(r.depreciation)} |",
        f"| Výdaje celkem včetně odpisů | {_kc(r.expenses_with_depreciation)} |",
        f"| Dílčí základ daně (§ 7) | {_kc(r.tax_base)} |",
        "",
        "## Přehledy pro ČSSZ a zdravotní pojišťovnu (orientačně)",
        "",
        "| Položka | Částka |",
        "| --- | ---: |",
        f"| Vyměřovací základ, sociální pojištění (55 %) | {_kc(r.vz_social)} |",
        f"| Vyměřovací základ, zdravotní pojištění (50 %) | {_kc(r.vz_health)} |",
        "",
        "Minimální vyměřovací základy a sazby se mění každý rok a nejsou započteny.",
        "",
        "## Peněžní prostředky",
        "",
        "| | Začátek roku | Konec roku |",
        "| --- | ---: | ---: |",
        f"| Pokladna | {_kc(r.opening_cash)} | {_kc(r.closing_cash)} |",
        f"| Účet | {_kc(r.opening_bank)} | {_kc(r.closing_bank)} |",
        "",
        "## Příjmy a výdaje neovlivňující základ daně",
        "",
        f"- Příjmy (sloupce 11–13): {_kc(r.not_affecting_income)}",
        f"- Výdaje (sloupce 20–23): {_kc(r.not_affecting_expenses)}",
        "",
        f"## Pohledávky k 31. 12. {r.year} (neuhrazené vydané faktury)",
        "",
    ]
    if r.receivables:
        lines += ["| Faktura | Vystaveno | Splatnost | Částka |", "| --- | --- | --- | ---: |"]
        for i in r.receivables:
            lines.append(
                f"| {i['cislo']} | {i['datum_vystaveni']:%d. %m. %Y} | "
                f"{i['datum_splatnosti']:%d. %m. %Y} | {_kc(i['castka'])} |"
            )
    else:
        lines.append("Žádné.")
    lines += ["", f"## Závazky k 31. 12. {r.year} (neuhrazené přijaté doklady)", ""]
    if r.payables:
        lines += ["| Doklad | Dodavatel | Vystaveno | Částka |", "| --- | --- | --- | ---: |"]
        for d in r.payables:
            lines.append(
                f"| {d['id']} | {d['dodavatel_nazev']} | {d['datum_vystaveni']:%d. %m. %Y} | "
                f"{_kc(d['castka'])} |"
            )
    else:
        lines.append("Žádné.")
    lines += ["", "## Majetek a odpisy", ""]
    if r.assets:
        lines += ["| Majetek | Skupina | Způsob | Odpis |", "| --- | --- | --- | ---: |"]
        for a, amount in r.assets:
            lines.append(
                f"| {a['nazev']} | {a['odpisova_skupina']} | {a['zpusob_odpisu']} | {_kc(amount)} |"
            )
    else:
        lines.append("Žádný odpisovaný majetek.")
    lines += ["", "## Zakázky (podle úhrad v roce)", ""]
    if r.jobs:
        lines += ["| Zakázka | Příjmy | Náklady | Rozdíl |", "| --- | ---: | ---: | ---: |"]
        for j in r.jobs:
            lines.append(
                f"| {j['id']} {j['nazev']} | {_kc(j['prijmy'])} | {_kc(j['naklady'])} | "  # type: ignore[arg-type]
                f"{_kc(j['rozdil'])} |"  # type: ignore[arg-type]
            )
    else:
        lines.append("Žádné zakázky s platbami.")
    return "\n".join(lines) + "\n"
