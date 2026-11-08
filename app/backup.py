"""Nightly encrypted backup of /data and /config with restic (any rclone remote).

Settings come from .env: ``BACKUP_REPOSITORY`` (e.g. ``rclone:zaloha:danova-evidence``
or a local path) and ``RESTIC_PASSWORD``. The rclone configuration lives in
``/config/rclone/rclone.conf``. The password is never logged or stored in /data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.storage.atomic import atomic_write_text, file_lock

log = logging.getLogger(__name__)

STATE_FILE = "zaloha.json"
TIMEOUT_S = 6 * 3600
# restic forget: how many snapshots to keep.
RETENTION = (
    "--keep-daily",
    "7",
    "--keep-weekly",
    "5",
    "--keep-monthly",
    "12",
    "--keep-yearly",
    "10",
)


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], dict[str, str]], CommandResult]


def run_command(args: Sequence[str], env: dict[str, str]) -> CommandResult:
    exe = shutil.which(args[0])
    if exe is None:
        return CommandResult(127, "", f"{args[0]} není nainstalovaný")
    proc = subprocess.run(  # noqa: S603 - fixed programs, no shell
        [exe, *args[1:]], env=env, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def configured(settings: Settings) -> bool:
    return bool(settings.backup_repository and settings.restic_password)


@dataclass
class BackupResult:
    started: str
    ok: bool = False
    snapshot: str = ""
    message: str = ""
    files: int = 0
    added_bytes: int = 0
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cas": self.started,
            "ok": self.ok,
            "snapshot": self.snapshot,
            "zprava": self.message,
            "souboru": self.files,
            "pridano_bajtu": self.added_bytes,
        }


class Backup:
    def __init__(self, settings: Settings, runner: Runner = run_command) -> None:
        self.s = settings
        self.run = runner
        self.state_path = settings.data_dir / STATE_FILE

    def env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            # The container has a private, writable /tmp only (read-only root filesystem).
            "HOME": tempfile.gettempdir(),
            "RESTIC_REPOSITORY": self.s.backup_repository,
            "RESTIC_PASSWORD": self.s.restic_password,
            "RESTIC_CACHE_DIR": str(Path(tempfile.gettempdir()) / "restic-cache"),
            "RCLONE_CONFIG": str(self.s.config_dir / "rclone" / "rclone.conf"),
        }
        return env

    def state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _fail(self, result: BackupResult, step: str, cmd: CommandResult) -> BackupResult:
        # Only the first line of restic's message: it never contains the password.
        first = (cmd.stderr or cmd.stdout).strip().splitlines()[:1]
        result.message = f"{step} selhalo: {first[0] if first else 'kód ' + str(cmd.returncode)}"
        log.warning("Backup failed at %s (exit code %d)", step, cmd.returncode)
        return result

    def backup(self) -> BackupResult:
        result = BackupResult(started=datetime.now().astimezone().isoformat(timespec="seconds"))
        if not configured(self.s):
            result.message = "Záloha není nastavená (BACKUP_REPOSITORY a RESTIC_PASSWORD v .env)."
            return result
        self.s.data_dir.mkdir(parents=True, exist_ok=True)
        with file_lock(self.s.data_dir / "zaloha"):
            env = self.env()
            check = self.run(["restic", "cat", "config"], env)
            if check.returncode != 0:
                init = self.run(["restic", "init"], env)
                result.steps.append("init")
                if init.returncode != 0:
                    return self._save(
                        self._fail(
                            result, "Založení úložiště", check if init.returncode == 127 else init
                        )
                    )
            cmd = self.run(
                [
                    "restic",
                    "backup",
                    "--json",
                    "--tag",
                    "danova-evidence",
                    "--exclude",
                    "*.lock",
                    str(self.s.data_dir),
                    str(self.s.config_dir),
                ],
                env,
            )
            result.steps.append("backup")
            if cmd.returncode != 0:
                return self._save(self._fail(result, "Záloha", cmd))
            for line in cmd.stdout.splitlines():
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("message_type") == "summary":
                    result.snapshot = str(msg.get("snapshot_id", ""))[:8]
                    result.files = int(msg.get("total_files_processed", 0))
                    result.added_bytes = int(msg.get("data_added", 0))
            forget = self.run(
                ["restic", "forget", "--prune", "--tag", "danova-evidence", *RETENTION], env
            )
            result.steps.append("forget")
            if forget.returncode != 0:
                return self._save(self._fail(result, "Promazání starých záloh", forget))
            result.ok = True
            result.message = "Záloha proběhla."
        log.info("Backup finished, snapshot %s", result.snapshot or "?")
        return self._save(result)

    def _save(self, result: BackupResult) -> BackupResult:
        atomic_write_text(
            self.state_path,
            json.dumps({"posledni": result.as_dict()}, ensure_ascii=False, indent=1) + "\n",
        )
        return result

    def snapshots(self) -> list[dict[str, Any]]:
        if not configured(self.s):
            return []
        cmd = self.run(["restic", "snapshots", "--json", "--tag", "danova-evidence"], self.env())
        if cmd.returncode != 0:
            return []
        try:
            data = json.loads(cmd.stdout or "[]")
        except json.JSONDecodeError:
            return []
        return [
            {"id": str(s.get("short_id", "")), "cas": _local_time(str(s.get("time", "")))}
            for s in reversed(data)
        ]


def _local_time(text: str) -> str:
    """restic reports times with an offset (often UTC); show them in local time."""
    try:
        # restic prints nanoseconds; Python accepts at most microseconds.
        moment = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00"))
    except ValueError:
        return text[:19].replace("T", " ")
    if moment.tzinfo is not None:
        moment = moment.astimezone(ZoneInfo("Europe/Prague"))
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def restore_into(
    settings: Settings, runner: Runner = run_command, snapshot: str = "latest"
) -> CommandResult:
    """Restore a snapshot into the data and config folders of ``settings``.

    This is the procedure of docs/zalohovani.md:
    ``docker compose run --rm app python -m app.backup obnovit``.
    """
    with tempfile.TemporaryDirectory(prefix="obnova-") as tmp:
        result = runner(
            ["restic", "restore", snapshot, "--target", tmp], Backup(settings, runner).env()
        )
        if result.returncode != 0:
            return result
        restored = Path(tmp)
        for folder in (settings.data_dir, settings.config_dir):
            source = restored / folder.relative_to(folder.anchor)
            if source.is_dir():
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, folder, dirs_exist_ok=True)
    return result


def main(argv: Sequence[str]) -> int:
    """``python -m app.backup [zalohovat|obnovit [snapshot]]``"""
    settings = Settings.from_env()
    if not configured(settings):
        print("Záloha není nastavená: doplňte BACKUP_REPOSITORY a RESTIC_PASSWORD v .env.")
        return 2
    if argv and argv[0] == "obnovit":
        snapshot = argv[1] if len(argv) > 1 else "latest"
        result = restore_into(settings, snapshot=snapshot)
        if result.returncode != 0:
            print("Obnova selhala:", (result.stderr or result.stdout).strip().splitlines()[:1])
            return 1
        print(f"Obnoveno ze zálohy {snapshot} do {settings.data_dir} a {settings.config_dir}.")
        return 0
    backup = Backup(settings).backup()
    print(backup.message)
    return 0 if backup.ok else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
