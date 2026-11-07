"""Uploaded files: detect the real type from content, never from the file name."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass


class UploadError(ValueError):
    """The file is not accepted (Czech message)."""


@dataclass(frozen=True)
class FileKind:
    ext: str
    mime: str
    label: str

    @property
    def is_pdf(self) -> bool:
        return self.ext == "pdf"

    @property
    def is_image(self) -> bool:
        return self.ext in ("jpg", "png")

    @property
    def is_isdoc(self) -> bool:
        return self.ext in ("isdoc", "isdocx")


PDF = FileKind("pdf", "application/pdf", "PDF")
JPEG = FileKind("jpg", "image/jpeg", "JPEG")
PNG = FileKind("png", "image/png", "PNG")
ISDOC = FileKind("isdoc", "application/xml", "ISDOC")
ISDOCX = FileKind("isdocx", "application/zip", "ISDOCX")

ACCEPT = ".pdf,.jpg,.jpeg,.png,.isdoc,.isdocx,.xml,application/pdf,image/jpeg,image/png"


def detect(data: bytes) -> FileKind:
    if not data:
        raise UploadError("Soubor je prázdný.")
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    head = data[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<Invoice"):
        if b"isdoc.cz/namespace" in data[:8192]:
            return ISDOC
        raise UploadError("XML soubor není faktura ve formátu ISDOC.")
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.lower().endswith(".isdoc") for n in z.namelist()):
                    return ISDOCX
        except zipfile.BadZipFile:
            pass
    raise UploadError("Nepodporovaný typ souboru. Nahrajte PDF, fotku (JPEG, PNG) nebo ISDOC.")


def isdoc_from_isdocx(data: bytes) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.lower().endswith(".isdoc"):
                info = z.getinfo(name)
                if info.file_size > 5 * 1024 * 1024:
                    return None  # refuse zip bombs
                return z.read(name)
    return None
