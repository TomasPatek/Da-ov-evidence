# Instalace na server s Linuxem

## K čemu slouží

Návod nainstaluje Daňovou evidenci na domácí server s Linuxem. Aplikace pak běží nepřetržitě
a otevřete ji z počítače i z iPhonu, ale **jen v lokální síti**. Z internetu dostupná není
a nemá být.

## Co je potřeba předem

- Server s Linuxem a nainstalovaným Dockerem s Docker Compose. Ověříte příkazem
  `docker compose version`. Pokud chybí, nainstalujte ho podle
  [docs.docker.com/engine/install](https://docs.docker.com/engine/install/).
- Přístup na server přes terminál (SSH).
- IP adresa serveru v lokální síti (zjistíte příkazem `hostname -I`). Doporučujeme
  serveru v routeru nastavit pevnou IP adresu, aby se neměnila.

## Postup

1. Vytvořte složku pro aplikaci a přejděte do ní:

   ```sh
   mkdir -p ~/danova-evidence && cd ~/danova-evidence
   ```

2. Stáhněte konfigurační soubory:

   ```sh
   BASE=https://raw.githubusercontent.com/TomasPatek/Da-ov-evidence/main
   curl -fsSLO $BASE/docker-compose.yml
   curl -fsSL -o .env $BASE/.env.example
   ```

3. Vytvořte složky pro data a konfiguraci. Musí existovat dřív, než Docker poprvé
   spustí aplikaci, jinak by patřily uživateli root:

   ```sh
   mkdir data config
   ```

4. Vygenerujte tajný klíč a zapište ho do `.env`:

   ```sh
   sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -base64 48)|" .env
   ```

5. Zjistěte své číslo uživatele a skupiny a zapište je do `.env`:

   ```sh
   sed -i "s|^APP_UID=.*|APP_UID=$(id -u)|; s|^APP_GID=.*|APP_GID=$(id -g)|" .env
   ```

6. Spusťte aplikaci:

   ```sh
   docker compose up -d
   ```

7. Najděte kód pro první spuštění:

   ```sh
   docker compose logs app | grep "kód pro nastavení hesla"
   ```

8. Otevřete v prohlížeči `http://<IP-adresa-serveru>:8000`, zadejte kód a projděte průvodce.

### Jak zůstat jen v lokální síti

- **Na routeru nepřesměrovávejte port 8000** (ani jiný port na server) do internetu.
  Zkontrolujte v nastavení routeru sekci *Port forwarding / Přesměrování portů* a *UPnP*.
- Nevystavujte aplikaci přes tunelovací služby ani vzdálený přístup typu „cloud“.
- Pokud je server připojený k více sítím (např. VPN), můžete aplikaci navázat jen na lokální
  adresu: v `.env` nastavte `APP_PORT=<IP-adresa-serveru>:8000` a spusťte znovu
  `docker compose up -d`.

## Jak ověřit, že to funguje

Na serveru:

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/zdravi
```

Služba `app` má stav `healthy` a druhý příkaz vypíše `{"stav":"ok"}`.
Z iPhonu připojeného k domácí Wi-Fi otevřete `http://<IP-adresa-serveru>:8000`: zobrazí se
přihlašovací stránka. Po přepnutí iPhonu na mobilní data se stránka **nesmí** načíst.

## Časté problémy

- **`permission denied` v logu při zápisu do `/data` nebo `/config`:** složky patří jinému
  uživateli. Opravíte příkazem `sudo chown -R $(id -u):$(id -g) data config`.
- **Přihlášení se „neudrží“, stále se vrací přihlašovací stránka:** v `.env` je
  `COOKIE_SECURE=true`. Při přístupu přes `http://` musí být `false`.
- **Kód pro první spuštění není v logu:** heslo už je nastavené. Pokud ho neznáte, smažte
  `config/auth.json` a restartujte aplikaci (`docker compose restart app`).
- **Z jiného zařízení se stránka nenačte:** zkontrolujte, že je zařízení ve stejné síti
  a že firewall serveru povoluje port 8000 (např. `sudo ufw allow from 192.168.0.0/16 to any port 8000`,
  rozsah upravte podle své sítě).
