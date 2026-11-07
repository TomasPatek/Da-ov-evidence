"""Czech bank account numbers (předčíslí-číslo/kód banky) and IBAN conversion."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ACCOUNT_RE = re.compile(r"^(?:(\d{1,6})-)?(\d{2,10})/(\d{4})$")
_PREFIX_WEIGHTS = (10, 5, 8, 4, 2, 1)
_NUMBER_WEIGHTS = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)


class AccountError(ValueError):
    pass


def _mod11_ok(digits: str, weights: tuple[int, ...]) -> bool:
    padded = digits.zfill(len(weights))
    return sum(int(d) * w for d, w in zip(padded, weights, strict=True)) % 11 == 0


def iban_check_digits(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return f"{98 - int(numeric) % 97:02d}"


def iban_is_valid(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    numeric = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return int(numeric) % 97 == 1


def format_iban(iban: str) -> str:
    iban = iban.replace(" ", "")
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


@dataclass(frozen=True)
class CzAccount:
    prefix: str
    number: str
    bank_code: str

    @property
    def iban(self) -> str:
        bban = self.bank_code + self.prefix.zfill(6) + self.number.zfill(10)
        return f"CZ{iban_check_digits('CZ', bban)}{bban}"

    def __str__(self) -> str:
        base = f"{self.number}/{self.bank_code}"
        return f"{self.prefix}-{base}" if self.prefix else base


def parse_cz_account(text: str) -> CzAccount:
    cleaned = re.sub(r"\s+", "", text)
    m = _ACCOUNT_RE.match(cleaned)
    if not m:
        raise AccountError("Číslo účtu zadejte ve tvaru [předčíslí-]číslo/kód banky.")
    prefix, number, bank = (m.group(1) or "").lstrip("0"), m.group(2).lstrip("0"), m.group(3)
    if prefix and not _mod11_ok(prefix, _PREFIX_WEIGHTS):
        raise AccountError("Předčíslí účtu nemá platný kontrolní součet.")
    if not number or not _mod11_ok(number, _NUMBER_WEIGHTS):
        raise AccountError("Číslo účtu nemá platný kontrolní součet.")
    return CzAccount(prefix=prefix, number=number, bank_code=bank)
