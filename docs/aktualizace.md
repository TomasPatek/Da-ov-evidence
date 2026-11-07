# Aktualizace

## K čemu slouží

Návod převede aplikaci na novou verzi. Data zůstávají ve složkách `data` a `config`,
aktualizuje se jen program (Docker image).

## Co je potřeba předem

- Běžící aplikace nainstalovaná podle [instalace na server](instalace-server.md)
  nebo [na vlastní počítač](instalace-lokalne.md).
- Čerstvá záloha podle [zálohování](zalohovani.md).

## Postup

1. Přečtěte si poznámky k vydání na
   [stránce Releases](https://github.com/TomasPatek/Da-ov-evidence/releases).
   Nová **hlavní** verze (např. z 1.x na 2.0) mění formát dat a poznámky popisují migraci.
2. Udělejte zálohu podle [zálohování](zalohovani.md).
3. Přejděte do složky aplikace a stáhněte nový image:

   ```sh
   cd ~/danova-evidence
   docker compose pull
   ```

4. Spusťte aplikaci s novým image:

   ```sh
   docker compose up -d
   ```

5. Smažte staré image, které už nejsou potřeba:

   ```sh
   docker image prune -f
   ```

Pokud chcete zůstat u konkrétní verze, nastavte v `.env` např. `APP_VERSION=1.2.0`.

### Migrace dat

Zatím žádná verze migraci nevyžaduje. Až bude potřeba, poznámky k vydání popíšou přesný postup.

## Jak ověřit, že to funguje

V patičce aplikace je číslo nové verze a `docker compose ps` ukazuje stav `healthy`.

## Časté problémy

- **`docker compose pull` nic nestáhl:** v `.env` je nastavená pevná verze `APP_VERSION`.
  Změňte ji, nebo řádek smažte.
- **Po aktualizaci aplikace nenaběhne:** podívejte se do `docker compose logs app`.
  Pro návrat ke staré verzi nastavte v `.env` `APP_VERSION=<stará verze>`
  a spusťte `docker compose up -d`.
