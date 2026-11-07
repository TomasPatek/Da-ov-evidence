# Changelog

Všechny podstatné změny projektu. Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/),
verze se řídí [sémantickým verzováním](https://semver.org/lang/cs/). Změna formátu CSV, která
vyžaduje migraci dat, je vždy nová hlavní verze.

## [Nevydáno]

### Přidáno

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
    s volitelnou reverzní proxy Caddy, testovací docker-compose s Mailpit a GreenMail.
  - CI: ruff, mypy, pytest s kontrolou pokrytí, Playwright E2E (desktop a iPhone), gitleaks,
    build image a smoke test `docker compose up`. Workflow pro vydání do ghcr.io.
  - Pre-commit hook odmítající soubory z `data/`, `config/` a `.env`.
  - Dokumentace: instalace, konfigurace, zálohování, aktualizace, formát CSV (generovaný z kódu),
    CONTRIBUTING, SECURITY, šablony issues a pull requestů.
