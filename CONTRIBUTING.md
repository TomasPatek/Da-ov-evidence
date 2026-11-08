# Jak přispět

Díky za zájem. Tento návod popisuje, jak rozběhnout vývojové prostředí a jak poslat změnu.

## Pravidla

- **Do repozitáře nikdy nepatří skutečná data**: doklady, výpisy, čísla účtů, jména klientů,
  hesla ani firemní branding. Vzorky v `tests/fixtures/` musí být **smyšlené nebo anonymizované**.
- Uživatelské rozhraní a dokumentace jsou česky. Kód, komentáře a commit zprávy anglicky.
- Commity ve formátu [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Peněžní částky jen jako `Decimal`, nikdy `float`. Zaokrouhlování jen přes `app/money.py`.
- Logiku s penězi a daněmi pište tak, že nejdřív napíšete test.
- Dokumentace je součástí každé změny. Změna chování bez úpravy dokumentace se nemerguje.
- Návody v `docs/` mají jednotnou kostru: K čemu slouží, Co je potřeba předem, Postup
  (číslované kroky), Jak ověřit, že to funguje, Časté problémy.

## Vývojové prostředí

Potřebujete [uv](https://docs.astral.sh/uv/) a Git.

```sh
git clone https://github.com/TomasPatek/Danova-evidence.git
cd Danova-evidence
uv sync
git config core.hooksPath .githooks
```

Poslední příkaz zapne pre-commit hook, který odmítne soubory z `data/`, `config/` a `.env`.
Pokud máte nainstalovaný [gitleaks](https://github.com/gitleaks/gitleaks), hook ho spustí také.

Spuštění aplikace s daty smyšlené firmy (heslo `demo-heslo-1234`):

```sh
uv run python scripts/demo.py demo-run
```

Pak otevřete <http://127.0.0.1:8765>.

## Testy

```sh
uv run pytest                                   # jednotkové a integrační testy
uv run playwright install chromium              # jednou, pro E2E testy
uv run pytest -m e2e tests/e2e                  # E2E v prohlížeči (desktop i iPhone)
uv run pytest -m live                           # testy proti skutečnému ARES (v CI vypnuté)
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Moduly `money`, `storage`, `banks`, `tax` a `invoices` musí mít pokrytí testy alespoň 90 %.

## Dokumentace generovaná z kódu

- `docs/csv-format.md` se generuje ze schémat v `app/storage/`. Po změně schématu spusťte
  `uv run python -m app.storage.docs`. CI selže, pokud soubor neodpovídá kódu.
- Screenshoty v `docs/img/` generuje `uv run python scripts/screenshots.py` nad demo daty
  ze `scripts/demo-data/`.

## Jak přidat vzorek dokladu nebo parser banky

1. Vzorek anonymizujte: změňte jména, IČO, adresy, čísla účtů, částky, variabilní symboly i zprávy.
2. Uložte ho do `tests/fixtures/<druh>/` a vedle něj očekávaný výsledek jako JSON (golden file).
3. Napište test, který vzorek zpracuje a porovná výsledek s JSON. Test musí nejdřív selhat.
4. Teprve pak upravte parser.

Podrobný postup pro banky je v [docs/banky.md](docs/banky.md).

## Pull request

1. Vytvořte větev z `main`.
2. Projděte checklist v šabloně pull requestu.
3. Doplňte sekci `Nevydáno` v `CHANGELOG.md`.
4. Merge do `main` je možný jen se zelenou CI.

## Vydání (pro správce)

1. Zvyšte verzi v `pyproject.toml` a `app/__init__.py`, spusťte `uv lock`.
2. Přesuňte položky z `Nevydáno` v `CHANGELOG.md` do nové sekce `## [X.Y.Z] - RRRR-MM-DD`
   a doplňte odkazy na konci souboru.
3. Pull request do `main`, zelená CI, merge.
4. Na aktuálním `main` vytvořte tag a pushněte ho:
   `git checkout main && git pull && git tag vX.Y.Z && git push origin vX.Y.Z`.
5. Workflow *Release* sestaví image pro amd64 i arm64, publikuje ho do `ghcr.io`
   (`ghcr.io/tomaspatek/danova-evidence:X.Y.Z` a `:latest`) a vytvoří GitHub Release
   s poznámkami z CHANGELOGu.
6. Po prvním vydání nastavte v GitHubu balíček `danova-evidence` jako veřejný
   (*Packages → Package settings → Change visibility*), jinak stažení image skončí chybou
   `denied`, a propojte ho s repozitářem (*Connect repository*).
7. Ověřte stažení hotového image podle varianty v `docs/instalace-server.md`.

Změna formátu CSV, která vyžaduje migraci, je vždy nová hlavní verze. Release notes pak
popisují postup migrace a zálohu před ní.

## Nastavení repozitáře na GitHubu (checklist pro správce)

- [ ] Popis repozitáře a témata `danova-evidence`, `osvc`, `fakturace`, `self-hosted`, `cesky`.
- [ ] Ochrana větve `main`: změny jen přes pull request se zelenou CI.
- [ ] Zapnutý secret scanning a push protection.
- [ ] Zapnutý private vulnerability reporting.
- [ ] GitHub Discussions vypnuté. Dotazy přes issues, komerční podpora přes topalux.cz.
