"""API v1 di sola lettura per l'integrazione machine-to-machine.

Consumatore previsto: DeepEx-Orchestrator, che deve interrogare P/N, distinte
base e costi tramite questa API invece di collegarsi direttamente a PostgreSQL.

L'API e' separata dalla UI browser: nessuna sessione, nessun template, solo
JSON e autenticazione Bearer (vedi app/api_auth.py).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from api_auth import require_service_token
from bom import compute_unit_cost
from db import get_db
from models import BOMItem, PartNumber

# Profondita' massima di espansione ricorsiva della distinta base.
MAX_BOM_DEPTH = 20

DEFAULT_SEARCH_LIMIT = 20
MIN_SEARCH_LIMIT = 1
MAX_SEARCH_LIMIT = 50

router = APIRouter(prefix="/api/v1", tags=["service-api-v1"])

# Sotto-router protetto: l'autenticazione di servizio vale per tutti gli
# endpoint /api/v1 tranne /api/v1/health.
protected = APIRouter(dependencies=[Depends(require_service_token)])


def _decimal(value) -> str | None:
    """Serializza un Decimal in stringa, senza perdere precisione decimale."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(Decimal(str(value)))


def _timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_SEARCH_LIMIT
    except (TypeError, ValueError):
        value = DEFAULT_SEARCH_LIMIT
    return max(MIN_SEARCH_LIMIT, min(value, MAX_SEARCH_LIMIT))


def _part_summary(obj: PartNumber) -> Dict[str, Any]:
    return {
        "pn": obj.pn,
        "descrizione": obj.descrizione,
        "classificazione": obj.classificazione,
        "stato": obj.stato,
        "rev": obj.rev,
        "val": obj.val,
        "supplier_pn": obj.supplier_pn,
    }


def _part_detail(obj: PartNumber) -> Dict[str, Any]:
    return {
        "pn": obj.pn,
        "cat_abbr": obj.cat_abbr,
        "tipo_abbr": obj.tipo_abbr,
        "progressivo": obj.progressivo,
        "rev": obj.rev,
        "val": obj.val,
        "descrizione": obj.descrizione,
        "classificazione": obj.classificazione,
        "costo_standard": _decimal(obj.costo_standard),
        "valuta": obj.valuta,
        "supplier_id": obj.supplier_id,
        "supplier_pn": obj.supplier_pn,
        "stato": obj.stato,
        "unita_misura": obj.unita_misura,
        "lead_time_giorni": obj.lead_time_giorni,
        "moq": obj.moq,
        "link": obj.link,
        "note": obj.note,
        "created_at": _timestamp(obj.created_at),
        "updated_at": _timestamp(obj.updated_at),
    }


def _get_part_or_404(db: Session, pn: str) -> PartNumber:
    obj = db.get(PartNumber, pn)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Part number not found: {pn}")
    return obj


def _bom_rows(db: Session, parent_pn: str) -> List[BOMItem]:
    return (
        db.query(BOMItem)
        .options(joinedload(BOMItem.child))
        .filter(BOMItem.parent_pn == parent_pn)
        .order_by(BOMItem.id.asc())
        .all()
    )


def _bom_line(row: BOMItem, parent_pn: str, level: int) -> Dict[str, Any]:
    child = row.child
    return {
        "bom_item_id": row.id,
        "parent_pn": parent_pn,
        "child_pn": row.child_pn,
        "level": level,
        "qty": _decimal(row.qty),
        "scrap_pct": _decimal(row.scrap_pct),
        "notes": row.notes,
        "child_descrizione": child.descrizione if child else None,
        "child_classificazione": child.classificazione if child else None,
        "child_stato": child.stato if child else None,
    }


@router.get("/health")
def api_v1_health() -> Dict[str, str]:
    """Liveness check non autenticato per l'Orchestrator.

    Non espone database, configurazione, host o stato interno.
    """
    return {"status": "ok", "api_version": "v1"}


