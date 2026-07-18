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
