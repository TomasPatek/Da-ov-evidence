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

### `kontakty.csv`

Odběratelé a dodavatelé. Faktury, zakázky a doklady na ně odkazují přes `id`.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `id` | text | Neměnný identifikátor, např. `K0001`. |
| `typ` | text | `odběratel`, `dodavatel` nebo `obojí`. |
| `ico` | text | IČO (8 číslic), u soukromé osoby prázdné. |
| `dic` | text | DIČ, např. `CZ12345678`. |
| `nazev` | text | Název firmy nebo jméno a příjmení. |
| `ulice` | text | Ulice a číslo. |
| `mesto` | text | Obec. |
| `psc` | text | PSČ. |
| `email` | text | E-mail pro zasílání faktur. |
| `telefon` | text | Telefon. |
| `poznamka` | text | Volná poznámka. |
| `ares_aktualizovano` | datum (`RRRR-MM-DD`) | Kdy byly údaje naposledy načteny z ARES; prázdné, pokud byly zadány ručně. |

### `zakazky.csv`

Zakázky. Faktury, doklady a platby se k nim připojují přes `zakazka_id`.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `id` | text | Neměnný identifikátor `ZRRRR-NNN`, např. `Z2026-001`. |
| `kontakt_id` | text | Zákazník, odkaz na `kontakty.csv`. |
| `nazev` | text | Krátký název zakázky. |
| `adresa_realizace` | text | Kde se zakázka provádí. |
| `stav` | text | `poptávka`, `rozpracováno`, `dokončeno`, `vyfakturováno` nebo `uhrazeno`. |
| `datum_zalozeni` | datum (`RRRR-MM-DD`) | Kdy byla zakázka založena. |
| `datum_dokonceni` | datum (`RRRR-MM-DD`) | Kdy byla dokončena; prázdné, dokud běží. |
| `poznamka` | text | Volná poznámka. |

### `RRRR/faktury-vydane.csv`

Vydané faktury roku. Vystavená faktura se nemaže, jen se stornuje. Položky jsou v `faktury-vydane-polozky.csv`.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `cislo` | text | Číslo faktury `RRRRNNNN`, řada bez děr. Je i variabilním symbolem. |
| `kontakt_id` | text | Odběratel, odkaz na `kontakty.csv`. |
| `zakazka_id` | text | Zakázka, odkaz na `zakazky.csv`; může být prázdné. |
| `datum_vystaveni` | datum (`RRRR-MM-DD`) | Datum vystavení. |
| `datum_splatnosti` | datum (`RRRR-MM-DD`) | Datum splatnosti. |
| `vs` | text | Variabilní symbol (stejný jako číslo faktury). |
| `castka` | částka (`1234,50`) | Celková částka k úhradě. |
| `mena` | text | Měna, zatím vždy `CZK`. |
| `stav` | text | `vystavena`, `odeslana`, `uhrazena` nebo `stornovana`. |
| `datum_odeslani` | datum (`RRRR-MM-DD`) | Kdy byla faktura odeslána e-mailem. |
| `datum_uhrady` | datum (`RRRR-MM-DD`) | Kdy byla faktura uhrazena. |
| `duvod_storna` | text | Důvod storna; vyplněno jen u stornované faktury. |
| `soubor_pdf` | text | PDF faktury, cesta v rámci složky roku. |
| `poznamka` | text | Poznámka vytištěná na faktuře. |

### `RRRR/faktury-vydane-polozky.csv`

Položky vydaných faktur. Součet `celkem` položek je `castka` faktury.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `id` | text | Identifikátor položky `cislo-poradi`, např. `20260001-1`. |
| `faktura_cislo` | text | Číslo faktury, odkaz na `faktury-vydane.csv`. |
| `poradi` | celé číslo | Pořadí položky na faktuře, od 1. |
| `popis` | text | Text položky. |
| `mnozstvi` | číslo (`1,5`) | Množství. |
| `jednotka` | text | Jednotka, např. `ks`, `hod`, `m²`. |
| `cena_jednotkova` | částka (`1234,50`) | Cena za jednotku. |
| `celkem` | částka (`1234,50`) | Množství × cena za jednotku, zaokrouhleno na haléře. |

