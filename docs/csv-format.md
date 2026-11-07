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

### `audit.csv`

Záznam všech změn v datových souborech. Každý změněný sloupec má vlastní řádek. Soubor se jen doplňuje, nikdy se z něj nemaže.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `cas` | datum a čas (`RRRR-MM-DDTHH:MM:SS+01:00`) | Kdy ke změně došlo (místní čas s časovou zónou). |
| `soubor` | text | Cesta k souboru v `/data`, např. `2026/denik.csv`. |
| `zaznam_id` | text | Hodnota `id` změněného záznamu. |
| `akce` | text | `vytvoření`, `změna` nebo `smazání`. |
| `pole` | text | Název změněného sloupce. |
| `stara_hodnota` | text | Hodnota před změnou, tak jak byla v CSV. |
| `nova_hodnota` | text | Hodnota po změně, tak jak je v CSV. |
