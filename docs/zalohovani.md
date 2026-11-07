# Zálohování a obnova

## K čemu slouží

Všechna data aplikace jsou ve dvou složkách: `data` (evidence, doklady, audit) a `config`
(nastavení, heslo, logo). Když je zálohujete, obnovíte celou evidenci na jiném počítači.

> Vestavěná noční šifrovaná záloha (restic) přibude ve fázi 4. Do té doby zálohujte ručně
> podle tohoto návodu.

## Co je potřeba předem

- Přístup na server, kde aplikace běží.
- Místo pro zálohu mimo server (NAS, externí disk).

## Postup

### Záloha

1. Přejděte do složky aplikace:

   ```sh
   cd ~/danova-evidence
   ```

2. Zastavte aplikaci, aby se během zálohy nic neměnilo:

   ```sh
   docker compose stop app
   ```

3. Zabalte data, konfiguraci a soubor `.env`:

   ```sh
   tar czf danova-evidence-$(date +%F).tar.gz data config .env docker-compose.yml
   ```

4. Spusťte aplikaci:

   ```sh
   docker compose start app
   ```

5. Archiv přesuňte na NAS nebo externí disk. Obsahuje citlivé údaje, ukládejte ho
   na místo, kam nemá přístup nikdo cizí.

### Obnova na čistém stroji

1. Nainstalujte Docker podle [instalace na server](instalace-server.md), část „Co je potřeba předem“.
2. Vytvořte složku a rozbalte do ní zálohu:

   ```sh
   mkdir -p ~/danova-evidence && cd ~/danova-evidence
   tar xzf /cesta/k/danova-evidence-RRRR-MM-DD.tar.gz
   ```

3. Nastavte vlastníka složek na svého uživatele:

   ```sh
   sudo chown -R $(id -u):$(id -g) data config
   sed -i "s|^APP_UID=.*|APP_UID=$(id -u)|; s|^APP_GID=.*|APP_GID=$(id -g)|" .env
   ```

4. Spusťte aplikaci:

   ```sh
   docker compose up -d
   ```

## Jak ověřit, že to funguje

Přihlaste se původním heslem. Na stránce *Nastavení* jsou vaše firemní údaje a v evidenci
jsou poslední záznamy z doby zálohy.

## Časté problémy

- **Aplikace po obnově chce znovu nastavit heslo:** v záloze chybí `config/auth.json`.
  Zkontrolujte, že jste zálohovali celou složku `config`, včetně skrytých souborů.
- **Po obnově se nelze přihlásit, i když je heslo správné:** chybí `.env` se stejným
  `SECRET_KEY`. Stačí se přihlásit znovu; staré přihlášení přestane platit.
- **`permission denied`:** spusťte krok 3 obnovy.