### `RRRR/doklady-prijate.csv`

Přijaté doklady (faktury a účtenky od dodavatelů). Soubory leží ve složce `doklady/` roku a jmenují se podle `id`. Výdaj se do deníku zapíše při úhradě.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `id` | text | Neměnný identifikátor `PDRRRR-NNN`, např. `PD2027-001`. |
| `typ` | text | `faktura`, `účtenka` nebo `jiný`. |
| `kontakt_id` | text | Dodavatel, odkaz na `kontakty.csv` (po potvrzení). |
| `dodavatel_ico` | text | IČO dodavatele, jak bylo na dokladu. |
| `dodavatel_nazev` | text | Název dodavatele, jak byl na dokladu. |
| `cislo_dodavatele` | text | Číslo dokladu u dodavatele. |
| `datum_vystaveni` | datum (`RRRR-MM-DD`) | Datum vystavení. |
| `datum_splatnosti` | datum (`RRRR-MM-DD`) | Datum splatnosti. |
| `castka` | částka (`1234,50`) | Celková částka včetně DPH (neplátce DPH ji uplatní celou). |
| `mena` | text | Měna, zatím jen `CZK`. |
| `vs` | text | Variabilní symbol pro úhradu. |
| `ucet` | text | Účet dodavatele (číslo/kód banky nebo IBAN). |
| `popis` | text | Co bylo nakoupeno. |
| `kategorie` | celé číslo | Sloupec výdajů ET 328 (15–23). |
| `zakazka_id` | text | Zakázka, na kterou byl nákup; prázdné = režie. |
| `soubor` | text | Soubor dokladu, cesta v rámci složky roku. |
| `zdroj` | text | `e-mail`, `foto`, `upload` nebo `ručně`. |
| `stav` | text | `ke kontrole`, `potvrzen` nebo `uhrazen`. |
| `datum_uhrady` | datum (`RRRR-MM-DD`) | Kdy byl doklad zaplacen. |
| `zpusob_uhrady` | text | `převod`, `hotovost`, `karta` nebo `QR na místě`. |
| `nejista_pole` | text | Pole, která aplikace přečetla nejistě (oddělená čárkou); po kontrole prázdné. |
| `poznamka` | text | Volná poznámka. |

### `RRRR/denik.csv`

Peněžní deník roku. Každý řádek je jeden pohyb peněz v pokladně nebo na účtu, s datem skutečné úhrady. Sloupec `kategorie` je číslo sloupce tiskopisu ET 328.

| Sloupec | Typ | Popis |
| --- | --- | --- |
| `id` | text | Neměnný identifikátor `DRRRR-NNNN`. |
| `datum_uhrady` | datum (`RRRR-MM-DD`) | Datum skutečné úhrady (ne datum vystavení). |
| `cislo_dokladu` | text | Číslo dokladu ve sloupci *b* ET 328: u účtu kód transakce z notifikace banky, bez něj číslo faktury nebo přijatého dokladu, u hotovosti příjmový `PPD1/27…` nebo výdajový `VPD1/27…` pokladní doklad (číslo/dvojčíslí roku), u bankovního pohybu bez dokladu `B1…`. |
| `doklad_id` | text | Vazba na vydanou fakturu nebo přijatý doklad. |
| `popis` | text | Text zápisu (sloupec *c* ET 328). |
| `smer` | text | `příjem` nebo `výdaj` (z pohledu pokladny nebo účtu). |
| `castka` | částka (`1234,50`) | Částka, vždy kladná. |
| `ucet` | text | `hotovost` (sloupce 1–3) nebo `banka` (sloupce 4–5). |
| `zpusob_uhrady` | text | `převod`, `hotovost`, `karta` nebo `QR na místě` (pro případné EET). |
| `kategorie` | celé číslo | Sloupec ET 328: příjmy 9–13, výdaje 15–23, převod mezi pokladnou a účtem 6 nebo 7. |
| `danove_uznatelny` | `ano` / `ne` | `ano`, pokud zápis ovlivňuje základ daně (sloupce 9, 10 a 15–19). |
| `zakazka_id` | text | Zakázka, ke které zápis patří; prázdné = režie. |
| `poznamka` | text | Volná poznámka. |

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
