# Konfigurace

## K čemu slouží

Popisuje všechna nastavení aplikace: tajné údaje v `.env`, údaje o firmě v `firma.toml`
a vzhled ve složce `branding`. Většinu nastaví průvodce prvním spuštěním; ručně je upravíte,
když chcete něco změnit později nebo hromadně.

## Co je potřeba předem

- Nainstalovaná aplikace podle [instalace na server](instalace-server.md) nebo
  [na vlastní počítač](instalace-lokalne.md).
- Textový editor.

## Postup

1. Zastavte aplikaci: `docker compose stop`.
2. Upravte příslušný soubor podle tabulek níže.
3. Spusťte aplikaci: `docker compose up -d`.

Soubory `firma.toml` a `branding/` aplikace načítá při každém zobrazení stránky, takže
u nich stačí obnovit stránku. Změny v `.env` vyžadují `docker compose up -d`.

### Soubor `.env` (tajné údaje a provoz)

Leží vedle `docker-compose.yml`. Do repozitáře nikdy nepatří; vzor je `.env.example`.

| Proměnná | Význam |
| --- | --- |
| `SECRET_KEY` | Tajný klíč pro přihlašovací cookie. Vygenerujte `openssl rand -base64 48`. Když chybí, aplikace si ho vygeneruje do `config/.secret_key`. |
| `COOKIE_SECURE` | `false` (výchozí) pro přístup přes `http://` v lokální síti. `true` jen pokud před aplikaci sami postavíte HTTPS. |
| `APP_PORT` | Port aplikace na serveru, výchozí `8000`. Ve tvaru `<IP-adresa>:8000` poslouchá jen na dané adrese. |
| `APP_UID`, `APP_GID` | Uživatel a skupina, pod kterými kontejner běží. Musí vlastnit složky `data` a `config`. |
| `LOG_LEVEL` | `INFO` (výchozí), `DEBUG` nebo `WARNING`. Na úrovni `INFO` log neobsahuje částky ani jména klientů. |
| `SETUP_TOKEN` | Volitelně pevný kód pro první spuštění. Jinak se vygeneruje a vypíše do logu. |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD` | Schránka, ze které se budou stahovat doklady (zatím se nepoužívá). |
| `SMTP_HOST`, `SMTP_PORT` | Server pro odesílání faktur. Port `465` (šifrované spojení) nebo `587` (STARTTLS). |
| `SMTP_USER`, `SMTP_PASSWORD` | Přihlášení k odchozí poště. Použijte heslo pro aplikace, pokud ho schránka umožňuje. |
| `SMTP_FROM` | Adresa odesílatele faktur. Když chybí, použije se `SMTP_USER`. |
| `SMTP_SECURITY` | Volitelné: `ssl`, `starttls` nebo `none`. Bez vyplnění se odvodí z portu (465 = `ssl`, jinak `starttls`). `none` jen pro testovací server. |

#### Příklad: pošta u WEDOS

Přesný název serveru (`wesX-smtp.wedos.net` a `wesX-imap.wedos.net`, kde X je číslo) najdete v zákaznické administraci WEDOS
u služby mailhosting. Příklad pro server `wes1`:

```sh
SMTP_HOST=wes1-smtp.wedos.net
SMTP_PORT=465
SMTP_USER=fakturace@vase-domena.cz
SMTP_PASSWORD=heslo-ke-schrance
SMTP_FROM=fakturace@vase-domena.cz

