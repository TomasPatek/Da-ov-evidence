# Instalace na Windows a macOS

## K čemu slouží

Návod spustí Daňovou evidenci na vašem počítači s Windows nebo macOS pomocí Docker Desktop.
Hodí se pro vyzkoušení nebo když nemáte domácí server. Aplikace běží, jen když běží počítač.

## Co je potřeba předem

- Docker Desktop: stáhněte z [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
  a nainstalujte. Po instalaci ho spusťte a počkejte, až ikona velryby ukáže „Docker Desktop is running“.
- Terminál: na Windows *PowerShell*, na macOS aplikace *Terminál*.

## Postup

1. Stáhněte aplikaci jako ZIP, rozbalte ji do složky `danova-evidence` ve své domovské
   složce a přejděte do ní.

   Windows (PowerShell):

   ```powershell
   cd $HOME
   Invoke-WebRequest "https://github.com/TomasPatek/Da-ov-evidence/archive/refs/heads/main.zip" -OutFile danova-evidence.zip
   Expand-Archive danova-evidence.zip -DestinationPath .
   Rename-Item Da-ov-evidence-main danova-evidence
   Remove-Item danova-evidence.zip
   cd danova-evidence
   ```

   macOS:

   ```sh
   cd ~
   curl -fsSL -o danova-evidence.zip https://github.com/TomasPatek/Da-ov-evidence/archive/refs/heads/main.zip
   unzip -q danova-evidence.zip && mv Da-ov-evidence-main danova-evidence && rm danova-evidence.zip
   cd danova-evidence
   ```

2. Vytvořte soubor s nastavením ze vzoru.

   Windows (PowerShell):

   ```powershell
   Copy-Item .env.example .env
   ```

   macOS:

   ```sh
   cp .env.example .env
   ```

3. Vytvořte složky pro data a konfiguraci:

   ```sh
   mkdir data
   mkdir config
   ```

4. Otevřete soubor `.env` v textovém editoru (Poznámkový blok, TextEdit) a za `SECRET_KEY=`
   doplňte dlouhý náhodný text, aspoň 40 znaků (např. z generátoru hesel). Soubor uložte
   jako prostý text.

5. Sestavte a spusťte aplikaci. Poprvé to trvá několik minut:

   ```sh
   docker compose up -d --build
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

- **`failed to read dockerfile: open Dockerfile: no such file or directory`:** ve složce
  chybí zdrojové kódy. Postupujte od kroku 1 a stáhněte celý ZIP.

- **`docker: command not found` nebo `Cannot connect to the Docker daemon`:** Docker Desktop
  neběží. Spusťte ho a počkejte, než se načte.
- **Port 8000 je obsazený:** v `.env` změňte `APP_PORT=8001` a otevřete `http://localhost:8001`.
- **Přihlášení se „neudrží“:** v `.env` je `COOKIE_SECURE=true`. Nastavte `false` a spusťte
  `docker compose up -d` znovu.
- **Windows: soubor se uložil jako `.env.txt`:** v Průzkumníku zapněte zobrazení přípon
  a soubor přejmenujte na `.env`.
