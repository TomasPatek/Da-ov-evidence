"""Generate docs/csv-format.md from the table schemas.

Usage: ``python -m app.storage.docs [--check]``. With ``--check`` exits non-zero
when the committed file differs (used in CI).
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.storage.csvformat import ColumnKind
from app.storage.schemas import ALL_SCHEMAS

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "csv-format.md"

KIND_LABELS = {
    ColumnKind.TEXT: "text",
    ColumnKind.MONEY: "částka (`1234,50`)",
    ColumnKind.DECIMAL: "číslo (`1,5`)",
    ColumnKind.INT: "celé číslo",
    ColumnKind.DATE: "datum (`RRRR-MM-DD`)",
    ColumnKind.DATETIME: "datum a čas (`RRRR-MM-DDTHH:MM:SS+01:00`)",
    ColumnKind.BOOL: "`ano` / `ne`",
}

INTRO = """\
# Formát CSV souborů

> Tento soubor je generovaný z kódu (`python -m app.storage.docs`). Neupravujte ho ručně.

## K čemu slouží

CSV soubory ve složce `/data` jsou hlavní úložiště aplikace, ne export. Tento popis
vám umožní pracovat s daty i bez aplikace: otevřít je v Excelu nebo Numbers,
zkontrolovat je nebo z nich něco spočítat.

## Co je potřeba předem

- Přístup ke složce `data` (na serveru nebo ze zálohy).
- Program na tabulky: Microsoft Excel, Apple Numbers nebo LibreOffice Calc.

## Postup

1. Než soubor upravíte ručně, zastavte aplikaci (`docker compose stop`) nebo pracujte s kopií.
2. Soubor otevřete dvojklikem. Český Excel ho načte bez průvodce importem.
3. Po ruční úpravě uložte soubor zase jako CSV (UTF-8, oddělovač středník).
4. Aplikaci spusťte. Při chybě ve formátu vypíše soubor, řádek a sloupec.

## Společná pravidla

- Kódování UTF-8 s BOM, oddělovač `;`, první řádek je hlavička, konce řádků CRLF.
- Text se středníkem, uvozovkami nebo novým řádkem je v uvozovkách podle RFC 4180.
- Datum `RRRR-MM-DD`, částky s desetinnou čárkou a bez oddělovače tisíců (`1234,50`).
- Prázdná buňka znamená „nevyplněno“.
- Každý záznam má neměnné `id`; vazby mezi soubory jdou přes `id`.
- Text začínající znakem `=`, `+`, `-`, `@`, tabulátorem nebo apostrofem je uložen
  s apostrofem navíc na začátku (`'=…`). Tabulkový program ho pak nespustí jako vzorec.
  Aplikace apostrof při čtení odstraní.
- Soubory s rokem v cestě leží ve složce roku, např. `2026/denik.csv`.
- Každou změnu zapisuje aplikace do `audit.csv`.

## Ověření

Otevřete soubor v Excelu. Diakritika je správně, každý sloupec je ve vlastní buňce
a částky jsou zarovnané doprava (Excel je bere jako čísla).

## Časté problémy

- **Excel zobrazí vše v jednom sloupci:** soubor byl uložen s čárkou jako oddělovačem.
  Uložte ho znovu jako „CSV (oddělený středníkem)“.
- **Rozbitá diakritika:** soubor byl uložen v jiném kódování než UTF-8.
- **Aplikace hlásí neznámý sloupec:** v hlavičce je sloupec, který aplikace nezná.
  Přejmenujte ho zpět nebo odstraňte.

## Soubory
"""


def render() -> str:
    parts = [INTRO]
    for schema in ALL_SCHEMAS:
        path = f"RRRR/{schema.name}" if schema.per_year else schema.name
        parts.append(f"\n### `{path}`\n\n{schema.description}\n\n")
        parts.append("| Sloupec | Typ | Popis |\n| --- | --- | --- |\n")
        for col in schema.columns:
            parts.append(f"| `{col.name}` | {KIND_LABELS[col.kind]} | {col.description} |\n")
    return "".join(parts)


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
        if current != content:
            print("docs/csv-format.md je zastaralý, spusťte: python -m app.storage.docs")
            return 1
        return 0
    DOC_PATH.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
