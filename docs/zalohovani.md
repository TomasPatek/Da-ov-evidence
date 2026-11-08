# Zálohování a obnova

## K čemu slouží

Všechna data aplikace jsou ve dvou složkách: `data` (evidence, doklady, audit) a `config`
(nastavení, heslo, logo). Aplikace je každou noc zašifruje a uloží do cloudu nebo do jiné
složky (program [restic](https://restic.net), cloud přes [rclone](https://rclone.org)).
Ze zálohy obnovíte celou evidenci na jiném počítači.

## Co je potřeba předem

- Běžící aplikace podle [instalace na server](instalace-server.md).
- Účet v cloudu, který rclone podporuje (např. Google Drive, OneDrive, Backblaze B2),
  nebo jiné místo mimo server (NAS, externí disk).
- Správce hesel (nebo jiné bezpečné místo mimo server) pro heslo zálohy.

## Postup

### 1. Nastavte rclone (jen pro cloud)

1. Na serveru spusťte průvodce rclone uvnitř aplikace:

   ```sh
   cd ~/danova-evidence
   mkdir -p config/rclone
   docker compose run --rm --entrypoint rclone app config
   ```

2. Zvolte `n` (nové úložiště), jméno zadejte `zaloha` a vyberte poskytovatele.
   U Google Drive a OneDrive se průvodce zeptá na přihlášení v prohlížeči; na serveru bez
   prohlížeče zvolte „No“ u automatické konfigurace a podle pokynů spusťte
   `rclone authorize` na počítači s prohlížečem.
3. Ověřte připojení:

   ```sh
   docker compose run --rm --entrypoint rclone app lsd zaloha:
   ```

### 2. Doplňte `.env` a restartujte aplikaci

```sh
BACKUP_REPOSITORY=rclone:zaloha:danova-evidence
RESTIC_PASSWORD=dlouhe-nahodne-heslo
BACKUP_TIME=02:30
```

Heslo vygenerujete např. `openssl rand -base64 32`. **Uložte ho i mimo server.** Bez něj
zálohu nikdo neobnoví a aplikace ho za vás nezná.

Místo cloudu můžete zálohovat do složky (NAS připojený na serveru, externí disk): přidejte
ji do `docker-compose.yml` jako svazek (např. `- /mnt/nas/zaloha:/zaloha`) a nastavte
`BACKUP_REPOSITORY=/zaloha`.

Pak spusťte `docker compose up -d`.

### 3. Vyzkoušejte zálohu

V aplikaci otevřete *Nastavení → Noční záloha* a klikněte na *Zálohovat teď*. První záloha
založí úložiště a může trvat déle. Pak se zálohuje každou noc v nastavený čas.
Uchovává se 7 denních, 5 týdenních, 12 měsíčních a 10 ročních záloh.

### Obnova na čistém stroji

1. Nainstalujte Docker a Git podle [instalace na server](instalace-server.md), část „Co je potřeba předem“.
2. Stáhněte aplikaci a vytvořte prázdné složky:

   ```sh
   git clone https://github.com/TomasPatek/Da-ov-evidence.git ~/danova-evidence
   cd ~/danova-evidence
   mkdir -p data config/rclone
   ```

3. Vytvořte `.env` podle `.env.example` se stejnými hodnotami `BACKUP_REPOSITORY`
   a `RESTIC_PASSWORD` jako na původním serveru. U cloudu nastavte rclone stejně jako v kroku 1.
4. Sestavte aplikaci a obnovte poslední zálohu:

   ```sh
   docker compose build
   docker compose run --rm app python -m app.backup obnovit
   ```

   Starší zálohu obnovíte, když za `obnovit` napíšete její číslo ze seznamu
   (*Nastavení → Noční záloha → Zobrazit uložené zálohy*).
5. Spusťte aplikaci:

   ```sh
   docker compose up -d
   ```

Postup zálohy a obnovy ověřuje automatický test `test_restore_on_a_clean_machine`.
Zálohu lze spustit i ručně: `docker compose exec app python -m app.backup`.

### Ruční záloha (bez restic)

Kdykoli můžete také zabalit složky ručně:

```sh
cd ~/danova-evidence
docker compose stop app
tar czf danova-evidence-$(date +%F).tar.gz data config .env
docker compose start app
```

Archiv obsahuje citlivé údaje, ukládejte ho na místo, kam nemá přístup nikdo cizí.

## Jak ověřit, že to funguje

- *Nastavení → Noční záloha* ukazuje u poslední zálohy „Záloha proběhla.“ a dnešní datum.
- Po obnově se přihlásíte původním heslem, v *Nastavení* jsou vaše údaje a v evidenci jsou
  poslední záznamy z doby zálohy.

## Časté problémy

- **„Záloha není nastavená“:** v `.env` chybí `BACKUP_REPOSITORY` nebo `RESTIC_PASSWORD`,
  nebo aplikace po úpravě `.env` nebyla restartována (`docker compose up -d`).
- **„Záloha selhalo: … unable to open repository“:** rclone nemá konfiguraci nebo vypršelo
  přihlášení do cloudu. Spusťte znovu `rclone config` (krok 1).
- **„wrong password or no key found“:** `RESTIC_PASSWORD` se liší od hesla, se kterým bylo
  úložiště založeno.
- **Aplikace po obnově chce znovu nastavit heslo:** v obnovených datech chybí `config/auth.json`.
- **Po obnově se nelze přihlásit, i když je heslo správné:** chybí `SECRET_KEY` v `.env` nebo
  `config/.secret_key`; přihlaste se znovu, staré relace neplatí.
