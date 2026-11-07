# Instalace na Windows a macOS

## K čemu slouží

Návod spustí Daňovou evidenci na vašem počítači s Windows nebo macOS pomocí Docker Desktop.
Hodí se pro vyzkoušení nebo když nemáte domácí server. Aplikace běží, jen když běží počítač.

## Co je potřeba předem

- Docker Desktop: stáhněte z [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
  a nainstalujte. Po instalaci ho spusťte a počkejte, až ikona velryby ukáže „Docker Desktop is running“.
- Terminál: na Windows *PowerShell*, na macOS aplikace *Terminál*.

## Postup

1. Vytvořte složku pro aplikaci a přejděte do ní.

   Windows (PowerShell):

   ```powershell
   mkdir $HOME\danova-evidence; cd $HOME\danova-evidence
   ```

   macOS:

   ```sh
   mkdir -p ~/danova-evidence && cd ~/danova-evidence
   ```

2. Stáhněte konfigurační soubory.

   Windows (PowerShell):

   ```powershell
   $BASE = "https://raw.githubusercontent.com/TomasPatek/Da-ov-evidence/main"
   Invoke-WebRequest "$BASE/docker-compose.yml" -OutFile docker-compose.yml
   Invoke-WebRequest "$BASE/.env.example" -OutFile .env
   ```

   macOS:

   ```sh
   BASE=https://raw.githubusercontent.com/TomasPatek/Da-ov-evidence/main
   curl -fsSLO $BASE/docker-compose.yml
   curl -fsSL -o .env $BASE/.env.example
   ```

3. Vytvořte složky pro data a konfiguraci:

   ```sh
   mkdir data
   mkdir config
   ```

4. Otevřete soubor `.env` v textovém editoru (Poznámkový blok, TextEdit) a upravte:
   - `SECRET_KEY=` doplňte dlouhý náhodný text, aspoň 40 znaků (např. z generátoru hesel),
   - `COOKIE_SECURE=false` (na vlastním počítači běží aplikace přes `http://`).

   Soubor uložte jako prostý text.

5. Spusťte aplikaci:

   ```sh
   docker compose up -d
   ```

6. Najděte kód pro první spuštění:

   ```sh
   docker compose logs app
   ```

   Hledejte řádek `První spuštění: kód pro nastavení hesla je ...`.

7. Otevřete v prohlížeči <http://localhost:8000>, zadejte kód a projděte průvodce.

## Jak ověřit, že to funguje

V Docker Desktop v sekci *Containers* běží kontejner `app` se stavem *healthy*.
Adresa <http://localhost:8000/zdravi> zobrazí `{"stav":"ok"}`.

## Časté problémy

- **`docker: command not found` nebo `Cannot connect to the Docker daemon`:** Docker Desktop
  neběží. Spusťte ho a počkejte, než se načte.
- **Port 8000 je obsazený:** v `.env` změňte `APP_PORT=8001` a otevřete `http://localhost:8001`.
- **Přihlášení se „neudrží“:** v `.env` chybí `COOKIE_SECURE=false`. Opravte a spusťte
  `docker compose up -d` znovu.
- **Windows: soubor se uložil jako `.env.txt`:** v Průzkumníku zapněte zobrazení přípon
  a soubor přejmenujte na `.env`.
