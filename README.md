# DeepEx PN

Applicazione web per la gestione di part number, revisioni, fornitori e distinte base.

## Requisiti

- Docker e Docker Compose

## Avvio

1. Copia `.env.example` in `.env`.
2. Sostituisci tutti i valori di esempio con credenziali sicure. Per `SECRET_KEY` usa una stringa casuale lunga.
3. Avvia i servizi:

   ```sh
   docker compose up --build
   ```

4. Apri <http://localhost:8088> e accedi con `ADMIN_USERNAME` e `ADMIN_PASSWORD`.

L'utente amministratore viene creato al primo avvio. I dati PostgreSQL restano nella cartella locale `postgres/`, esclusa da Git.

## API di servizio `/api/v1` (sola lettura)

L'API `/api/v1` e' il confine di integrazione machine-to-machine di DeepEx_PN,
pensata per **DeepEx-Orchestrator**. PostgreSQL resta privato dietro DeepEx_PN:
l'Orchestrator deve usare questa API e **non** collegarsi direttamente al database.

E' separata dalla UI browser: non usa la sessione/cookie di login, non serve
template e non modifica dati (tutti gli endpoint sono in sola lettura). La UI e
l'endpoint esistente `/api/pn/search` restano invariati.

### Autenticazione

- Token di servizio letto dall'ambiente: `DEEPEX_PN_API_TOKEN` (vedi `.env.example`).
- Protocollo: header `Authorization: Bearer <token>`, confronto a tempo costante.
- Tutti gli endpoint `/api/v1` richiedono il token, **eccetto** `/api/v1/health`.
- Fail closed: se `DEEPEX_PN_API_TOKEN` non e' configurato (assente o vuoto), gli
  endpoint protetti rispondono `401`. L'applicazione e la UI browser si avviano e
  funzionano comunque.
- Credenziali assenti, malformate o errate ricevono un `401` JSON.

### Endpoint

| Metodo e percorso | Auth | Descrizione |
| --- | --- | --- |
| `GET /api/v1/health` | no | Liveness check minimale per l'Orchestrator |
| `GET /api/v1/parts/search?q=&limit=` | si | Ricerca per P/N, descrizione o codice fornitore (case-insensitive); `limit` tra 1 e 50 |
| `GET /api/v1/parts/{pn}` | si | Dati del P/N; `404` JSON se sconosciuto |
| `GET /api/v1/parts/{pn}/bom` | si | Distinta base diretta; `404` JSON se il padre non esiste |
| `GET /api/v1/parts/{pn}/bom/recursive` | si | Espansione ricorsiva delle assemblee MAKE, con rilevamento cicli e profondita' massima riportati nel JSON |
| `GET /api/v1/parts/{pn}/cost` | si | Costo unitario calcolato, P/N senza costo, `cycle_found`, `cycle_path` |

### Esempio

```sh
curl -H "Authorization: Bearer replace-with-a-long-random-service-api-token" \
  "http://localhost:8088/api/v1/parts/search?q=PCB&limit=10"
```

## Struttura

```text
.
|-- app/                 # Applicazione FastAPI
|   |-- static/          # CSS e asset
|   |-- templates/       # Template Jinja
|   |-- Dockerfile
|   `-- requirements.txt
|-- docker-compose.yml
`-- .env.example
```
