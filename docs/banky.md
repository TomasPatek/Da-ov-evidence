# Jak přidat parser další banky

## K čemu slouží

Návod pro vývojáře: jak naučit aplikaci číst notifikace nebo výpisy další banky.
Parsery bank jsou výměnné moduly ve složce `app/banks/`; první je Air Bank.

## Co je potřeba předem

- Vývojové prostředí podle [CONTRIBUTING.md](../CONTRIBUTING.md).
- Několik notifikací banky uložených jako `.eml` (příchozí a odchozí platba, platba kartou).
  **Před přidáním do repozitáře je anonymizujte:** čísla účtů, jména, částky, zprávy i kódy
  transakcí nahraďte smyšlenými hodnotami. Struktura textu musí zůstat stejná.

## Postup

1. Vytvořte modul `app/banks/<banka>/__init__.py` s třídou, která splňuje rozhraní
   `BankParser` z `app/banks/model.py`:
   - `name` – název banky,
   - `matches_email(msg)` – pozná notifikaci banky (adresa odesílatele a předmět),
   - `parse_email(msg)` – vrátí `BankMovement`, nebo `None`, když zprávu nelze přečíst.
2. `BankMovement` musí mít datum zaúčtování, směr, kladnou částku, náš účet a **kód transakce**.
   Kód slouží ke sloučení stejné transakce z notifikace a z výpisu.
3. Parser zaregistrujte v `PARSERS` v `app/banks/__init__.py`.
4. Anonymizované vzorky dejte do `tests/fixtures/<banka>/` a napište testy po vzoru
   `tests/unit/test_airbank.py`: každý vzorek se přečte, správná pole, odmítnutí podvržené
   adresy odesílatele.
5. Doplňte banku do `docs/banka.md` a do CHANGELOG.

## Jak ověřit, že to funguje

`uv run pytest tests/unit/test_<banka>.py` projde a notifikace nahraná v *Bance → Nahrát
notifikace ručně* se objeví jako pohyb.

## Časté problémy

- **Neviditelné znaky:** banky občas připojují k hodnotám znak BOM (`﻿`). Před
  rozborem textu je odstraňte (viz `_INVISIBLE` v parseru Air Bank).
- **Podvržené notifikace:** ověřujte přesnou doménu odesílatele, ne jen její část.
- **Účet:** aplikace odmítne pohyb k jinému účtu, než je v nastavení; parser proto musí
  vracet číslo účtu, ke kterému notifikace patří.
