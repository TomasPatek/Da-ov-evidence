import pytest

from app.ares.ico import normalize_ico, validate_ico
from app.banks.ucet import AccountError, format_iban, parse_cz_account


@pytest.mark.parametrize("ico", ["00006947", "12345679", "25596641", "6947"])
def test_valid_ico(ico: str) -> None:
    assert validate_ico(ico)


@pytest.mark.parametrize("ico", ["00006948", "12345678", "", "abcdefgh", "123456789", "1234 567"])
def test_invalid_ico(ico: str) -> None:
    assert not validate_ico(ico)


def test_normalize_ico_pads_and_strips() -> None:
    assert normalize_ico(" 6947 ") == "00006947"
    with pytest.raises(ValueError):
        normalize_ico("12345678")


def test_ico_checksum_remainder_edge_cases() -> None:
    # remainder 0 -> check digit 1, remainder 1 -> check digit 0
    # 1000000x: weighted sum = 8 -> remainder 8 -> check 3
    assert validate_ico("10000003")
    # 0000011x: 3*1 + 2*1 = 5 -> check 6
    assert validate_ico("00000116")
    # 0000010x: 3 -> check 8 ; 0000001x: 2 -> 9
    assert validate_ico("00000108")
    # sum 11 -> remainder 0 -> check 1 (0000100 + digits): 4*2 + 3*1 = 11
    assert validate_ico("00002101")
    # sum 12 -> remainder 1 -> check 0: 5*2 + 2*1 = 12
    assert validate_ico("00020010")


def test_parse_cz_account_and_iban() -> None:
    acc = parse_cz_account("19-2000145399/0800")
    assert (acc.prefix, acc.number, acc.bank_code) == ("19", "2000145399", "0800")
    assert acc.iban == "CZ6508000000192000145399"
    assert str(acc) == "19-2000145399/0800"
    assert format_iban(acc.iban) == "CZ65 0800 0000 1920 0014 5399"


def test_parse_account_without_prefix_and_with_spaces() -> None:
    acc = parse_cz_account(" 2000145399 / 0800 ")
    assert acc.prefix == ""
    assert str(acc) == "2000145399/0800"
    assert acc.iban.startswith("CZ") and len(acc.iban) == 24


@pytest.mark.parametrize(
    "text",
    [
        "2000145398/0800",
        "19-2000145399",
        "19-2000145399/08",
        "x/0800",
        "12345678901/0800",
        "18-2000145399/0800",
    ],
)
def test_invalid_accounts(text: str) -> None:
    with pytest.raises(AccountError):
        parse_cz_account(text)
