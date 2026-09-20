"""Autenticazione service-to-service per l'API /api/v1.

Separata dall'autenticazione a sessione del browser (app/auth.py):
qui non esistono cookie di sessione, solo un token di servizio letto
dall'ambiente e confrontato in tempo costante.
"""

import hmac
import os

from fastapi import HTTPException, Request

API_TOKEN_ENV = "DEEPEX_PN_API_TOKEN"

# Messaggio unico: non distingue token assente, malformato o errato,
# per non esporre lo stato di configurazione del servizio.
_UNAUTHORIZED_DETAIL = "Invalid or missing service credentials"
_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def _configured_token() -> str:
    """Token di servizio configurato, letto a ogni richiesta (mai a import-time)."""
    return (os.environ.get(API_TOKEN_ENV) or "").strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=_UNAUTHORIZED_DETAIL,
        headers=_UNAUTHORIZED_HEADERS,
    )


def require_service_token(request: Request) -> str:
    """Dipendenza FastAPI per gli endpoint /api/v1 protetti.

    Fail closed: se DEEPEX_PN_API_TOKEN non e' configurato (assente o vuoto)
    nessuna credenziale puo' essere valida. Questo non impedisce l'avvio
    dell'applicazione ne' il funzionamento della UI browser.
    """
    expected = _configured_token()
    if not expected:
        raise _unauthorized()

    header = request.headers.get("Authorization") or ""
    scheme, _, credential = header.partition(" ")
    credential = credential.strip()

    if scheme.lower() != "bearer" or not credential:
        raise _unauthorized()

    if not hmac.compare_digest(credential.encode("utf-8"), expected.encode("utf-8")):
        raise _unauthorized()

    return credential
