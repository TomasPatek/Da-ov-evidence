# Changelog

Všechny podstatné změny projektu. Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/),
verze se řídí [sémantickým verzováním](https://semver.org/lang/cs/). Změna formátu CSV, která
vyžaduje migraci dat, je vždy nová hlavní verze.

## [Nevydáno]

### Změněno

- Nová sekce `[evidence]` ve `firma.toml`; u existující instalace ji vyplníte v *Nastavení →
  Peněžní deník*. Docker image obsahuje knihovnu `libzbar0` pro čtení QR kódů.
- Nové proměnné `SMTP_FROM` a `SMTP_SECURITY` v `.env`; nová položka `[fakturace] text_dph`
  ve `firma.toml` (výchozí „Nejsem plátce DPH.“). Stávající soubory není potřeba upravovat.
- Formát číselné řady nejde změnit, jakmile existuje vystavená faktura.
- Docker image obsahuje knihovny pro vykreslení PDF (Pango, HarfBuzz, písma DejaVu).
- Krok „Pošta“ v průvodci vysvětluje, proč se heslo k e-mailu zadává jen do `.env`, a obsahuje
  postup nastavení včetně doporučení použít heslo pro aplikace.

### Opraveno

- Formulář *Zadat ručně* u přijatých dokladů se neotevřel (chyba při zobrazení prázdné částky).
- Nový zápis do deníku nabízí jen kategorie zvoleného směru (příjmy nebo výdaje).
- PDF faktury: IBAN přetékal do sloupce s daty.
- Údaj o zápisu v živnostenském rejstříku se na faktuře tiskne v patičce místo v bloku dodavatele.
- Instalace podle návodu končila chybou `denied` a `open Dockerfile: no such file or directory`,
  protože návod stahoval jen `docker-compose.yml` a počítal s image na `ghcr.io`, který zatím
  neexistuje. Do prvního vydání se aplikace instaluje z repozitáře a image sestavuje lokálně
  (`docker compose up -d --build`).
- Sestavení Docker image selhalo na chybě `Readme file does not exist: README.md`; soubor se
  teď do sestavení kopíruje.
- Aplikace v kontejneru padala na `ModuleNotFoundError`, když zdrojové složky neměly práva
  pro čtení ostatními (např. po rozbalení ZIPu). Práva se teď při sestavení srovnají.

### Přidáno

- Fáze 2, evidence:
  - Peněžní deník (`RRRR/denik.csv`) ve sloupcích tiskopisu ET 328: pokladna a účet se
    zůstatky, pokladní doklady číslované `PPD1/27` a `VPD1/27`, u pohybů na účtu kód transakce
    z notifikace banky jako číslo dokladu, průběžné položky pro převody, kontrolní součty, tabulka ET 328 k tisku,
    orientační rozdíl příjmů a výdajů. Kategorie a daňová uznatelnost jsou v `app/tax`
    s odkazy na zákon č. 586/1992 Sb.
  - Začátek evidence a počáteční stavy pokladny a účtu v průvodci a v nastavení.
  - Úhrada vydané faktury se zapíše do deníku (převodem, hotově, kartou, QR na místě).
  - Přijaté doklady (`RRRR/doklady-prijate.csv`, soubory v `RRRR/doklady/`): nahrání PDF,
    fotky nebo ISDOC, čtení ISDOC (i jako přílohy PDF), QR platby a textové vrstvy PDF,
    šablony dodavatelů (`sablony-dodavatelu.json`), fronta Ke kontrole s náhledem a
    zvýrazněním nejistých polí, ověření dodavatele v ARES, návrh zakázky, ruční zadání,
    úhrada a její zrušení.
  - Zakázky: přímé náklady z přijatých dokladů, rozdíl, upozornění na materiál nakoupený
    po poslední faktuře.
  - Smyšlené vzorky dokladů s očekávanými výsledky (`tests/fixtures/doklady`) a skript
    `scripts/make_ingest_fixtures.py`.
  - Návody `docs/doklady.md` a `docs/denik.md`.
- Fáze 1, fakturace:
  - Kontakty (`kontakty.csv`): odběratelé a dodavatelé, načtení a aktualizace údajů z ARES,
    kontrola IČO a duplicit, vyhledávání.
  - Zakázky (`zakazky.csv`, čísla `ZRRRR-NNN`): stavy od poptávky po úhradu, přehled
    fakturace, upozornění na dokončenou zakázku bez faktury. Stav *vyfakturováno*
    a *uhrazeno* nastavuje aplikace podle faktur.
  - Vydané faktury (`RRRR/faktury-vydane.csv` a `RRRR/faktury-vydane-polozky.csv`): číselná
    řada bez děr i při souběžném vystavení, číslo je zároveň variabilní symbol, položky
    s průběžným součtem, storno s důvodem místo smazání, ruční označení úhrady.
  - Úprava vystavené faktury, dokud není uhrazená ani stornovaná; číslo zůstává, PDF se vytvoří
    znovu. U již odeslané faktury se před úpravou zobrazí upozornění.
  - PDF faktury (WeasyPrint) s logem, barvami, údajem o zápisu v rejstříku a textem
    „Nejsem plátce DPH.“; vlastní šablona `config/branding/faktura.html`.
  - QR platba (SPAYD) na faktuře i v aplikaci.
  - Export ISDOC 6.0.2, ověřený v testech proti oficiálnímu XSD.
  - Odeslání faktury e-mailem přes SMTP s PDF a volitelně ISDOC v příloze; příklad nastavení
    pro WEDOS v `docs/konfigurace.md`.
  - Přehled: neuhrazené faktury a faktury po splatnosti, fakturace za rok, zakázky bez faktury.
  - Návod `docs/fakturace.md`.
- Fáze 0, kostra aplikace:
  - FastAPI aplikace se šablonami Jinja2 a HTMX, světlý i tmavý režim, použitelná na mobilu.
  - Přihlášení jedním uživatelem (heslo Argon2, session cookie HttpOnly/Secure/SameSite=Strict),
    omezení počtu neúspěšných pokusů, ochrana CSRF, bezpečnostní hlavičky.
  - Průvodce prvním spuštěním: heslo s jednorázovým kódem z logu, firemní údaje z ARES,
    bankovní účet s výpočtem IBAN, přehled nastavení pošty, logo a barvy, číselná řada faktur.
  - Vrstva CSV úložiště: UTF-8 s BOM, středník, atomický zápis, zámky souborů, ochrana proti
    vzorcům v Excelu, auditní log `audit.csv`.
  - Peněžní částky výhradně v Decimal se zaokrouhlením na haléře na jednom místě.
  - Klient ARES za rozhraním, validace IČO a českých čísel účtů.
  - Branding mimo repozitář (`/config/branding`), neutrální výchozí vzhled.
  - Dockerfile (neprivilegovaný uživatel, read-only kořenový souborový systém), docker-compose
    pro provoz jen v lokální síti, testovací docker-compose s Mailpit a GreenMail.
  - CI: ruff, mypy, pytest s kontrolou pokrytí, Playwright E2E (desktop a iPhone), gitleaks,
    build image a smoke test `docker compose up`. Workflow pro vydání do ghcr.io.
  - Pre-commit hook odmítající soubory z `data/`, `config/` a `.env`.
  - Dokumentace: instalace, konfigurace, zálohování, aktualizace, formát CSV (generovaný z kódu),
    CONTRIBUTING, SECURITY, šablony issues a pull requestů.
