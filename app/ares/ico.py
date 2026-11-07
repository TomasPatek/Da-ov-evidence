"""IČO (company identification number) validation."""

from __future__ import annotations

_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def validate_ico(ico: str) -> bool:
    """Check the mod-11 checksum of an IČO (shorter values are zero-padded)."""
    ico = ico.strip()
    if not ico.isdigit() or not ico.isascii() or len(ico) > 8:
        return False
    ico = ico.zfill(8)
    total = sum(int(d) * w for d, w in zip(ico[:7], _WEIGHTS, strict=True))
    check = (11 - total % 11) % 10
    return int(ico[7]) == check


def normalize_ico(ico: str) -> str:
    """Return the canonical 8-digit IČO or raise ValueError."""
    if not validate_ico(ico):
        raise ValueError(f"neplatné IČO: {ico!r}")
    return ico.strip().zfill(8)
