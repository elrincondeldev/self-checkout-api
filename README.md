# Self-Checkout API

FastAPI backend for an NFC self-checkout system: an ESP32 scans product tags,
the kiosk UI receives them in real time over WebSocket, and completed
purchases are stored in PostgreSQL (Railway).

## Flow

```
ESP32 ──POST /scan──▶ API ──WebSocket push──▶ Kiosk UI (cart)
                       │                          │
                       ▼                          ▼ POST /checkout
                  PostgreSQL ◀── transaction + items, stock decrement
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL and API_KEY
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8123
```

Interactive docs: http://localhost:8123/docs

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/scan` | `X-API-Key` | ESP32 sends `{"tag_id": "..."}`; product returned + pushed to UI |
| WS | `/ws` | — | Kiosk UI receives `{"event":"scan","product":{...}}` |
| POST | `/checkout` | — | `{"items":[{"product_id":1,"quantity":2}]}` → transaction |
| GET | `/transactions` | — | Purchase history |
| GET | `/transactions/{id}` | — | Receipt detail |
| GET/POST | `/products` | — | List / register products |
| GET/PATCH/DELETE | `/products/{id}` | — | Manage products (DELETE = soft delete) |
| GET | `/health` | — | Liveness + DB ping |

## ESP32 integration

```
POST http://<api-host>/scan
Headers: X-API-Key: <key>
         Content-Type: application/json
Body:    {"tag_id": "04:A3:2B:1C"}
```

Responses: `200` product found · `404` unknown tag · `401` bad key.

## Checkout guarantees

- Total recomputed server-side from current DB prices — client totals ignored.
- Product rows locked (`SELECT ... FOR UPDATE`) — concurrent checkouts cannot oversell.
- Price snapshotted per item — receipts survive later price changes.
- Any validation failure (stock, unknown/inactive product) aborts the whole
  transaction; stock untouched.

## Migrations

```bash
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```