@protected.get("/parts/search")
def api_v1_parts_search(
    q: str = "",
    limit: int = DEFAULT_SEARCH_LIMIT,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    q = (q or "").strip()
    limit = _clamp_limit(limit)

    if not q:
        return {"query": q, "limit": limit, "count": 0, "items": []}

    like = f"%{q}%"
    rows = (
        db.query(PartNumber)
        .filter(
            or_(
                PartNumber.pn.ilike(like),
                PartNumber.descrizione.ilike(like),
                PartNumber.supplier_pn.ilike(like),
            )
        )
        .order_by(PartNumber.pn.asc())
        .limit(limit)
        .all()
    )

    items = [_part_summary(r) for r in rows]
    return {"query": q, "limit": limit, "count": len(items), "items": items}


@protected.get("/parts/{pn}")
def api_v1_part_detail(pn: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _part_detail(_get_part_or_404(db, pn))


@protected.get("/parts/{pn}/bom")
def api_v1_part_bom(pn: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    parent = _get_part_or_404(db, pn)
    rows = _bom_rows(db, parent.pn)
    items = [_bom_line(r, parent.pn, 1) for r in rows]

    return {
        "pn": parent.pn,
        "descrizione": parent.descrizione,
        "classificazione": parent.classificazione,
        "stato": parent.stato,
        "count": len(items),
        "items": items,
    }


def _expand_bom(
    db: Session,
    parent_pn: str,
    level: int,
    path: List[str],
    report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Espande ricorsivamente le sole assemblee MAKE.

    La ricorsione e' limitata da MAX_BOM_DEPTH e dal rilevamento esplicito dei
    cicli: entrambe le condizioni vengono riportate nel nodo e nel report, mai
    scartate silenziosamente.
    """
    nodes: List[Dict[str, Any]] = []

    for row in _bom_rows(db, parent_pn):
        node = _bom_line(row, parent_pn, level)
        node.update({"cycle": False, "depth_limit_reached": False, "expanded": False, "children": []})

        child_pn = row.child_pn
        child = row.child
        classificazione = ((child.classificazione if child else "") or "").upper()

        if child_pn in path:
            # Ciclo: si interrompe qui e si riporta il percorso completo.
            cycle_path = path[path.index(child_pn):] + [child_pn]
            node["cycle"] = True
            node["cycle_path"] = cycle_path
            report["cycles"].append({"pn": child_pn, "cycle_path": cycle_path})
        elif classificazione == "MAKE":
            if level >= MAX_BOM_DEPTH:
                node["depth_limit_reached"] = True
                if child_pn not in report["depth_limited_pns"]:
                    report["depth_limited_pns"].append(child_pn)
            else:
                node["children"] = _expand_bom(db, child_pn, level + 1, path + [child_pn], report)
                node["expanded"] = True

        if level > report["max_level_reached"]:
            report["max_level_reached"] = level

        nodes.append(node)

    return nodes


@protected.get("/parts/{pn}/bom/recursive")
def api_v1_part_bom_recursive(pn: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    parent = _get_part_or_404(db, pn)

    report: Dict[str, Any] = {"cycles": [], "depth_limited_pns": [], "max_level_reached": 0}
    items = _expand_bom(db, parent.pn, 1, [parent.pn], report)

    return {
        "pn": parent.pn,
        "descrizione": parent.descrizione,
        "classificazione": parent.classificazione,
        "stato": parent.stato,
        "max_depth": MAX_BOM_DEPTH,
        "max_level_reached": report["max_level_reached"],
        "cycle_found": bool(report["cycles"]),
        "cycles": report["cycles"],
        "depth_limit_reached": bool(report["depth_limited_pns"]),
        "depth_limited_pns": sorted(report["depth_limited_pns"]),
        "items": items,
    }


@protected.get("/parts/{pn}/cost")
def api_v1_part_cost(pn: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    parent = _get_part_or_404(db, pn)

    # Logica di costo invariata: si riusa compute_unit_cost di app/bom.py.
    res = compute_unit_cost(db, parent.pn, cache={}, visiting=[])

    return {
        "pn": parent.pn,
        "unit_cost": _decimal(res.cost),
        "valuta": parent.valuta,
        "missing_cost_pns": sorted(res.missing_cost_pns),
        "cycle_found": res.cycle_found,
        "cycle_path": list(res.cycle_path),
    }


router.include_router(protected)
