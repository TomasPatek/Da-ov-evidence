# Instalace na server s Linuxem

## K čemu slouží

Návod nainstaluje Daňovou evidenci na domácí server s Linuxem (např. vedle Home Assistant).
Aplikace pak běží nepřetržitě a otevřete ji z počítače i z iPhonu v lokální síti.
Volitelně nastavíte vlastní adresu s HTTPS, např. `https://ucetnictvi.example.cz`.

## Co je potřeba předem

- Server s Linuxem a nainstalovaným Dockerem s Docker Compose. Ověříte příkazem
  `docker compose version`. Pokud chybí, nainstalujte ho podle
  [docs.docker.com/engine/install](https://docs.docker.com/engine/install/).
- Přístup na server přes terminál (SSH).
- Pro HTTPS navíc: vlastní doména u poskytovatele DNS s API (např. Cloudflare),
  lokální DNS server (např. Pi-hole) a API token k DNS.

## Postup

### Základní instalace

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

6. Pokud **nebudete** používat HTTPS proxy (krok níže), nastavte v `.env`
   `COOKIE_SECURE=false`. Jinak se přes `http://` nepřihlásíte.

7. Spusťte aplikaci:

   ```sh
   docker compose up -d
   ```

8. Najděte kód pro první spuštění:

   ```sh
   docker compose logs app | grep "kód pro nastavení hesla"
   ```

9. Otevřete v prohlížeči `http://<adresa-serveru>:8000`, zadejte kód a projděte průvodce.

### HTTPS s vlastní doménou (volitelné)

Certifikát Let's Encrypt se získá ověřením přes DNS, takže server nemusí být dostupný z internetu.

1. U poskytovatele DNS vytvořte API token s právem upravovat záznamy domény.
2. V `.env` vyplňte:

   ```sh
   DOMAIN=ucetnictvi.example.cz
   ACME_EMAIL=vas@email.cz
   DNS_PROVIDER=cloudflare
   DNS_API_TOKEN=<token>
   COOKIE_SECURE=true
   FORWARDED_ALLOW_IPS=*
   ```

   `DNS_PROVIDER` je název modulu z [github.com/caddy-dns](https://github.com/caddy-dns).
   Návod předpokládá poskytovatele, kterému stačí jeden token (např. Cloudflare). Jiní mohou
   potřebovat upravit řádek `dns` v souboru `proxy/Caddyfile`.
3. Stáhněte soubory proxy:

   ```sh
   mkdir -p proxy
   curl -fsSL -o proxy/Dockerfile $BASE/proxy/Dockerfile
   curl -fsSL -o proxy/Caddyfile $BASE/proxy/Caddyfile
   ```

4. V lokálním DNS (Pi-hole: *Local DNS → DNS Records*) nasměrujte doménu na IP adresu serveru.
5. Spusťte aplikaci i proxy:

   ```sh
   docker compose --profile proxy up -d
   ```

6. Aby aplikace nebyla dostupná i bez HTTPS, v `.env` nastavte `APP_PORT=127.0.0.1:8000`
   a spusťte znovu příkaz z bodu 5.

## Jak ověřit, že to funguje

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/zdravi
```

Služba `app` má stav `healthy` a druhý příkaz vypíše `{"stav":"ok"}`.
S proxy otevřete `https://<vaše-doména>`: prohlížeč neukazuje varování o certifikátu.

## Časté problémy

- **`permission denied` v logu při zápisu do `/data` nebo `/config`:** složky patří jinému
  uživateli. Opravíte příkazem `sudo chown -R $(id -u):$(id -g) data config`.
- **Přihlášení se „neudrží“, stále se vrací přihlašovací stránka:** používáte `http://`
  a v `.env` je `COOKIE_SECURE=true`. Nastavte `false`, nebo použijte HTTPS proxy.
- **Kód pro první spuštění není v logu:** heslo už je nastavené. Pokud ho neznáte, smažte
  `config/auth.json` a restartujte aplikaci (`docker compose restart app`).
- **Caddy nezíská certifikát:** zkontrolujte `docker compose logs caddy`. Nejčastěji je
  chybný `DNS_API_TOKEN` nebo token nemá právo upravovat DNS záznamy.
- **Doména nefunguje z iPhonu:** iPhone musí používat lokální DNS (Pi-hole). Zkontrolujte
  nastavení DNS v routeru nebo Wi-Fi.
