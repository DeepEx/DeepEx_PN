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

def compute_unit_cost(db: Session, pn: str, cache: Dict[str, Decimal], visiting: List[str]) -> CostResult:
    # ciclo
    if pn in visiting:
        # path ciclo
        i = visiting.index(pn)
        return CostResult(cost=Decimal("0"), missing_cost_pns=set(), cycle_found=True, cycle_path=visiting[i:] + [pn])

    if pn in cache:
        return CostResult(cost=cache[pn], missing_cost_pns=set(), cycle_found=False, cycle_path=[])

    obj = db.get(PartNumber, pn)
    if not obj:
        return CostResult(cost=Decimal("0"), missing_cost_pns={pn}, cycle_found=False, cycle_path=[])

    visiting.append(pn)

    cls = (obj.classificazione or "").upper()

    # BUY/STANDARD: usa costo_standard
    if cls in ("BUY", "STANDARD"):
        if obj.costo_standard is None:
            visiting.pop()
            cache[pn] = Decimal("0")
            return CostResult(cost=Decimal("0"), missing_cost_pns={pn}, cycle_found=False, cycle_path=[])
        cost = _to_decimal(obj.costo_standard)
        visiting.pop()
        cache[pn] = cost
        return CostResult(cost=cost, missing_cost_pns=set(), cycle_found=False, cycle_path=[])

    # MAKE: somma BOM
    rows = db.query(BOMItem).filter(BOMItem.parent_pn == pn).all()
    total = Decimal("0")
    missing: Set[str] = set()

    if not rows:
        # MAKE senza BOM -> costo mancante
        visiting.pop()
        cache[pn] = Decimal("0")
        return CostResult(cost=Decimal("0"), missing_cost_pns={pn}, cycle_found=False, cycle_path=[])

    for r in rows:
        qty = _to_decimal(r.qty)
        scrap = _to_decimal(r.scrap_pct) if r.scrap_pct is not None else Decimal("0")
        qty_eff = qty * (Decimal("1") + (scrap / Decimal("100")))

        child_res = compute_unit_cost(db, r.child_pn, cache, visiting)
        if child_res.cycle_found:
            return child_res

        missing |= child_res.missing_cost_pns
        total += qty_eff * child_res.cost

    visiting.pop()
    cache[pn] = total
    return CostResult(cost=total, missing_cost_pns=missing, cycle_found=False, cycle_path=[])


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
