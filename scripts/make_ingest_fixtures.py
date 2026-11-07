"""Generate fictional received documents for parser tests (tests/fixtures/doklady).

All companies, IČO and accounts are made up. Two PDF layouts mimic common Czech
invoicing software: labels and values on one line, and a block of labels followed by
a block of values. Run ``python scripts/make_ingest_fixtures.py`` and review the
golden files (``*.json``) it writes before committing.
"""

from __future__ import annotations

import io
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from weasyprint import HTML, Attachment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import FirmaConfig  # noqa: E402
from app.ingest.files import detect  # noqa: E402
from app.ingest.pipeline import read_document  # noqa: E402
from app.ingest.templates import SupplierTemplates  # noqa: E402
from app.invoices.isdoc import build_isdoc  # noqa: E402
from app.invoices.service import InvoiceView  # noqa: E402
from app.invoices.spayd import build_spayd, qr_png, qr_svg  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "doklady"
OWN_ICO = "99999994"  # demo company Jana Vzorová (the customer on these documents)
OWN_ACCOUNT = "1234567899/0100"
STYLE = "body{font-family:'DejaVu Sans';font-size:10pt} td{padding:2px 6px} .r{text-align:right}"

CUSTOMER = """<p>Odběratel: IČO: 99999994<br>Jana Vzorová<br>Ukázková 12<br>54321 Horní Dolní</p>"""

INLINE = f"""
<h2>Díly Vzor s.r.o. &nbsp; FAKTURA - DAŇOVÝ DOKLAD č.:2027000123</h2>
<p>Díly Vzor s.r.o.<br>Průmyslová 5<br>54321 Vzorov<br>IČ: 99990032 DIČ: CZ99990032</p>
{CUSTOMER}
<p>Bankovní spojení: 19-2000145399 / 0800 &nbsp; Variabilní symbol: 2027000123</p>
<p>Forma úhrady: převodem</p>
<p>Datum vystavení: 05.01.2027<br>Datum zd.plnění: 05.01.2027<br>Datum splatnosti: 19.01.2027</p>
<table><tr><td>Topné těleso do trouby 2000W</td><td>1 ks</td><td class=r>1 210,00 Kč</td></tr>
<tr><td>Těsnění dvířek</td><td>2 ks</td><td class=r>145,00 Kč</td></tr></table>
<p>Základní sazba DPH 21 % 1 239,67 Kč 260,33 Kč 1 500,00 Kč</p>
<p><b>Celkem k úhradě 1 500,00 Kč</b></p>
"""

COLUMNS = f"""
<table style="width:100%"><tr><td><b>Faktura - daňový doklad</b></td><td class=r><b>Číslo: 7700451</b></td></tr></table>
<table><tr><td>Dodavatel:</td><td>Spotřebiče Pokus s.r.o.<br>Dílenská 7<br>54321 Vzorov</td></tr></table>
<p>IČO:</p><p>Banka:</p><p>2000145399/0800</p><p>Pokusná banka a.s.</p><p>99990041 DIČ: CZ99990041</p>
<p>Variabilní symbol:</p><p>Objednávka/smlouva:</p><p>660123</p><p>4412;zasilkovna</p>
{CUSTOMER}
<p>Datum vystavení:</p><p>Datum splatnosti:</p><p>Datum zdanitelného plnění:</p><p>Způsob úhrady:</p>
<p>14.02.2027</p><p>14.02.2027</p><p>14.02.2027</p><p>kartou</p>
<table><tr><td>Ohřívač vody 1500W</td><td>1,00</td><td class=r>619,83</td><td>21%</td><td class=r>750,00</td></tr>
<tr><td>Doprava</td><td>1,00</td><td class=r>65,29</td><td>21%</td><td class=r>79,00</td></tr></table>
<p>Celkem 829,00</p>
"""


def qr_page(payload: str) -> str:
    svg = qr_svg(payload).replace("\n", "")
    return f"""
<h2>Faktura 2027-0042</h2>
<p>Servis Ukázka s.r.o., IČO: 99990024, DIČ: CZ99990024</p>
{CUSTOMER}
<p>Datum vystavení: 3. 3. 2027</p>
<p>Celkem k úhradě: 2 420,00 Kč</p>
<p>Zaplaťte pomocí QR kódu:</p><div style="width:40mm">{svg}</div>
"""


def pdf(html: str, **kw: object) -> bytes:
    return HTML(string=f"<style>{STYLE}</style>{html}").write_pdf(**kw)  # type: ignore[no-any-return]


def isdoc_bytes() -> bytes:
    firma = FirmaConfig()
    f = firma.firma
    f.nazev, f.ico, f.dic = "Velkoobchod Vzor a.s.", "99990016", "CZ99990016"
    f.ulice, f.mesto, f.psc = "Skladová 3", "Vzorov", "54321"
    firma.banka.ucet, firma.banka.iban = "19-2000145399/0800", "CZ6508000000192000145399"
    view = InvoiceView(
        invoice={
            "cislo": "VF27-0815",
            "vs": "270815",
            "mena": "CZK",
            "poznamka": "",
            "datum_vystaveni": date(2027, 4, 1),
            "datum_splatnosti": date(2027, 4, 15),
            "castka": Decimal("3630.00"),
        },
        items=[
            {
                "poradi": 1,
                "popis": "Sada filtrů pro myčky",
                "mnozstvi": Decimal("3"),
                "jednotka": "ks",
                "cena_jednotkova": Decimal("1210.00"),
                "celkem": Decimal("3630.00"),
            },
        ],
        customer={
            "nazev": "Jana Vzorová",
            "ico": OWN_ICO,
            "ulice": "Ukázková 12",
            "mesto": "Horní Dolní",
            "psc": "54321",
        },
        job=None,
        firma=firma,
        spayd=None,
    )
    return build_isdoc(view)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    files["faktura-radky.pdf"] = pdf(INLINE)
    files["faktura-sloupce.pdf"] = pdf(COLUMNS)
    payload = build_spayd(
        "CZ6508000000192000145399",
        Decimal("2420"),
        vs="270042",
        message="Faktura 2027-0042",
        due=date(2027, 3, 17),
        recipient="Servis Ukazka",
    )
    files["faktura-qr.pdf"] = pdf(qr_page(payload))
    files["uctenka-qr.png"] = qr_png(payload, scale=6)
    files["faktura.isdoc"] = isdoc_bytes()
    files["faktura-s-isdoc.pdf"] = pdf(
        "<h2>Faktura VF27-0815</h2><p>Velkoobchod Vzor a.s.</p>",
        attachments=[
            Attachment(string=files["faktura.isdoc"].decode(), base_url=None, name="faktura.isdoc")
        ],
    )
    # A scan: the first PDF rendered to an image and wrapped into a PDF without text.
    from app.ingest.qr import pdf_images

    image = pdf_images(files["faktura-radky.pdf"], scale=1.5)[0].convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PDF")
    files["sken.pdf"] = buf.getvalue()

    for name, data in files.items():
        (OUT / name).write_bytes(data)
        ex = read_document(
            data, detect(data), OWN_ICO, OWN_ACCOUNT, SupplierTemplates(OUT / "none"), [], []
        )
        golden = {"values": ex.as_json(), "uncertain": sorted(ex.uncertain), "steps": ex.steps}
        (OUT / f"{name}.json").write_text(
            json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(name, ex.steps)


if __name__ == "__main__":
    main()
