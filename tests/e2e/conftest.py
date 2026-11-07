from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from demo import prepare, serve

IPHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1280, "height": 800}}


@pytest.fixture
def demo_url(tmp_path: Path) -> Iterator[str]:
    with serve(prepare(tmp_path)) as url:
        yield url


@pytest.fixture
def fresh_url(tmp_path: Path) -> Iterator[str]:
    with serve(prepare(tmp_path, configured=False)) as url:
        yield url


@pytest.fixture(params=["desktop", "iphone"])
def browser_context_args(
    request: pytest.FixtureRequest, browser_context_args: dict[str, object]
) -> dict[str, object]:
    device = DESKTOP if request.param == "desktop" else IPHONE
    return {**browser_context_args, **device}
