"""Run the app with demo data of a fictional company.

Used by E2E tests and the screenshot script; can also be run by hand:
``python scripts/demo.py /tmp/demo`` then open http://127.0.0.1:8765 (heslo: demo-heslo-1234).
"""

from __future__ import annotations

import shutil
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth import PasswordStore  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

DEMO_DIR = ROOT / "scripts" / "demo-data"
DEMO_PASSWORD = "demo-heslo-1234"
DEMO_SETUP_TOKEN = "DEMO0001"


def prepare(target: Path, configured: bool = True) -> Settings:
    """Copy demo config into ``target``; ``configured=False`` gives a fresh install."""
    config, data = target / "config", target / "data"
    if configured:
        shutil.copytree(DEMO_DIR / "config", config, dirs_exist_ok=True)
        PasswordStore(config / "auth.json").set_password(DEMO_PASSWORD)
    data.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data,
        config_dir=config,
        secret_key="demo-secret-key-not-for-production",
        cookie_secure=False,
        setup_token=DEMO_SETUP_TOKEN,
        log_level="WARNING",
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def serve(settings: Settings, port: int | None = None) -> Iterator[str]:
    """Run the app in a background thread; yields the base URL."""
    port = port or free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-run")
    with serve(prepare(target), port=8765) as url:
        print(f"Demo běží na {url}, heslo: {DEMO_PASSWORD}. Ukončete Ctrl+C.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
