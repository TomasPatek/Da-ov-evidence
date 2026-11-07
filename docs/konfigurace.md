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
| `COOKIE_SECURE` | `true` s HTTPS proxy, `false` při přístupu přes `http://`. |
| `APP_PORT` | Port aplikace na serveru, výchozí `8000`. `127.0.0.1:8000` zpřístupní aplikaci jen přes proxy. |
| `APP_UID`, `APP_GID` | Uživatel a skupina, pod kterými kontejner běží. Musí vlastnit složky `data` a `config`. |
| `LOG_LEVEL` | `INFO` (výchozí), `DEBUG` nebo `WARNING`. Na úrovni `INFO` log neobsahuje částky ani jména klientů. |
| `FORWARDED_ALLOW_IPS` | Adresy proxy, jejichž hlavičkám o adrese klienta aplikace věří. S Caddy v compose `*`. |
| `SETUP_TOKEN` | Volitelně pevný kód pro první spuštění. Jinak se vygeneruje a vypíše do logu. |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD` | Schránka, ze které se stahují doklady (fáze 3). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Odesílání faktur (fáze 1). |
| `DOMAIN`, `ACME_EMAIL`, `DNS_PROVIDER`, `DNS_API_TOKEN` | Reverzní proxy Caddy s HTTPS. |

### Soubor `config/firma.toml` (údaje o firmě)

Vytvoří ho průvodce. Vzor je `firma.example.toml`.

| Položka | Význam |
| --- | --- |
| `[firma] nazev` | Jméno a příjmení nebo obchodní firma, jak se tiskne na faktury. |
| `[firma] ico`, `dic` | IČO (8 číslic) a DIČ (`CZ…`, u neplátce DPH nepovinné). |
| `[firma] ulice`, `mesto`, `psc` | Adresa sídla. |
| `[firma] email`, `telefon`, `web` | Kontakty na faktuře. |
| `[firma] zapis_rejstrik` | Údaj o zápisu v živnostenském rejstříku na faktuře. |
| `[banka] ucet`, `iban` | Číslo účtu (`předčíslí-číslo/kód`) a IBAN pro QR platbu. |
| `[fakturace] format_cisla` | `RRRRNNNN` (2026 0001) nebo `RRRRNNN` (2026 001). |
| `[fakturace] pocatecni_cislo` | První pořadové číslo v roce, kdy začínáte aplikaci používat. |
| `[fakturace] splatnost_dni` | Výchozí splatnost faktur ve dnech. |
| `[aplikace] pruvodce_dokoncen` | `true`, jakmile je průvodce prvním spuštěním dokončen. |

### Složka `config/branding/` (vzhled)

| Soubor | Význam |
| --- | --- |
| `logo.svg` nebo `logo.png` | Logo v aplikaci a na fakturách. Nejvýše 1 MB. SVG nesmí obsahovat skripty. |
| `theme.css` | Barvy jako CSS proměnné. Vzor je `branding.example/theme.css`. |
| `faktura.html` | Vlastní šablona faktury (od fáze 1). |

Proměnné v `theme.css`:

| Proměnná | Použití |
| --- | --- |
| `--brand-primary` | Horní lišta, tlačítka, odkazy. |
| `--brand-primary-contrast` | Text na hlavní barvě (bílá nebo černá). |
| `--brand-accent` | Zvýraznění, odkazy v tmavém režimu, rámeček aktivního prvku. |
| `--brand-accent-contrast` | Text na doplňkové barvě. |

V `theme.css` můžete přepsat i proměnné z `app/web/static/css/app.css`, např. `--bg` nebo `--surface`.

## Jak ověřit, že to funguje

Otevřete stránku *Nastavení*. Zobrazené údaje odpovídají souboru `firma.toml`
a barevné vzorky barvám z `theme.css`.

## Časté problémy

- **Po úpravě `firma.toml` aplikace hlásí chybu:** soubor má chybnou syntaxi TOML. Text musí
  být v uvozovkách, čísla a `true`/`false` bez nich.
- **Barvy se nezměnily:** prohlížeč drží starý soubor. Obnovte stránku se Shift.
- **Logo se nezobrazí:** soubor se musí jmenovat přesně `logo.svg` nebo `logo.png`.
