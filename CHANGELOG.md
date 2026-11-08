# Changelog

Všechny podstatné změny projektu. Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/),
verze se řídí [sémantickým verzováním](https://semver.org/lang/cs/). Změna formátu CSV, která
vyžaduje migraci dat, je vždy nová hlavní verze.

## [Nevydáno]

### Změněno

- CI a sestavení vydání používají nové verze akcí GitHubu (Node 24).

### Opraveno

- Kontrola dokumentace CSV v CI už nepotřebuje knihovnu zbar.

## [1.0.0] - 2026-11-08

První veřejné vydání. Aplikace pokrývá běžný rok OSVČ, která není plátcem DPH: fakturaci,
přijaté doklady, peněžní deník ve sloupcích ET 328, banku a párování plateb, majetek,
roční přehledy a zálohování.

Daňová pravidla (kategorie, odpisy, vyměřovací základy) mají odkazy na zákon č. 586/1992 Sb.
a jsou označená k ověření s daňovým poradcem. Načítání měsíčního výpisu Air Bank a položek
faktur s více řádky z Air Bank přibude v další verzi.

### Přidáno

- Fáze 4, dokončení:
  - Evidence majetku (`majetek.csv`) s rovnoměrnými (§ 31) a zrychlenými (§ 32) odpisy,
    přerušením a polovičním odpisem v roce vyřazení; pravidla v `app/tax/depreciation.py`.
  - Roční přehled: příjmy, výdaje, odpisy, dílčí základ daně, orientační vyměřovací základy
    ČSSZ a ZP, pohledávky a závazky k 31. 12., majetek, zakázky; export do PDF a Markdownu.
  - Uzamčení roku proti změnám (úhrady faktur a dokladů z uzamčeného roku dál možné),
    zápis do auditního logu.
  - OCR skenů a fotek (Tesseract, čeština), focení účtenek z mobilu, otočení fotek podle EXIF.
  - Ikona na ploše iPhonu (manifest, ikony), stránka pro uzamčení a zálohu v nastavení.
  - Noční šifrovaná záloha (restic, cloud přes rclone nebo složka) s retencí, stránka
    *Záloha*, obnova `python -m app.backup obnovit` ověřená testem.
  - Návody `docs/rocni-prehled.md`, `docs/mobil.md`, přepracovaný `docs/zalohovani.md`.
- Fáze 3, automatizace:
  - Stahování pošty přes IMAP každých 15 minut (APScheduler v aplikaci) a tlačítkem;
    zpracované zprávy se přesouvají do složky *Zpracováno*, ostatní zůstávají a čtou se jen jednou.
  - Parser notifikací Air Bank (`app/banks/airbank`) včetně plateb kartou, výměnné parsery bank (`docs/banky.md`).
  - Bankovní pohyby (`RRRR/banka.csv`), sloučení duplicit podle kódu transakce.
  - Párování: automaticky podle VS a částky, návrhy (částečná úhrada, přeplatek, shoda částky
    nebo účtu, platba kartou k už zaplacenému dokladu), zápis jiných pohybů, převody, zrušení.
  - Částečné úhrady vydaných faktur.
  - Doklady z příloh e-mailů jdou do fronty Ke kontrole.
  - Faktury vystavené v Air Bank se poznají (vaše IČO jako dodavatel, platba na váš účet)
    a převezmou do vydaných faktur pod svým číslem a s původním PDF; aplikace pokračuje
    ve stejné číselné řadě. Nový sloupec `zdroj` ve `faktury-vydane.csv`.
  - Ruční nahrání notifikací `.eml`; stránky *Banka* a *Pošta*; návod `docs/banka.md`.
  - Anonymizované vzorky notifikací v `tests/fixtures/airbank`, test proti GreenMail v CI.
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

[Nevydáno]: https://github.com/TomasPatek/Da-ov-evidence/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/TomasPatek/Da-ov-evidence/releases/tag/v1.0.0
