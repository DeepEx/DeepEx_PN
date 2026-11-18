from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Set, List, Tuple

from sqlalchemy.orm import Session

from models import PartNumber, BOMItem

@dataclass
class CostResult:
    cost: Decimal
    missing_cost_pns: Set[str]
    cycle_found: bool
    cycle_path: List[str]

def _to_decimal(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def compute_unit_cost(db: Session, pn: str, cache: Dict[str, CostResult], visiting: List[str]) -> CostResult:
    """Costo unitario di un P/N.

    - Se il P/N ha righe di BOM, il costo e la somma della BOM (qty con scarto),
      qualunque sia la classificazione: un assieme non perde la distinta perche
      e stato importato o marcato BUY/STANDARD.
    - Senza BOM si usa costo_standard; se manca, il P/N e segnalato come mancante.
    La cache conserva anche l'elenco dei mancanti, cosi un componente presente
    in piu rami resta segnalato.
    """
    if pn in visiting:
        i = visiting.index(pn)
        return CostResult(cost=Decimal("0"), missing_cost_pns=set(), cycle_found=True, cycle_path=visiting[i:] + [pn])

    if pn in cache:
        return cache[pn]

    obj = db.get(PartNumber, pn)
    if not obj:
        return CostResult(cost=Decimal("0"), missing_cost_pns={pn}, cycle_found=False, cycle_path=[])

    rows = db.query(BOMItem).filter(BOMItem.parent_pn == pn).all()

    if not rows:
        if obj.costo_standard is None:
            res = CostResult(cost=Decimal("0"), missing_cost_pns={pn}, cycle_found=False, cycle_path=[])
        else:
            res = CostResult(cost=_to_decimal(obj.costo_standard), missing_cost_pns=set(), cycle_found=False, cycle_path=[])
        cache[pn] = res
        return res

    visiting.append(pn)
    total = Decimal("0")
    missing: Set[str] = set()
    for r in rows:
        child_res = compute_unit_cost(db, r.child_pn, cache, visiting)
        if child_res.cycle_found:
            visiting.pop()
            return child_res
        missing |= child_res.missing_cost_pns
        total += effective_qty(r) * child_res.cost
    visiting.pop()

    res = CostResult(cost=total, missing_cost_pns=missing, cycle_found=False, cycle_path=[])
    cache[pn] = res
    return res


def effective_qty(row: BOMItem) -> Decimal:
    qty = _to_decimal(row.qty)
    scrap = _to_decimal(row.scrap_pct) if row.scrap_pct is not None else Decimal("0")
    return qty * (Decimal("1") + (scrap / Decimal("100")))


def would_create_cycle(db: Session, parent_pn: str, child_pn: str) -> bool:
    """True se aggiungere child sotto parent crea un ciclo (child contiene gia parent)."""
    if parent_pn == child_pn:
        return True
    stack, seen = [child_pn], set()
    while stack:
        cur = stack.pop()
        if cur == parent_pn:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(r.child_pn for r in db.query(BOMItem).filter(BOMItem.parent_pn == cur).all())
    return False


@dataclass
class PhysicalResult:
    total: Decimal
    missing_pns: Set[str]
    cycle_found: bool
    cycle_path: List[str]


def compute_physical_rollup(db: Session, pn: str, attr: str, cache: Dict[str, PhysicalResult], visiting: List[str]) -> PhysicalResult:
    """Somma una proprieta fisica (es. massa_secco_g, peso_acqua_g) lungo la BOM.

    Un valore inserito direttamente sul P/N (anche di un assieme) ha la precedenza:
    una pesata dell'assieme intero vale piu della somma dei componenti.
    Se manca, si somma la BOM (qty, senza scarto); un P/N senza valore e senza BOM e mancante.
    """
    if pn in visiting:
        i = visiting.index(pn)
        return PhysicalResult(Decimal("0"), set(), True, visiting[i:] + [pn])
    if pn in cache:
        return cache[pn]

    obj = db.get(PartNumber, pn)
    if not obj:
        return PhysicalResult(Decimal("0"), {pn}, False, [])

    own = getattr(obj, attr)
    if own is not None:
        res = PhysicalResult(_to_decimal(own), set(), False, [])
        cache[pn] = res
        return res

    rows = db.query(BOMItem).filter(BOMItem.parent_pn == pn).all()
    if not rows:
        res = PhysicalResult(Decimal("0"), {pn}, False, [])
        cache[pn] = res
        return res

    visiting.append(pn)
    total = Decimal("0")
    missing: Set[str] = set()
    for r in rows:
        child = compute_physical_rollup(db, r.child_pn, attr, cache, visiting)
        if child.cycle_found:
            visiting.pop()
            return child
        missing |= child.missing_pns
        total += _to_decimal(r.qty) * child.total
    visiting.pop()
    res = PhysicalResult(total, missing, False, [])
    cache[pn] = res
    return res
