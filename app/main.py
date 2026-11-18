import os
import json
import csv, io, re
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from db import Base, engine, get_db, ensure_schema
from models import Abbreviation, Supplier, PartNumber, User, PNHistory
from auth import verify_password, require_user, SESSION_KEY, ensure_admin_user, get_user
from pn import create_pn, create_pn_revision

from models import Abbreviation, PartNumber

from decimal import Decimal
from bom import compute_unit_cost, compute_physical_rollup
from models import BOMItem
from fastapi import Form
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from models import Abbreviation

from urllib.parse import quote
from sqlalchemy import func
from models import Abbreviation, PartNumber
from fastapi.responses import JSONResponse



app = FastAPI(title="DeepEx – Gestione Part Number")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"])

templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    # crea admin se mancante
    from db import SessionLocal
    db = SessionLocal()
    try:
        ensure_admin_user(db)
    finally:
        db.close()

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.username == username).first()
    if not u or not verify_password(password, u.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali non valide"})
    request.session[SESSION_KEY] = u.username
    return RedirectResponse("/", status_code=303)

@app.post("/logout")
def logout(request: Request):
    request.session.pop(SESSION_KEY, None)
    return RedirectResponse("/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/pn/new", response_class=HTMLResponse)
def new_pn_page(request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    cats = db.query(Abbreviation).filter(Abbreviation.kind == "CAT").order_by(Abbreviation.name).all()
    tipos = db.query(Abbreviation).filter(Abbreviation.kind == "TIPO").order_by(Abbreviation.name).all()
    suppliers = db.query(Supplier).order_by(Supplier.name).all()

    print("DEBUG suppliers:", len(suppliers))  # temporaneo, poi lo togli

    return templates.TemplateResponse(
        "new_pn.html",
        {"request": request, "user": user, "cats": cats, "tipos": tipos, "suppliers": suppliers, "error": None}
    )


@app.post("/pn/new")
def new_pn_submit(
    request: Request,
    cat_abbr: str = Form(...),
    tipo_abbr: str = Form(...),
    rev: str = Form(...),
    val: str = Form(...),
    descrizione: str = Form(""),
    classificazione: str = Form("BUY"),
    costo_standard: str = Form(""),
    valuta: str = Form("EUR"),
    supplier_id: str = Form(""),
    supplier_pn: str = Form(""),
    unita_misura: str = Form(""),
    lead_time_giorni: str = Form(""),
    moq: str = Form(""),
    link: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    try:
        costo = float(costo_standard) if costo_standard.strip() else None
        sup_id = int(supplier_id) if supplier_id.strip() else None
        sup_pn = supplier_pn.strip() or None
        desc = descrizione.strip() or None
        um = unita_misura.strip() or None
        lt = int(lead_time_giorni) if lead_time_giorni.strip() else None
        moq_i = int(moq) if moq.strip() else None
        lk = link.strip() or None
        nt = note.strip() or None

        obj = create_pn(
            db=db,
            user=user,
            cat_abbr=cat_abbr.strip(),
            tipo_abbr=tipo_abbr.strip(),
            rev=rev.strip(),
            val=val.strip(),
            descrizione=desc,
            classificazione=classificazione.strip().upper(),
            costo_standard=costo,
            valuta=valuta.strip().upper(),
            supplier_id=sup_id,
            supplier_pn=sup_pn,
            unita_misura=um,
            lead_time_giorni=lt,
            moq=moq_i,
            link=lk,
            note=nt,

        )
        db.commit()
        return RedirectResponse(f"/pn/{obj.pn}", status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("new_pn.html", {
            "request": request, "user": user, "cats": db.query(Abbreviation).filter(Abbreviation.kind=="CAT").all(),
            "tipos": db.query(Abbreviation).filter(Abbreviation.kind=="TIPO").all(),
            "suppliers": db.query(Supplier).all(),
            "error": f"Errore creazione P/N: {e}"
        })

from sqlalchemy import or_

@app.get("/pn", response_class=HTMLResponse)
def list_pn(request: Request, q: str = "", stato: str = "", db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    q = (q or "").strip()
    stato = (stato or "").strip().upper()

    query = db.query(PartNumber)

    if stato in ("BOZZA", "RILASCIATO", "OBSOLETO"):
        query = query.filter(PartNumber.stato == stato)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            PartNumber.pn.ilike(like),
            PartNumber.descrizione.ilike(like),
            PartNumber.supplier_pn.ilike(like),
        ))

    items = query.order_by(PartNumber.created_at.desc()).limit(200).all()

    return templates.TemplateResponse(
        "list_pn.html",
        {"request": request, "user": user, "items": items, "q": q, "stato": stato}
    )


@app.get("/pn/{pn}", response_class=HTMLResponse)
def pn_detail(pn: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if not item:
        return RedirectResponse("/pn", status_code=303)

    return templates.TemplateResponse(
        "detail_pn.html",
        {"request": request, "user": user, "item": item}
    )

@app.post("/admin/abbreviations/import")
def import_abbreviations(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    text = file.file.read().decode("utf-8-sig")  # gestisce anche BOM Excel
    reader = csv.DictReader(text.splitlines())

    added = 0
    for row in reader:
        kind = row["kind"].strip().upper()
        name = row["name"].strip()
        abbr = row["abbr"].strip().upper()

        if kind not in ("CAT", "TIPO"):
            continue

        exists = db.query(Abbreviation).filter_by(kind=kind, abbr=abbr).first()
        if not exists:
            db.add(Abbreviation(kind=kind, name=name, abbr=abbr))
            added += 1

    db.commit()
    return {"status": "ok", "added": added}


from models import Supplier

@app.get("/suppliers", response_class=HTMLResponse)
def suppliers_page(request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return templates.TemplateResponse(
        "suppliers.html",
        {"request": request, "user": user, "suppliers": suppliers, "error": None}
    )

@app.post("/suppliers")
def suppliers_add(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    note: str = Form(""),
    piva: str = Form(""),
    indirizzo: str = Form(""),
    citta: str = Form(""),
    cap: str = Form(""),
    nazione: str = Form(""),
    sito_web: str = Form(""),
    referente_nome: str = Form(""),
    referente_email: str = Form(""),
    referente_tel: str = Form(""),

    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    name = name.strip()
    if not name:
        return RedirectResponse("/suppliers", status_code=303)

    db.add(Supplier(
        name=name,
        email=email.strip() or None,
        phone=phone.strip() or None,
        note=note.strip() or None,
        piva=piva.strip() or None,
        indirizzo=indirizzo.strip() or None,
        citta=citta.strip() or None,
        cap=cap.strip() or None,
        nazione=nazione.strip() or None,
        sito_web=sito_web.strip() or None,
        referente_nome=referente_nome.strip() or None,
        referente_email=referente_email.strip() or None,
        referente_tel=referente_tel.strip() or None,
    ))
    db.commit()
    return RedirectResponse("/suppliers", status_code=303)

import csv, io
from decimal import Decimal, InvalidOperation
from fastapi import UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from models import PartNumber, Supplier

def _parse_price_eur(s: str | None):
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # gestisce "12,50" e "12.50" e anche "€"
    s = s.replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None

@app.post("/admin/pn/import")
def import_existing_pn(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw = file.file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")

    required = {"Categoria", "Tipo", "Versione", "Descrizione", "Codice"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise HTTPException(400, f"Intestazioni CSV non valide. Attese almeno: {sorted(required)}")

    created = 0
    updated = 0
    skipped = 0

    for row in reader:
        codice = (row.get("Codice") or "").strip()
        if not codice:
            skipped += 1
            continue

        # parsing P/N: CAT-TIPO-NNNN-REV(-VAL opzionale)
        parts = codice.split("-")
        if len(parts) < 4:
            skipped += 1
            continue

        cat_abbr = parts[0].strip()
        tipo_abbr = parts[1].strip()

        try:
            progressivo = int(parts[2])
        except ValueError:
            skipped += 1
            continue

        rev = parts[3].strip()
        val = parts[4].strip() if len(parts) > 4 else ""

        descrizione = (row.get("Descrizione") or "").strip() or None
        link = (row.get("Link") or "").strip() or None
        supplier_name = (row.get("Fornitore") or "").strip() or None
        supplier_pn = (row.get("Codice Fornitore") or "").strip() or None
        prezzo = _parse_price_eur(row.get("Prezzo (€)"))

        # "Valore" dal CSV (se vuoi salvarlo nelle note)
        valore_extra = (row.get("Valore") or "").strip() or None

        # Trova/crea fornitore (se presente)
        supplier_id = None
        if supplier_name:
            sup = db.query(Supplier).filter(Supplier.name == supplier_name).first()
            if not sup:
                sup = Supplier(name=supplier_name)
                db.add(sup)
                db.flush()  # ottieni sup.id senza commit
            supplier_id = sup.id

        obj = db.get(PartNumber, codice)

        if not obj:
            # Nuovo record
            obj = PartNumber(
                pn=codice,
                cat_abbr=cat_abbr,
                tipo_abbr=tipo_abbr,
                progressivo=progressivo,
                rev=rev,
                val=val,
                descrizione=descrizione,
                classificazione="BUY" if supplier_id else "STANDARD",
                costo_standard=prezzo,
                valuta="EUR",
                supplier_id=supplier_id,
                supplier_pn=supplier_pn,
                link=link,
                note=valore_extra,
                stato="RILASCIATO",
            )
            db.add(obj)
            created += 1
        else:
            # Aggiorna solo se nel CSV ci sono valori non vuoti
            changed = False

            def set_if(value, attr):
                nonlocal changed
                if value is not None and value != "" and getattr(obj, attr) != value:
                    setattr(obj, attr, value)
                    changed = True

            set_if(descrizione, "descrizione")
            set_if(link, "link")
            set_if(supplier_id, "supplier_id")
            set_if(supplier_pn, "supplier_pn")
            if prezzo is not None and obj.costo_standard != prezzo:
                obj.costo_standard = prezzo
                obj.valuta = "EUR"
                changed = True
            if valore_extra:
                # se note è vuota, riempila; se già c’è, lasciamo com’è
                if not obj.note:
                    obj.note = valore_extra
                    changed = True

            # opzionale: se non aveva classificazione e ora ha fornitore
            if supplier_id and obj.classificazione != "BUY":
                obj.classificazione = "BUY"
                changed = True

            if changed:
                updated += 1
            else:
                skipped += 1

    db.commit()
    return {"status": "ok", "created": created, "updated": updated, "skipped": skipped}

@app.get("/suppliers/{supplier_id}", response_class=HTMLResponse)
def supplier_detail(request: Request, supplier_id: int, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    s = db.get(Supplier, supplier_id)
    if not s:
        return RedirectResponse("/suppliers", status_code=303)

    return templates.TemplateResponse(
        "supplier_detail.html",
        {"request": request, "user": user, "s": s, "error": None}
    )

@app.post("/suppliers/{supplier_id}")
def supplier_update(
    request: Request,
    supplier_id: int,
    name: str = Form(...),
    piva: str = Form(""),
    indirizzo: str = Form(""),
    citta: str = Form(""),
    cap: str = Form(""),
    nazione: str = Form(""),
    sito_web: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    referente_nome: str = Form(""),
    referente_email: str = Form(""),
    referente_tel: str = Form(""),
    iban: str = Form(""),
    payment_terms: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    s = db.get(Supplier, supplier_id)
    if not s:
        return RedirectResponse("/suppliers", status_code=303)

    s.name = name.strip()
    s.piva = piva.strip() or None
    s.indirizzo = indirizzo.strip() or None
    s.citta = citta.strip() or None
    s.cap = cap.strip() or None
    s.nazione = nazione.strip() or None
    s.sito_web = sito_web.strip() or None
    s.email = email.strip() or None
    s.phone = phone.strip() or None
    s.referente_nome = referente_nome.strip() or None
    s.referente_email = referente_email.strip() or None
    s.referente_tel = referente_tel.strip() or None
    s.iban = iban.strip() or None
    s.payment_terms = payment_terms.strip() or None
    s.note = note.strip() or None

    db.commit()
    return RedirectResponse(f"/suppliers/{supplier_id}", status_code=303)

@app.get("/pn/{pn}/edit", response_class=HTMLResponse)
def pn_edit_page(pn: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if not item:
        return RedirectResponse("/pn", status_code=303)

    readonly_id = (item.stato == "OBSOLETO")  # su obsoleto blocchiamo tutto
    if readonly_id:
        return RedirectResponse(f"/pn/{pn}", status_code=303)


    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    return templates.TemplateResponse(
        "pn_edit.html",
        {
            "request": request,
            "user": user,
            "item": item,
            "suppliers": suppliers,
            "error": None,
            "revision_error": None,
            "suggested_rev": _suggest_next_revision(item.rev),
            "physical_sources": PHYSICAL_SOURCES,
        }
    )


def _suggest_next_revision(current_rev: str | None) -> str:
    value = (current_rev or "").strip()
    if not value:
        return "1"

    if value.isdigit():
        return str(int(value) + 1)

    if len(value) == 1 and value.isalpha():
        if value.upper() == "Z":
            return "AA"
        return chr(ord(value.upper()) + 1)

    return value

PHYSICAL_SOURCES = ["MISURATO", "CAD", "DATASHEET", "STIMATO"]


def _parse_decimal_field(raw: str, label: str, allow_negative: bool = False):
    value = (raw or "").strip().replace(" ", "").replace(",", ".")
    if not value:
        return None
    try:
        number = Decimal(value)
    except Exception:
        raise ValueError(f"{label}: valore numerico non valido ({raw}).")
    if not number.is_finite():
        raise ValueError(f"{label}: valore numerico non valido ({raw}).")
    if number < 0 and not allow_negative:
        raise ValueError(f"{label}: il valore non puo essere negativo.")
    return number.quantize(Decimal("0.1"))


def _parse_physical_form(massa, peso_acqua, volume, lung, larg, alt, fonte, data, note):
    from datetime import date as _date
    result = {
        "massa_secco_g": _parse_decimal_field(massa, "Massa a secco"),
        "peso_acqua_g": _parse_decimal_field(peso_acqua, "Peso in acqua", allow_negative=True),
        "volume_cm3": _parse_decimal_field(volume, "Volume"),
        "dim_lunghezza_mm": _parse_decimal_field(lung, "Lunghezza"),
        "dim_larghezza_mm": _parse_decimal_field(larg, "Larghezza"),
        "dim_altezza_mm": _parse_decimal_field(alt, "Altezza"),
    }
    src = (fonte or "").strip().upper() or None
    if src is not None and src not in PHYSICAL_SOURCES:
        raise ValueError(f"Fonte proprieta fisiche non valida: {fonte}.")
    result["proprieta_fonte"] = src
    d = (data or "").strip()
    if d:
        try:
            result["proprieta_data"] = _date.fromisoformat(d)
        except ValueError:
            raise ValueError(f"Data proprieta fisiche non valida: {data} (formato AAAA-MM-GG).")
    else:
        result["proprieta_data"] = None
    result["proprieta_note"] = (note or "").strip() or None
    return result


@app.post("/pn/{pn}/edit")
def pn_edit_submit(
    pn: str,
    request: Request,
    descrizione: str = Form(""),
    classificazione: str = Form("BUY"),
    costo_standard: str = Form(""),
    valuta: str = Form("EUR"),
    supplier_id: str = Form(""),
    supplier_pn: str = Form(""),
    unita_misura: str = Form(""),
    lead_time_giorni: str = Form(""),
    moq: str = Form(""),
    link: str = Form(""),
    note: str = Form(""),
    massa_secco_g: str = Form(""),
    peso_acqua_g: str = Form(""),
    volume_cm3: str = Form(""),
    dim_lunghezza_mm: str = Form(""),
    dim_larghezza_mm: str = Form(""),
    dim_altezza_mm: str = Form(""),
    proprieta_fonte: str = Form(""),
    proprieta_data: str = Form(""),
    proprieta_note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if not item:
        return RedirectResponse("/pn", status_code=303)

    if item.stato == "OBSOLETO":
        return RedirectResponse(f"/pn/{pn}", status_code=303)

    # proprieta fisiche
    try:
        phys = _parse_physical_form(
            massa_secco_g, peso_acqua_g, volume_cm3,
            dim_lunghezza_mm, dim_larghezza_mm, dim_altezza_mm,
            proprieta_fonte, proprieta_data, proprieta_note,
        )
    except ValueError as e:
        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        return templates.TemplateResponse(
            "pn_edit.html",
            {
                "request": request,
                "user": user,
                "item": item,
                "suppliers": suppliers,
                "error": str(e),
                "revision_error": None,
                "suggested_rev": _suggest_next_revision(item.rev),
                "physical_sources": PHYSICAL_SOURCES,
            },
            status_code=400,
        )

    # parsing
    desc = descrizione.strip() or None
    cl = classificazione.strip().upper()
    cur = valuta.strip().upper() or "EUR"
    sup_id = int(supplier_id) if supplier_id.strip() else None
    sup_pn = supplier_pn.strip() or None
    um = unita_misura.strip() or None
    lt = int(lead_time_giorni) if lead_time_giorni.strip() else None
    moq_i = int(moq) if moq.strip() else None
    lk = link.strip() or None
    nt = note.strip() or None

    costo = None
    if costo_standard.strip():
        s = costo_standard.strip().replace("€", "").replace(" ", "").replace(",", ".")
        try:
            costo = float(s)
        except ValueError:
            costo = None

    # update campi
    item.descrizione = desc
    item.classificazione = cl
    item.costo_standard = costo
    item.valuta = cur
    item.supplier_id = sup_id
    item.supplier_pn = sup_pn
    item.unita_misura = um
    item.lead_time_giorni = lt
    item.moq = moq_i
    item.link = lk
    item.note = nt

    phys_changes = {}
    for key, value in phys.items():
        old = getattr(item, key)
        if (str(old) if old is not None else None) != (str(value) if value is not None else None):
            phys_changes[key] = {"da": None if old is None else str(old), "a": None if value is None else str(value)}
        setattr(item, key, value)

    db.add(PNHistory(
    pn=item.pn,
    user=user,
    action="UPDATE_META",
    details_json=json.dumps({"proprieta_fisiche": phys_changes}, ensure_ascii=False) if phys_changes else None,
    ))

    db.commit()
    return RedirectResponse(f"/pn/{pn}", status_code=303)


@app.post("/pn/{pn}/revision")
def pn_revision_submit(
    pn: str,
    request: Request,
    new_rev: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if not item:
        return RedirectResponse("/pn", status_code=303)

    if item.stato == "OBSOLETO":
        return RedirectResponse(f"/pn/{pn}", status_code=303)

    try:
        new_item = create_pn_revision(
            db=db,
            user=user,
            source=item,
            new_rev=new_rev,
        )
        db.commit()
        return RedirectResponse(f"/pn/{new_item.pn}", status_code=303)
    except Exception as e:
        db.rollback()
        current_item = db.get(PartNumber, pn)
        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        return templates.TemplateResponse(
            "pn_edit.html",
            {
                "request": request,
                "user": user,
                "item": current_item,
                "suppliers": suppliers,
                "error": None,
                "revision_error": f"Errore generazione revisione: {e}",
                "suggested_rev": (new_rev or "").strip() or _suggest_next_revision(current_item.rev if current_item else ""),
                "physical_sources": PHYSICAL_SOURCES,
            }
        )

@app.post("/pn/{pn}/release")
def pn_release(pn: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if item and item.stato == "BOZZA":
        item.stato = "RILASCIATO"
        db.add(PNHistory(pn=item.pn, user=user, action="RELEASE", details_json=None))
        db.commit()
    return RedirectResponse(f"/pn/{pn}", status_code=303)

@app.post("/pn/{pn}/obsolete")
def pn_obsolete(pn: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    item = db.get(PartNumber, pn)
    if item and item.stato != "OBSOLETO":
        item.stato = "OBSOLETO"
        db.add(PNHistory(pn=item.pn, user=user, action="OBSOLETE", details_json=None))
        db.commit()
    return RedirectResponse(f"/pn/{pn}", status_code=303)

from sqlalchemy import or_

@app.get("/pn/{pn}/bom", response_class=HTMLResponse)
def pn_bom_page(pn: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    parent = db.get(PartNumber, pn)
    if not parent:
        return RedirectResponse("/pn", status_code=303)

    rows = (
    db.query(BOMItem)
    .options(joinedload(BOMItem.child))
    .filter(BOMItem.parent_pn == pn)
    .order_by(BOMItem.id.asc())
    .all()
    )

    cache = {}
    res = compute_unit_cost(db, pn, cache, visiting=[])

    mass_res = compute_physical_rollup(db, pn, "massa_secco_g", {}, visiting=[])
    water_res = compute_physical_rollup(db, pn, "peso_acqua_g", {}, visiting=[])

    # costo righe (solo per mostrare breakdown)
    line_costs = []
    if not res.cycle_found:
        for r in rows:
            child_cost = cache.get(r.child_pn, Decimal("0"))
            qty = Decimal(str(r.qty))
            scrap = Decimal(str(r.scrap_pct)) if r.scrap_pct is not None else Decimal("0")
            qty_eff = qty * (Decimal("1") + (scrap / Decimal("100")))
            line_costs.append({
                "id": r.id,
                "child_pn": r.child_pn,
                "child_desc": (r.child.descrizione if r.child else ""),
                "qty": r.qty,
                "scrap_pct": r.scrap_pct,
                "notes": r.notes,
                "unit_cost": child_cost,
                "line_cost": qty_eff * child_cost,
            })


    return templates.TemplateResponse(
        "pn_bom.html",
        {
            "request": request,
            "user": user,
            "parent": parent,
            "rows": rows,
            "line_costs": line_costs,
            "total_cost": res.cost,
            "missing_cost_pns": sorted(list(res.missing_cost_pns)),
            "cycle_found": res.cycle_found,
            "cycle_path": res.cycle_path,
            "mass_rollup": mass_res,
            "water_rollup": water_res,
            "error": None,
        }
    )

@app.post("/pn/{pn}/bom/add")
def pn_bom_add(
    pn: str,
    request: Request,
    child_pn: str = Form(...),
    qty: str = Form(...),
    scrap_pct: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    parent = db.get(PartNumber, pn)
    if not parent:
        return RedirectResponse("/pn", status_code=303)

    child_pn = (child_pn or "").strip()
    if not db.get(PartNumber, child_pn):
        # child non esiste
        return RedirectResponse(f"/pn/{pn}/bom", status_code=303)

    # parsing qty
    q = (qty or "").strip().replace(",", ".")
    sp = (scrap_pct or "").strip().replace(",", ".")

    try:
        qty_d = Decimal(q)
    except Exception:
        return RedirectResponse(f"/pn/{pn}/bom", status_code=303)

    sp_d = None
    if sp:
        try:
            sp_d = Decimal(sp)
        except Exception:
            sp_d = None

    obj = BOMItem(
        parent_pn=pn,
        child_pn=child_pn,
        qty=qty_d,
        scrap_pct=sp_d,
        notes=(notes.strip() or None),
    )
    db.add(obj)

    # storico
    db.add(PNHistory(pn=pn, user=user, action="BOM_ADD", details_json=None))

    try:
        db.commit()
    except Exception:
        db.rollback()
        # se UNIQUE(parent_pn, child_pn) rompe, non facciamo crash
    return RedirectResponse(f"/pn/{pn}/bom", status_code=303)

@app.post("/pn/{pn}/bom/{bom_id}/delete")
def pn_bom_delete(pn: str, bom_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    row = db.get(BOMItem, bom_id)
    if row and row.parent_pn == pn:
        db.delete(row)
        db.add(PNHistory(pn=pn, user=user, action="BOM_DEL", details_json=None))
        db.commit()

    return RedirectResponse(f"/pn/{pn}/bom", status_code=303)

@app.get("/admin/abbreviations", response_class=HTMLResponse)
def abbreviations_page(request: Request, db: Session = Depends(get_db), msg: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    cats = db.query(Abbreviation).filter(Abbreviation.kind == "CAT").order_by(Abbreviation.name.asc()).all()
    tipos = db.query(Abbreviation).filter(Abbreviation.kind == "TIPO").order_by(Abbreviation.name.asc()).all()

    return templates.TemplateResponse(
        "abbreviations.html",
        {"request": request, "user": user, "cats": cats, "tipos": tipos, "msg": msg}
    )


@app.post("/admin/abbreviations/add")
def abbreviations_add(
    request: Request,
    kind: str = Form(...),
    name: str = Form(...),
    abbr: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    kind = (kind or "").strip().upper()
    name = (name or "").strip()
    abbr = (abbr or "").strip().upper()

    if kind not in ("CAT", "TIPO") or not name or not abbr:
        return RedirectResponse("/admin/abbreviations", status_code=303)

    # evita duplicati (stesso kind + name o kind + abbr)
    exists = db.query(Abbreviation).filter(
        Abbreviation.kind == kind,
        (Abbreviation.name == name) | (Abbreviation.abbr == abbr)
    ).first()
    if exists:
        # già presente: non crashiamo
        return RedirectResponse("/admin/abbreviations", status_code=303)

    db.add(Abbreviation(kind=kind, name=name, abbr=abbr))
    try:
        db.commit()
    except Exception:
        db.rollback()

    return RedirectResponse("/admin/abbreviations", status_code=303)


@app.post("/admin/abbreviations/{abbr_id}/delete")
def abbreviations_delete(abbr_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    obj = db.get(Abbreviation, abbr_id)
    if not obj:
        return RedirectResponse("/admin/abbreviations", status_code=303)

    # Protezione: non eliminare se già usata
    used = 0
    if obj.kind == "CAT":
        used = db.query(func.count(PartNumber.pn)).filter(PartNumber.cat_abbr == obj.abbr).scalar() or 0
    elif obj.kind == "TIPO":
        used = db.query(func.count(PartNumber.pn)).filter(PartNumber.tipo_abbr == obj.abbr).scalar() or 0

    if used > 0:
        msg = f'Impossibile eliminare: "{obj.kind} {obj.abbr}" è usata da {used} P/N.'
        return RedirectResponse("/admin/abbreviations?msg=" + quote(msg), status_code=303)

    db.delete(obj)
    db.commit()
    return RedirectResponse("/admin/abbreviations?msg=" + quote("Abbreviazione eliminata."), status_code=303)

@app.get("/api/pn/search")
def api_pn_search(request: Request, q: str = "", limit: int = 12, db: Session = Depends(get_db)):
    user = get_user(request)
    if not user:
        return JSONResponse({"items": []})

    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse({"items": []})

    like = f"%{q}%"
    limit = max(1, min(int(limit or 12), 50))

    rows = (
        db.query(PartNumber)
        .filter(or_(
            PartNumber.pn.ilike(like),
            PartNumber.descrizione.ilike(like),
            PartNumber.supplier_pn.ilike(like),
        ))
        .order_by(PartNumber.pn.asc())
        .limit(limit)
        .all()
    )

    return JSONResponse({
        "items": [
            {
                "pn": r.pn,
                "descrizione": r.descrizione or "",
                "classificazione": r.classificazione or "",
                "stato": r.stato or "",
            }
            for r in rows
        ]
    })
