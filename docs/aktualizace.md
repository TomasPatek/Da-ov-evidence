# Aktualizace

## K čemu slouží

Návod převede aplikaci na novou verzi. Data zůstávají ve složkách `data` a `config`,
aktualizuje se jen program (Docker image).

## Co je potřeba předem

- Běžící aplikace nainstalovaná podle [instalace na server](instalace-server.md)
  nebo [na vlastní počítač](instalace-lokalne.md).
- Čerstvá záloha podle [zálohování](zalohovani.md).

## Postup

1. Přečtěte si [CHANGELOG](../CHANGELOG.md) nebo poznámky k vydání na
   [stránce Releases](https://github.com/TomasPatek/Da-ov-evidence/releases).
   Nová **hlavní** verze (např. z 1.x na 2.0) mění formát dat a poznámky popisují migraci.
2. Udělejte zálohu podle [zálohování](zalohovani.md).
3. Přejděte do složky aplikace a stáhněte novou verzi.

   Server s Linuxem (instalace přes `git clone`):

   ```sh
   cd ~/danova-evidence
   git pull
   ```

   Windows a macOS (instalace ze ZIPu): stáhněte a rozbalte ZIP stejně jako v kroku 1
   [instalace na vlastní počítač](instalace-lokalne.md), jen místo přejmenování složky
   zkopírujte její obsah přes stávající složku `danova-evidence`. Složky `data`, `config`
   a soubor `.env` v ZIPu nejsou, takže se nepřepíšou.

4. Sestavte a spusťte novou verzi:

   ```sh
   docker compose up -d --build
   ```

   Pokud používáte hotový image (`APP_IMAGE` v `.env`, viz [instalace](instalace-server.md#varianta-hotový-image-místo-sestavení)),
   přepište v `APP_IMAGE` číslo verze na novou a místo sestavení spusťte:

   ```sh
   docker compose pull
   docker compose up -d
   ```

5. Smažte staré image, které už nejsou potřeba:

   ```sh
   docker image prune -f
   ```

### Migrace dat

Zatím žádná verze migraci nevyžaduje. Až bude potřeba, poznámky k vydání popíšou přesný postup.

## Jak ověřit, že to funguje

V patičce aplikace je číslo nové verze a `docker compose ps` ukazuje stav `healthy`.

## Časté problémy

- **`git pull` hlásí konflikt:** ručně jste upravili soubor z repozitáře (např.
  `docker-compose.yml`). Vlastní nastavení patří do `.env`. Změny zahodíte příkazem
  `git checkout -- docker-compose.yml` a `git pull` zopakujete.
- **Po aktualizaci aplikace nenaběhne:** podívejte se do `docker compose logs app`.
  Pro návrat ke staré verzi spusťte `git checkout v<stará verze>` (např. `git checkout v0.1.0`)
  a `docker compose up -d --build`.
