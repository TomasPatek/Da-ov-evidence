import json
from pathlib import Path

import httpx
import pytest

from app.ares.client import AresUnavailable, HttpAresClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ares"


def client_for(handler: object) -> HttpAresClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return HttpAresClient(http=httpx.Client(transport=transport))


def fixture_response(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_lookup_parses_subject() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return fixture_response("00006947.json")

    subj = client_for(handler).lookup("6947")
    assert seen == [
        "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/00006947"
    ]
    assert subj is not None
    assert subj.ico == "00006947"
    assert subj.nazev == "Ministerstvo financí"
    assert subj.dic == "CZ00006947"
    assert subj.ulice == "Letenská 525/15"
    assert subj.mesto == "Praha 1"
    assert subj.psc == "11800"
    assert subj.datum_aktualizace is not None


def test_lookup_without_street_uses_part_of_village() -> None:
    subj = client_for(lambda r: fixture_response("bez-ulice.json")).lookup("99999994")
    assert subj is not None
    assert subj.ulice == "Horní Dolní č.p. 42"
    assert subj.mesto == "Horní Dolní"
    assert subj.dic == ""


def test_not_found_returns_none() -> None:
    assert client_for(lambda r: fixture_response("nenalezeno.json", 404)).lookup("99999994") is None


def test_invalid_ico_is_rejected_before_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    with pytest.raises(ValueError):
        client_for(handler).lookup("12345678")


@pytest.mark.parametrize("status", [500, 503])
def test_server_error_raises_unavailable(status: int) -> None:
    with pytest.raises(AresUnavailable):
        client_for(lambda r: httpx.Response(status)).lookup("00006947")


def test_network_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(AresUnavailable):
        client_for(handler).lookup("00006947")


def test_garbage_json_raises_unavailable() -> None:
    with pytest.raises(AresUnavailable):
        client_for(lambda r: httpx.Response(200, text="<html>")).lookup("00006947")


@pytest.mark.live
def test_live_lookup() -> None:
    subj = HttpAresClient().lookup("00006947")
    assert subj is not None and subj.nazev == "Ministerstvo financí"
