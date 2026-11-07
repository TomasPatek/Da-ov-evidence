"""Categories of the cash book (peněžní deník) following the Baloušek ET 328 form.

Each income or expense category is one column of the form. Whether it enters the tax
base follows zákon č. 586/1992 Sb., o daních z příjmů (ZDP). References are given at
the level of the paragraph; the exact letter must be checked with a tax advisor
before relying on it in edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

ZDP = "zákon č. 586/1992 Sb."

# Tangible assets with an input price above this amount are depreciated, not expensed
# at once (§ 26 odst. 2 ZDP).
DHM_THRESHOLD = Decimal("80000")


class Direction(StrEnum):
    INCOME = "příjem"
    EXPENSE = "výdaj"


@dataclass(frozen=True)
class Category:
    column: int
    label: str
    direction: Direction
    affects_tax_base: bool
    legal_ref: str
    help: str = ""


INCOME_COLUMNS: tuple[Category, ...] = (
    Category(
        9,
        "prodej zboží, výrobků a služeb",
        Direction.INCOME,
        True,
        f"§ 7 {ZDP}",
        "Úhrady vydaných faktur a tržby.",
    ),
    Category(
        10,
        "ostatní příjmy ovlivňující základ daně",
        Direction.INCOME,
        True,
        f"§ 7 {ZDP}",
        "Např. prodej majetku používaného v podnikání, náhrady škod.",
    ),
    Category(
        11,
        "příjmy zdaněné u zdroje srážkou",
        Direction.INCOME,
        False,
        f"§ 36 {ZDP}",
        "Např. úroky z účtu, z nichž banka strhla daň.",
    ),
    Category(
        12,
        "úvěry, dotace, peněžní dary, půjčky, vklad",
        Direction.INCOME,
        False,
        f"§ 3 odst. 4 {ZDP}",
        "Vklad podnikatele, přijatý úvěr nebo půjčka.",
    ),
    Category(
        13,
        "ostatní příjmy neovlivňující základ daně",
        Direction.INCOME,
        False,
        f"§ 3 odst. 4 {ZDP}",
        "Např. vrácené přeplatky.",
    ),
)

EXPENSE_COLUMNS: tuple[Category, ...] = (
    Category(
        15,
        "materiál",
        Direction.EXPENSE,
        True,
        f"§ 24 {ZDP}",
        "Materiál a náhradní díly spotřebované při práci.",
    ),
    Category(
        16, "zboží", Direction.EXPENSE, True, f"§ 24 {ZDP}", "Zboží nakoupené k dalšímu prodeji."
    ),
    Category(
        17, "mzdy, srážky z mezd", Direction.EXPENSE, True, f"§ 24 {ZDP}", "Mzdy zaměstnanců."
    ),
    Category(
        18,
        "pojistné za zaměstnance",
        Direction.EXPENSE,
        True,
        f"§ 24 {ZDP}",
        "Sociální a zdravotní pojištění placené za zaměstnance.",
    ),
    Category(
        19,
        "provozní režie",
        Direction.EXPENSE,
        True,
        f"§ 24 {ZDP}",
        "Telefon, nájem, PHM, nářadí do 80 000 Kč, služby.",
    ),
    Category(
        20,
        "nákup DHM, DNM a finančního majetku",
        Direction.EXPENSE,
        False,
        f"§ 26 a § 25 {ZDP}",
        "Majetek nad 80 000 Kč; do základu daně jde postupně odpisy.",
    ),
    Category(
        21,
        "daň z příjmů, pojistné OSVČ",
        Direction.EXPENSE,
        False,
        f"§ 25 {ZDP}",
        "Zálohy na daň, sociální a zdravotní pojištění OSVČ.",
    ),
    Category(
        22,
        "peněžní dary, splátky úvěrů a půjček",
        Direction.EXPENSE,
        False,
        f"§ 25 {ZDP}",
        "Splátky jistiny, dary.",
    ),
    Category(
        23,
        "osobní spotřeba, ostatní",
        Direction.EXPENSE,
        False,
        f"§ 25 {ZDP}",
        "Výběry pro osobní potřebu, výdaje nesouvisející s podnikáním.",
    ),
)

_BY_COLUMN = {c.column: c for c in (*INCOME_COLUMNS, *EXPENSE_COLUMNS)}


def category(column: int) -> Category:
    return _BY_COLUMN[column]


def categories(direction: Direction) -> tuple[Category, ...]:
    return INCOME_COLUMNS if direction is Direction.INCOME else EXPENSE_COLUMNS


def default_category(direction: Direction) -> Category:
    return categories(direction)[0]


def hints_for_expense(column: int, amount: Decimal) -> list[str]:
    """Non-blocking hints shown when a received document is confirmed."""
    hints = []
    if column in (15, 16, 19) and amount > DHM_THRESHOLD:
        hints.append(
            "Částka je nad 80 000 Kč. Jde-li o hmotný majetek (stroj, auto, nářadí), "
            "nepatří do výdajů najednou, ale do sloupce 20 a do základu daně jde odpisy "
            f"(§ 26 {ZDP})."
        )
    return hints
