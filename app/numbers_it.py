"""Lettura dei numeri inseriti a mano o importati da CSV.

Accetta sia il formato italiano (1.234,56) sia quello internazionale (1234.56).
Un valore che non si riesce a interpretare con certezza genera ValueError:
meglio un errore visibile che un prezzo cancellato o letto mille volte piu piccolo.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_STRIP = ("€", "EUR", "eur", " ", " ", " ", "'")


class AmbiguousNumber(ValueError):
    pass


def parse_number(raw: str | None, label: str = "Valore") -> Decimal | None:
    """Restituisce un Decimal, None se il campo e vuoto, ValueError se non e interpretabile."""
    if raw is None:
        return None
    s = str(raw).strip()
    for token in _STRIP:
        s = s.replace(token, "")
    if not s:
        return None

    sign = ""
    if s[0] in "+-":
        sign, s = s[0], s[1:]
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        raise ValueError(f"{label}: valore non numerico ({raw}).")

    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        # il separatore che compare per ultimo e quello decimale
        if s.rfind(",") > s.rfind("."):
            thousands, decimal = ".", ","
        else:
            thousands, decimal = ",", "."
        integer, _, frac = s.rpartition(decimal)
        if decimal in integer or not _valid_grouping(integer, thousands):
            raise ValueError(f"{label}: formato non valido ({raw}).")
        s = integer.replace(thousands, "") + "." + frac
    elif has_comma:
        if s.count(",") > 1:
            if not _valid_grouping(s, ","):
                raise ValueError(f"{label}: formato non valido ({raw}).")
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        if s.count(".") > 1:
            if not _valid_grouping(s, "."):
                raise ValueError(f"{label}: formato non valido ({raw}).")
            s = s.replace(".", "")
        else:
            integer, _, frac = s.partition(".")
            # "1.234" puo essere 1234 (migliaia italiane) o 1,234: non si indovina
            if len(frac) == 3 and integer not in ("", "0"):
                raise AmbiguousNumber(
                    f"{label}: «{raw}» e ambiguo (1234 o 1,234?). Scrivi 1234 oppure 1,234."
                )

    try:
        value = Decimal(sign + s)
    except InvalidOperation:
        raise ValueError(f"{label}: valore non numerico ({raw}).")
    if not value.is_finite():
        raise ValueError(f"{label}: valore non numerico ({raw}).")
    return value


def _valid_grouping(s: str, sep: str) -> bool:
    groups = s.split(sep)
    if not groups[0] or len(groups[0]) > 3:
        return False
    return all(len(g) == 3 for g in groups[1:])


def parse_positive(raw: str | None, label: str, allow_zero: bool = True) -> Decimal | None:
    value = parse_number(raw, label)
    if value is None:
        return None
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{label}: il valore deve essere {'positivo o zero' if allow_zero else 'maggiore di zero'}.")
    return value


def fmt_decimal(value, max_decimals: int = 6, min_decimals: int = 2) -> str:
    """Formato a video: almeno 2 decimali, al massimo max_decimals, senza zeri inutili."""
    if value is None:
        return ""
    d = Decimal(str(value)).quantize(Decimal(1).scaleb(-max_decimals))
    text = f"{d:.{max_decimals}f}"
    if "." in text:
        integer, frac = text.split(".")
        frac = frac.rstrip("0")
        if len(frac) < min_decimals:
            frac = frac.ljust(min_decimals, "0")
        text = integer + ("." + frac if frac else "")
    return text
