"""ARES (public Czech business register) client.

Uses the public REST API documented at https://ares.gov.cz/swagger-ui/ —
``GET /ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import httpx

from app.ares.ico import normalize_ico

log = logging.getLogger(__name__)

ARES_BASE_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"


class AresUnavailable(Exception):
    """ARES could not be reached or returned an unexpected response."""


@dataclass(frozen=True)
class AresSubjekt:
    ico: str
    nazev: str
    dic: str
    ulice: str
    mesto: str
    psc: str
    datum_aktualizace: date | None


class AresClient(Protocol):
    def lookup(self, ico: str) -> AresSubjekt | None:
        """Return the subject, None if it does not exist; raise AresUnavailable on errors."""
        ...


def _street(sidlo: dict[str, Any]) -> str:
    number = ""
    if sidlo.get("cisloDomovni"):
        number = str(sidlo["cisloDomovni"])
        if sidlo.get("cisloOrientacni"):
            number += f"/{sidlo['cisloOrientacni']}{sidlo.get('cisloOrientacniPismeno', '')}"
    if sidlo.get("nazevUlice"):
        return f"{sidlo['nazevUlice']} {number}".strip()
    place = sidlo.get("nazevCastiObce") or sidlo.get("nazevObce") or ""
    if number:
        prefix = "č.ev." if sidlo.get("typCisloDomovni") == 2 else "č.p."
        return f"{place} {prefix} {number}".strip()
    return str(place)


def _city(sidlo: dict[str, Any]) -> str:
    obec = str(sidlo.get("nazevObce") or "")
    district = str(sidlo.get("nazevMestskehoObvodu") or "")
    # Prague and other statutory cities: "Praha 1" is the usual postal form.
    if obec and district.startswith(obec):
        return district
    return obec


def parse_subject(data: dict[str, Any]) -> AresSubjekt:
    sidlo = data.get("sidlo") or {}
    updated = data.get("datumAktualizace")
    return AresSubjekt(
        ico=str(data["ico"]),
        nazev=" ".join(str(data["obchodniJmeno"]).split()),
        dic=str(data.get("dic") or ""),
        ulice=_street(sidlo),
        mesto=_city(sidlo),
        psc=str(sidlo.get("psc") or ""),
        datum_aktualizace=date.fromisoformat(updated) if updated else None,
    )


class HttpAresClient:
    def __init__(
        self,
        http: httpx.Client | None = None,
        base_url: str = ARES_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._http = http or httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")

    def lookup(self, ico: str) -> AresSubjekt | None:
        ico = normalize_ico(ico)
        url = f"{self._base_url}/ekonomicke-subjekty/{ico}"
        try:
            resp = self._http.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            log.warning("ARES request failed: %s", type(exc).__name__)
            raise AresUnavailable("ARES je nedostupný") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            log.warning("ARES returned HTTP %s", resp.status_code)
            raise AresUnavailable(f"ARES vrátil chybu {resp.status_code}")
        try:
            return parse_subject(resp.json())
        except (ValueError, KeyError, TypeError) as exc:
            raise AresUnavailable("ARES vrátil neočekávanou odpověď") from exc
