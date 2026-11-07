"""ISDOC 6.0.2 export of an issued invoice (Czech e-invoice XML standard).

The invoice is issued by a non-VAT payer: ``VATApplicable`` is false and all tax
amounts are zero. The UUID is derived from the supplier IČO and the invoice number
so re-exporting the same invoice always yields the same document identity.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

from app import __version__
from app.banks.ucet import AccountError, parse_cz_account
from app.invoices.service import InvoiceView
from app.money import ZERO, format_csv_decimal

NS = "http://isdoc.cz/namespace/2013"
VERSION = "6.0.2"
_UUID_NAMESPACE = uuid.UUID("6f1c3a52-6a39-4f55-9d0e-6a0b4c7d2e11")


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _qty(value: Decimal) -> str:
    return format_csv_decimal(value).replace(",", ".")


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{NS}}}{tag}", attrs)
    if text is not None:
        el.text = text
    return el


def document_uuid(supplier_ico: str, cislo: str) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, f"{supplier_ico}/{cislo}")).upper()


def _party(
    parent: ET.Element,
    tag: str,
    ico: str,
    dic: str,
    name: str,
    street: str,
    city: str,
    zip_code: str,
    email: str = "",
    phone: str = "",
) -> None:
    party = _sub(_sub(parent, tag), "Party")
    ident = _sub(party, "PartyIdentification")
    _sub(ident, "ID", ico)
    _sub(_sub(party, "PartyName"), "Name", name)
    addr = _sub(party, "PostalAddress")
    _sub(addr, "StreetName", street)
    _sub(addr, "BuildingNumber", "")
    _sub(addr, "CityName", city)
    _sub(addr, "PostalZone", zip_code.replace(" ", ""))
    country = _sub(addr, "Country")
    _sub(country, "IdentificationCode", "CZ")
    _sub(country, "Name", "Česká republika")
    if dic:
        scheme = _sub(party, "PartyTaxScheme")
        _sub(scheme, "CompanyID", dic)
        _sub(scheme, "TaxScheme", "VAT")
    if email or phone:
        contact = _sub(party, "Contact")
        if phone:
            _sub(contact, "Telephone", phone)
        if email:
            _sub(contact, "ElectronicMail", email)


def build_isdoc(view: InvoiceView) -> bytes:
    inv, firma = view.invoice, view.firma
    total: Decimal = inv["castka"]
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Invoice", {"version": VERSION})
    _sub(root, "DocumentType", "1")  # 1 = invoice
    _sub(root, "ID", inv["cislo"])
    _sub(root, "UUID", document_uuid(firma.firma.ico, inv["cislo"]))
    _sub(root, "IssuingSystem", f"Daňová evidence {__version__}")
    _sub(root, "IssueDate", inv["datum_vystaveni"].isoformat())
    _sub(root, "VATApplicable", "false")
    _sub(root, "ElectronicPossibilityAgreementReference", "")
    note = " ".join(t for t in (firma.fakturace.text_dph, inv["poznamka"]) if t)
    if note:
        _sub(root, "Note", note)
    _sub(root, "LocalCurrencyCode", inv["mena"])
    _sub(root, "CurrRate", "1")
    _sub(root, "RefCurrRate", "1")

    f = firma.firma
    _party(
        root,
        "AccountingSupplierParty",
        f.ico,
        f.dic,
        f.nazev,
        f.ulice,
        f.mesto,
        f.psc,
        f.email,
        f.telefon,
    )
    c = view.customer
    _party(
        root,
        "AccountingCustomerParty",
        c.get("ico", ""),
        c.get("dic", ""),
        c.get("nazev", ""),
        c.get("ulice", ""),
        c.get("mesto", ""),
        c.get("psc", ""),
        c.get("email", ""),
        c.get("telefon", ""),
    )

    lines = _sub(root, "InvoiceLines")
    for item in view.items:
        line = _sub(lines, "InvoiceLine")
        _sub(line, "ID", str(item["poradi"]))
        qty = _sub(line, "InvoicedQuantity", _qty(item["mnozstvi"]))
        if item["jednotka"]:
            qty.set("unitCode", item["jednotka"])
        _sub(line, "LineExtensionAmount", _amount(item["celkem"]))
        _sub(line, "LineExtensionAmountTaxInclusive", _amount(item["celkem"]))
        _sub(line, "LineExtensionTaxAmount", _amount(ZERO))
        _sub(line, "UnitPrice", _amount(item["cena_jednotkova"]))
        _sub(line, "UnitPriceTaxInclusive", _amount(item["cena_jednotkova"]))
        cat = _sub(line, "ClassifiedTaxCategory")
        _sub(cat, "Percent", "0")
        _sub(cat, "VATCalculationMethod", "0")
        _sub(cat, "VATApplicable", "false")
        _sub(_sub(line, "Item"), "Description", item["popis"])

    tax_total = _sub(root, "TaxTotal")
    sub = _sub(tax_total, "TaxSubTotal")
    for tag, value in (
        ("TaxableAmount", total),
        ("TaxAmount", ZERO),
        ("TaxInclusiveAmount", total),
        ("AlreadyClaimedTaxableAmount", ZERO),
        ("AlreadyClaimedTaxAmount", ZERO),
        ("AlreadyClaimedTaxInclusiveAmount", ZERO),
        ("DifferenceTaxableAmount", total),
        ("DifferenceTaxAmount", ZERO),
        ("DifferenceTaxInclusiveAmount", total),
    ):
        _sub(sub, tag, _amount(value))
    tax_cat = _sub(sub, "TaxCategory")
    _sub(tax_cat, "Percent", "0")
    _sub(tax_cat, "VATApplicable", "false")
    _sub(tax_total, "TaxAmount", _amount(ZERO))

    money = _sub(root, "LegalMonetaryTotal")
    for tag, value in (
        ("TaxExclusiveAmount", total),
        ("TaxInclusiveAmount", total),
        ("AlreadyClaimedTaxExclusiveAmount", ZERO),
        ("AlreadyClaimedTaxInclusiveAmount", ZERO),
        ("DifferenceTaxExclusiveAmount", total),
        ("DifferenceTaxInclusiveAmount", total),
        ("PayableRoundingAmount", ZERO),
        ("PaidDepositsAmount", ZERO),
        ("PayableAmount", total),
    ):
        _sub(money, tag, _amount(value))

    payment = _sub(_sub(root, "PaymentMeans"), "Payment")
    _sub(payment, "PaidAmount", _amount(total))
    _sub(payment, "PaymentMeansCode", "42")  # 42 = bank transfer
    details = _sub(payment, "Details")
    _sub(details, "PaymentDueDate", inv["datum_splatnosti"].isoformat())
    try:
        account = parse_cz_account(firma.banka.ucet)
        number = f"{account.prefix}-{account.number}" if account.prefix else account.number
        bank_code = account.bank_code
    except AccountError:
        number, bank_code = firma.banka.ucet, ""
    _sub(details, "ID", number)
    _sub(details, "BankCode", bank_code)
    _sub(details, "Name", "")
    _sub(details, "IBAN", firma.banka.iban)
    _sub(details, "BIC", "")
    _sub(details, "VariableSymbol", inv["vs"])

    ET.indent(root)
    body: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return body
