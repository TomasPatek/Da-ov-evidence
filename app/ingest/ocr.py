"""Step 5: OCR of scans and photos with Tesseract (Czech), only when nothing else worked.

Runs the ``tesseract`` program locally; nothing leaves the server. Everything read by OCR
is marked as uncertain for the review form.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

LANGUAGE = "ces"
TIMEOUT_S = 90
MIN_WIDTH = 1600  # small photos are upscaled, Tesseract likes ~300 dpi


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def prepare(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)  # photos from phones carry rotation in EXIF
    image = ImageOps.grayscale(image)
    if image.width < MIN_WIDTH:
        factor = MIN_WIDTH / image.width
        image = image.resize((MIN_WIDTH, int(image.height * factor)), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(image)


def run_tesseract(png: bytes) -> str:
    """Plain text of one image. Replaced in tests."""
    exe = shutil.which("tesseract")
    if exe is None:
        return ""
    result = subprocess.run(  # noqa: S603 - fixed program, image passed on stdin
        [exe, "stdin", "stdout", "-l", LANGUAGE, "--psm", "4"],
        input=png,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        log.info("Tesseract failed with code %d", result.returncode)
        return ""
    return result.stdout.decode("utf-8", "replace")


def ocr_images(images: list[Image.Image]) -> str:
    parts = []
    for image in images:
        buf = io.BytesIO()
        prepare(image).save(buf, format="PNG")
        try:
            parts.append(run_tesseract(buf.getvalue()))
        except (OSError, subprocess.TimeoutExpired):
            log.info("OCR could not run")
    return "\n".join(p for p in parts if p.strip())
