"""Nightly backup: restic commands, first-time init, status, no secrets; real round trip."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from app.backup import Backup, CommandResult, configured, restore_into
from app.config import Settings

SECRET = "velmi-tajne-heslo-zalohy"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "data" / "2027").mkdir(parents=True)
    (tmp_path / "data" / "2027" / "denik.csv").write_text(
        "id;castka\r\nD2027-0001;10,00\r\n", "utf-8"
    )
    (tmp_path / "data" / "2027" / ".denik.csv.lock").write_text("", "utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "firma.toml").write_text('[firma]\nnazev = "Jana"\n', "utf-8")
    return Settings(
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        secret_key="k",
        backup_repository=str(tmp_path / "repo"),
        restic_password=SECRET,
    )


class FakeRestic:
    def __init__(self, initialized: bool = True, fail: str = "") -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.initialized = initialized
        self.fail = fail

    def __call__(self, args: Sequence[str], env: dict[str, str]) -> CommandResult:
        self.calls.append((list(args), env))
        sub = args[1]
        if sub == self.fail:
            return CommandResult(
                1, "", f"Fatal: unable to open repository at {env['RESTIC_REPOSITORY']}\nmore"
            )
        if sub == "cat":
            return CommandResult(0 if self.initialized else 1)
        if sub == "backup":
            summary = {
                "message_type": "summary",
                "snapshot_id": "abcdef1234567890",
                "total_files_processed": 3,
                "data_added": 2048,
            }
            return CommandResult(0, '{"message_type":"status"}\n' + json.dumps(summary) + "\n")
        if sub == "snapshots":
            return CommandResult(
                0, json.dumps([{"short_id": "abcdef12", "time": "2027-01-02T01:30:01.123456789Z"}])
            )
        return CommandResult(0)


def test_backup_runs_restic_with_env(settings: Settings) -> None:
    fake = FakeRestic()
    result = Backup(settings, fake).backup()
    assert result.ok and result.snapshot == "abcdef12" and result.files == 3
    commands = [c[0][1] for c in fake.calls]
    assert commands == ["cat", "backup", "forget"]
    backup_args, env = fake.calls[1]
    assert str(settings.data_dir) in backup_args and str(settings.config_dir) in backup_args
    assert "*.lock" in backup_args
    assert env["RESTIC_PASSWORD"] == SECRET
    assert env["RCLONE_CONFIG"].endswith("config/rclone/rclone.conf")
    forget = fake.calls[2][0]
    assert "--prune" in forget and "--keep-daily" in forget
    state = Backup(settings, fake).state()["posledni"]
    assert state["ok"] and state["snapshot"] == "abcdef12"
    assert SECRET not in json.dumps(state)


def test_first_backup_initialises_repository(settings: Settings) -> None:
    fake = FakeRestic(initialized=False)
    assert Backup(settings, fake).backup().ok
    assert [c[0][1] for c in fake.calls] == ["cat", "init", "backup", "forget"]


def test_failure_is_reported_without_secrets(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    result = Backup(settings, FakeRestic(fail="backup")).backup()
    assert not result.ok
    assert result.message.startswith("Záloha selhalo: Fatal: unable to open repository")
    assert SECRET not in result.message and SECRET not in caplog.text


def test_not_configured(settings: Settings) -> None:
    empty = replace(settings, backup_repository="", restic_password="")
    assert not configured(empty)
    assert "není nastavená" in Backup(empty, FakeRestic()).backup().message
    assert Backup(empty, FakeRestic()).snapshots() == []


def test_snapshots_list(settings: Settings) -> None:
    assert Backup(settings, FakeRestic()).snapshots() == [
        {"id": "abcdef12", "cas": "2027-01-02 02:30:01"}
    ]


def test_password_not_in_settings_repr(settings: Settings) -> None:
    assert SECRET not in repr(settings)


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic not installed")
def test_restore_on_a_clean_machine(settings: Settings, tmp_path: Path) -> None:
    """The procedure from docs/zalohovani.md: back up, lose everything, restore."""
    assert Backup(settings).backup().ok
    original = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in (tmp_path / "data").rglob("*")
        if p.is_file() and not p.name.endswith(".lock") and p.name != "zaloha.json"
    }
    original[Path("config/firma.toml")] = (tmp_path / "config" / "firma.toml").read_bytes()
    # A clean machine: empty data and config folders, same repository and password.
    clean = replace(
        settings, data_dir=tmp_path / "novy" / "data", config_dir=tmp_path / "novy" / "config"
    )
    restored = replace(clean, data_dir=settings.data_dir, config_dir=settings.config_dir)
    shutil.rmtree(settings.data_dir)
    shutil.rmtree(settings.config_dir)
    assert restore_into(restored).returncode == 0
    for rel, content in original.items():
        assert (tmp_path / rel).read_bytes() == content, rel
    assert not list((tmp_path / "data").rglob("*.lock"))
    assert clean.data_dir != settings.data_dir


def test_restore_copies_into_folders_with_fake(settings: Settings, tmp_path: Path) -> None:
    def fake(args: Sequence[str], env: dict[str, str]) -> CommandResult:
        target = Path(args[args.index("--target") + 1])
        restored = target / settings.data_dir.relative_to("/") / "2027"
        restored.mkdir(parents=True)
        (restored / "denik.csv").write_text("obnoveno", "utf-8")
        return CommandResult(0)

    assert restore_into(settings, fake).returncode == 0
    assert (settings.data_dir / "2027" / "denik.csv").read_text("utf-8") == "obnoveno"