IMAP_HOST=wes1-imap.wedos.net
IMAP_PORT=993
IMAP_USER=fakturace@vase-domena.cz
IMAP_PASSWORD=heslo-ke-schrance
```

Po uložení spusťte `docker compose up -d`. U faktury pak tlačítko *Odeslat e-mailem* ukáže
formulář místo upozornění, že pošta není nastavená.

### Soubor `config/firma.toml` (údaje o firmě)

Vytvoří ho průvodce. Vzor je `firma.example.toml`.

| Položka | Význam |
| --- | --- |
| `[firma] nazev` | Jméno a příjmení nebo obchodní firma, jak se tiskne na faktury. |
| `[firma] ico`, `dic` | IČO (8 číslic) a DIČ (`CZ…`, u neplátce DPH nepovinné). |
| `[firma] ulice`, `mesto`, `psc` | Adresa sídla. |
| `[firma] email`, `telefon`, `web` | Kontakty na faktuře. |
| `[firma] zapis_rejstrik` | Údaj o zápisu v živnostenském rejstříku a příslušném úřadu, tiskne se v patičce faktury. |
| `[banka] ucet`, `iban` | Číslo účtu (`předčíslí-číslo/kód`) a IBAN pro QR platbu. |
| `[fakturace] format_cisla` | `RRRRNNNN` (2026 0001) nebo `RRRRNNN` (2026 001). Po vystavení první faktury už nejde změnit. |
| `[fakturace] pocatecni_cislo` | Pořadové číslo úplně první faktury v aplikaci (pokud jste letos už fakturovali jinde). Další roky začínají vždy od 1. |
| `[fakturace] splatnost_dni` | Výchozí splatnost faktur ve dnech. |
| `[fakturace] text_dph` | Text na faktuře, výchozí „Nejsem plátce DPH.“ |
| `[aplikace] pruvodce_dokoncen` | `true`, jakmile je průvodce prvním spuštěním dokončen. |

### Složka `config/branding/` (vzhled)

| Soubor | Význam |
| --- | --- |
| `logo.svg` nebo `logo.png` | Logo v aplikaci a na fakturách. Nejvýše 1 MB. SVG nesmí obsahovat skripty. |
| `theme.css` | Barvy jako CSS proměnné. Vzor je `branding.example/theme.css`. |
| `faktura.html` | Vlastní šablona faktury. Výchozí je `app/invoices/templates/faktura.html`; zkopírujte ji a upravte. |

Proměnné v `theme.css`:

| Proměnná | Použití |
| --- | --- |
| `--brand-primary` | Horní lišta, tlačítka, odkazy. |
| `--brand-primary-contrast` | Text na hlavní barvě (bílá nebo černá). |
| `--brand-accent` | Zvýraznění, odkazy v tmavém režimu, rámeček aktivního prvku. |
| `--brand-accent-contrast` | Text na doplňkové barvě. |

V `theme.css` můžete přepsat i proměnné z `app/web/static/css/app.css`, např. `--bg` nebo `--surface`.

Faktura používá `--brand-primary` a `--brand-primary-contrast`. Vlastní šablona `faktura.html`
smí načítat jen obrázky vložené přímo do souboru (`data:`), žádné odkazy na web ani na jiné soubory.
Logo, barvy a QR kód do ní aplikace vloží sama. Změna šablony se projeví jen u nově vystavených
faktur; PDF už vystavených faktur zůstávají beze změny.

## Jak ověřit, že to funguje

Otevřete stránku *Nastavení*. Zobrazené údaje odpovídají souboru `firma.toml`
a barevné vzorky barvám z `theme.css`.

## Časté problémy

- **Po úpravě `firma.toml` aplikace hlásí chybu:** soubor má chybnou syntaxi TOML. Text musí
  být v uvozovkách, čísla a `true`/`false` bez nich.
- **Barvy se nezměnily:** prohlížeč drží starý soubor. Obnovte stránku se Shift.
- **Logo se nezobrazí:** soubor se musí jmenovat přesně `logo.svg` nebo `logo.png`.
- **Odeslání faktury hlásí „Server odmítl přihlášení“:** zkontrolujte `SMTP_USER` a `SMTP_PASSWORD`.
  U WEDOS platí nové heslo až asi po 15 minutách.
- **Odeslání skončí chybou `TimeoutError` nebo `ConnectionRefusedError`:** zkuste druhý port
  (`465` ↔ `587`). Server musí mít povolené odchozí spojení na tento port.
