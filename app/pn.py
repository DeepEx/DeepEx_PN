from sqlalchemy import text
from sqlalchemy.orm import Session

from models import BOMItem, PNHistory, PartNumber

def next_progressivo(db: Session, cat_abbr: str, tipo_abbr: str) -> int:
    scope = f"{cat_abbr}|{tipo_abbr}"
    # UPSERT atomico: crea scope se non esiste, altrimenti incrementa.
    # Ritorna SEMPRE il nuovo last_number.
    q = text("""
        INSERT INTO pn_sequences (scope, last_number)
        VALUES (:scope, 1)
        ON CONFLICT (scope)
        DO UPDATE SET last_number = pn_sequences.last_number + 1
        RETURNING last_number
    """)
    new_num = db.execute(q, {"scope": scope}).scalar_one()
    return int(new_num)

def build_pn(cat_abbr: str, tipo_abbr: str, progressivo: int, rev: str, val: str) -> str:
    return f"{cat_abbr}-{tipo_abbr}-{progressivo:04d}-{rev}-{val}"

def create_pn(
    db: Session,
    user: str,
    cat_abbr: str,
    tipo_abbr: str,
    rev: str,
    val: str,
    descrizione: str | None,
    classificazione: str,
    costo_standard: float | None,
    valuta: str,
    supplier_id: int | None,
    supplier_pn: str | None,
    unita_misura: str | None,
    lead_time_giorni: int | None,
    moq: int | None,
    link: str | None,
    note: str | None,
):

    progressivo = next_progressivo(db, cat_abbr, tipo_abbr)
    pn = build_pn(cat_abbr, tipo_abbr, progressivo, rev, val)

    obj = PartNumber(
        pn=pn,
        cat_abbr=cat_abbr,
        tipo_abbr=tipo_abbr,
        progressivo=progressivo,
        rev=rev,
        val=val,
        descrizione=descrizione,
        classificazione=classificazione,
        costo_standard=costo_standard,
        valuta=valuta,
        supplier_id=supplier_id,
        supplier_pn=supplier_pn,
        stato="BOZZA",
        unita_misura=unita_misura,
        lead_time_giorni=lead_time_giorni,
        moq=moq,
        link=link,
        note=note,

    )
    db.add(obj)
    db.flush()  # <-- inserisce PartNumber nella transazione (senza commit)

    db.add(PNHistory(
        pn=pn,
        user=user,
        action="CREATE",
        details_json=None,
    ))

    return obj
def create_pn_revision(
    db: Session,
    user: str,
    source: PartNumber,
    new_rev: str,
):
    rev = (new_rev or "").strip()
    if not rev:
        raise ValueError("Inserisci la nuova revisione.")

    pn = build_pn(
        source.cat_abbr,
        source.tipo_abbr,
        source.progressivo,
        rev,
        source.val or "",
    )

    if pn == source.pn:
        raise ValueError("La nuova revisione deve essere diversa da quella corrente.")

    if db.get(PartNumber, pn):
        raise ValueError(f"Esiste gia un P/N con codice {pn}.")

    obj = PartNumber(
        pn=pn,
        cat_abbr=source.cat_abbr,
        tipo_abbr=source.tipo_abbr,
        progressivo=source.progressivo,
        rev=rev,
        val=source.val,
        descrizione=source.descrizione,
        classificazione=source.classificazione,
        costo_standard=source.costo_standard,
        valuta=source.valuta,
        supplier_id=source.supplier_id,
        supplier_pn=source.supplier_pn,
        stato="BOZZA",
        unita_misura=source.unita_misura,
        lead_time_giorni=source.lead_time_giorni,
        moq=source.moq,
        link=source.link,
        note=source.note,
        # le proprieta fisiche partono da quelle della revisione sorgente: vanno riverificate
        massa_secco_g=source.massa_secco_g,
        peso_acqua_g=source.peso_acqua_g,
        volume_cm3=source.volume_cm3,
        dim_lunghezza_mm=source.dim_lunghezza_mm,
        dim_larghezza_mm=source.dim_larghezza_mm,
        dim_altezza_mm=source.dim_altezza_mm,
        proprieta_fonte=source.proprieta_fonte,
        proprieta_data=source.proprieta_data,
        proprieta_note=source.proprieta_note,
    )
    db.add(obj)
    db.flush()

    bom_rows = db.query(BOMItem).filter(BOMItem.parent_pn == source.pn).all()
    for row in bom_rows:
        db.add(BOMItem(
            parent_pn=obj.pn,
            child_pn=row.child_pn,
            qty=row.qty,
            scrap_pct=row.scrap_pct,
            notes=row.notes,
        ))

    db.add(PNHistory(
        pn=obj.pn,
        user=user,
        action="CREATE_REVISION",
        details_json=f"from:{source.pn}",
    ))
    db.add(PNHistory(
        pn=source.pn,
        user=user,
        action="REVISED_TO",
        details_json=pn,
    ))

    return obj


__all__ = ["build_pn", "create_pn", "create_pn_revision", "next_progressivo"]
