"""First-run wizard: password, company, bank account, mail, branding, numbering."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from starlette.responses import RedirectResponse, Response

from app.ares.client import AresUnavailable
from app.ares.ico import normalize_ico, validate_ico
from app.auth import MIN_PASSWORD_LENGTH, tokens_equal
from app.banks.ucet import AccountError, parse_cz_account
from app.config import INVOICE_NUMBER_FORMATS, Firma, FirmaConfig
from app.invoices.service import InvoiceService
from app.web.branding import MAX_LOGO_BYTES, BrandingError, current_colors, save_logo, write_theme
from app.web.routes_auth import log_in
from app.web.security import verify_csrf
from app.web.templating import render

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pruvodce", dependencies=[Depends(verify_csrf)])

STEPS = (
    ("heslo", "Heslo"),
    ("firma", "Firma"),
    ("banka", "Bankovní účet"),
    ("posta", "Pošta"),
    ("vzhled", "Logo a barvy"),
    ("rada", "Číselná řada"),
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PSC_RE = re.compile(r"^\d{3} ?\d{2}$")


def _load(request: Request) -> FirmaConfig:
    return FirmaConfig.load(request.app.state.settings.firma_path)


def _save(request: Request, cfg: FirmaConfig) -> None:
    cfg.save(request.app.state.settings.firma_path)


def _page(request: Request, step: str, status_code: int = 200, **ctx: Any) -> Response:
    return render(
        request, f"pruvodce/{step}.html", status_code=status_code, steps=STEPS, step=step, **ctx
    )


def _next(step: str) -> RedirectResponse:
    names = [s for s, _ in STEPS]
    i = names.index(step)
    target = f"/pruvodce/{names[i + 1]}" if i + 1 < len(names) else "/"
    return RedirectResponse(target, status_code=303)


@router.get("")
def start(request: Request) -> Response:
    return RedirectResponse("/pruvodce/firma", status_code=303)


# -- password --------------------------------------------------------------


@router.get("/heslo")
def password_form(request: Request) -> Response:
    if request.app.state.passwords.is_set():
        return RedirectResponse("/pruvodce", status_code=303)
    return _page(request, "heslo")


@router.post("/heslo")
def password_set(
    request: Request,
    kod: Annotated[str, Form()] = "",
    heslo: Annotated[str, Form()] = "",
    heslo2: Annotated[str, Form()] = "",
) -> Response:
    passwords = request.app.state.passwords
    if passwords.is_set():
        return RedirectResponse("/pruvodce", status_code=303)
    errors = []
    if not tokens_equal(kod.strip(), request.app.state.setup_token):
        errors.append("Nesprávný kód pro první spuštění. Najdete ho ve výpisu (logu) kontejneru.")
    if len(heslo) < MIN_PASSWORD_LENGTH:
        errors.append(f"Heslo musí mít alespoň {MIN_PASSWORD_LENGTH} znaků.")
    elif heslo != heslo2:
        errors.append("Hesla se neshodují.")
    if errors:
        return _page(request, "heslo", status_code=400, errors=errors)
    passwords.set_password(heslo)
    log.info("Password set via setup wizard")
    log_in(request)
    return _next("heslo")


# -- company ---------------------------------------------------------------


@router.get("/firma")
def company_form(request: Request) -> Response:
    return _page(request, "firma", f=_load(request).firma)


@router.get("/ares")
def ares_lookup(request: Request, ico: str = "") -> Response:
    """HTMX endpoint: returns the company fields pre-filled from ARES."""
    current = Firma(ico=ico.strip())
    if not validate_ico(ico):
        return render(
            request,
            "pruvodce/_firma_pole.html",
            f=current,
            errors=["IČO nemá platný kontrolní součet."],
        )
    try:
        subj = request.app.state.ares.lookup(ico)
    except AresUnavailable:
        return render(
            request,
            "pruvodce/_firma_pole.html",
            f=current,
            errors=["ARES je teď nedostupný. Údaje vyplňte ručně."],
        )
    if subj is None:
        return render(
            request,
            "pruvodce/_firma_pole.html",
            f=current,
            errors=["Subjekt s tímto IČO v ARES neexistuje."],
        )
    stored = _load(request).firma
    f = Firma(
        nazev=subj.nazev,
        ico=subj.ico,
        dic=subj.dic,
        ulice=subj.ulice,
        mesto=subj.mesto,
        psc=subj.psc,
        email=stored.email,
        telefon=stored.telefon,
        web=stored.web,
        zapis_rejstrik=stored.zapis_rejstrik,
    )
    return render(request, "pruvodce/_firma_pole.html", f=f, info="Údaje načteny z ARES.")


@router.post("/firma")
def company_save(
    request: Request,
    nazev: Annotated[str, Form()] = "",
    ico: Annotated[str, Form()] = "",
    dic: Annotated[str, Form()] = "",
    ulice: Annotated[str, Form()] = "",
    mesto: Annotated[str, Form()] = "",
    psc: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    telefon: Annotated[str, Form()] = "",
    web: Annotated[str, Form()] = "",
    zapis_rejstrik: Annotated[str, Form()] = "",
) -> Response:
    f = Firma(
        nazev=nazev.strip(),
        ico=ico.strip(),
        dic=dic.strip().upper(),
        ulice=ulice.strip(),
        mesto=mesto.strip(),
        psc=psc.strip(),
        email=email.strip(),
        telefon=telefon.strip(),
        web=web.strip(),
        zapis_rejstrik=zapis_rejstrik.strip(),
    )
    errors = []
    if not f.nazev:
        errors.append("Vyplňte název nebo jméno.")
    if not validate_ico(f.ico):
        errors.append("IČO nemá platný kontrolní součet.")
    else:
        f.ico = normalize_ico(f.ico)
    if f.dic and not re.fullmatch(r"CZ\d{8,10}", f.dic):
        errors.append("DIČ zadejte ve tvaru CZ12345678.")
    if not (f.ulice and f.mesto):
        errors.append("Vyplňte adresu.")
    if not _PSC_RE.match(f.psc):
        errors.append("PSČ zadejte jako pět číslic.")
    if f.email and not _EMAIL_RE.match(f.email):
        errors.append("E-mail nemá správný tvar.")
    if errors:
        return _page(request, "firma", status_code=400, f=f, errors=errors)
    cfg = _load(request)
    cfg.firma = f
    _save(request, cfg)
    return _next("firma")


# -- bank account ----------------------------------------------------------


@router.get("/banka")
def bank_form(request: Request) -> Response:
    return _page(request, "banka", ucet=_load(request).banka.ucet)


@router.post("/banka")
def bank_save(request: Request, ucet: Annotated[str, Form()] = "") -> Response:
    try:
        account = parse_cz_account(ucet)
    except AccountError as exc:
        return _page(request, "banka", status_code=400, ucet=ucet, errors=[str(exc)])
    cfg = _load(request)
    cfg.banka.ucet = str(account)
    cfg.banka.iban = account.iban
    _save(request, cfg)
    return _next("banka")


# -- mail (read-only overview, secrets live in .env) -----------------------


@router.get("/posta")
def mail_info(request: Request) -> Response:
    return _page(request, "posta", s=request.app.state.settings)


@router.post("/posta")
def mail_continue(request: Request) -> Response:
    return _next("posta")


# -- branding --------------------------------------------------------------


@router.get("/vzhled")
def look_form(request: Request) -> Response:
    primary, accent = current_colors(request.app.state.settings.branding_dir)
    return _page(request, "vzhled", primary=primary, accent=accent)


@router.post("/vzhled")
async def look_save(
    request: Request,
    logo: UploadFile | None = None,
    primary: Annotated[str, Form()] = "",
    accent: Annotated[str, Form()] = "",
) -> Response:
    branding_dir = request.app.state.settings.branding_dir
    try:
        if logo is not None and logo.filename:
            data = await logo.read(MAX_LOGO_BYTES + 1)
            save_logo(branding_dir, data)
        if primary or accent:
            cur_primary, cur_accent = current_colors(branding_dir)
            write_theme(branding_dir, primary or cur_primary, accent or cur_accent)
    except BrandingError as exc:
        return _page(
            request, "vzhled", status_code=400, primary=primary, accent=accent, errors=[str(exc)]
        )
    return _next("vzhled")


# -- invoice numbering -----------------------------------------------------


@router.get("/rada")
def numbering_form(request: Request) -> Response:
    return _page(request, "rada", fak=_load(request).fakturace, formats=INVOICE_NUMBER_FORMATS)


@router.post("/rada")
def numbering_save(
    request: Request,
    format_cisla: Annotated[str, Form()] = "RRRRNNNN",
    pocatecni_cislo: Annotated[str, Form()] = "1",
    splatnost_dni: Annotated[str, Form()] = "14",
    text_dph: Annotated[str, Form()] = "",
) -> Response:
    cfg = _load(request)
    errors = []
    if format_cisla not in INVOICE_NUMBER_FORMATS:
        errors.append("Neznámý formát číselné řady.")
    elif (
        format_cisla != cfg.fakturace.format_cisla
        and InvoiceService(request.app.state.storage, cfg).years()
    ):
        errors.append("Formát číselné řady nejde změnit, když už existují vystavené faktury.")
    if not text_dph.strip():
        errors.append("Vyplňte text o tom, že nejste plátce DPH.")
    max_seq = 10 ** format_cisla.count("N") - 1
    try:
        start = int(pocatecni_cislo)
        if not 1 <= start <= max_seq:
            raise ValueError
    except ValueError:
        errors.append(f"Počáteční číslo musí být celé číslo od 1 do {max_seq}.")
        start = 1
    try:
        due = int(splatnost_dni)
        if not 0 <= due <= 365:
            raise ValueError
    except ValueError:
        errors.append("Splatnost zadejte jako počet dní (0–365).")
        due = 14
    cfg.fakturace.format_cisla = format_cisla
    cfg.fakturace.pocatecni_cislo = start
    cfg.fakturace.splatnost_dni = due
    cfg.fakturace.text_dph = text_dph.strip() or cfg.fakturace.text_dph
    if errors:
        return _page(
            request,
            "rada",
            status_code=400,
            fak=cfg.fakturace,
            formats=INVOICE_NUMBER_FORMATS,
            errors=errors,
        )
    cfg.aplikace.pruvodce_dokoncen = True
    _save(request, cfg)
    log.info("Setup wizard completed")
    return _next("rada")
