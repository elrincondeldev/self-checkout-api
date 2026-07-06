# Self-Checkout API — Clothing Shop

FastAPI backend for an NFC-based clothing-store self-checkout. Every garment
carries its own NFC sticker; an **ESP32** reads it, the **kiosk UI** receives
the product in real time over WebSocket, and completed purchases are stored in
**PostgreSQL** (hosted on Railway).

**Tag model:** one sticker = one physical garment. Many stickers map to the
same product (five identical t-shirts → five tags → one product with stock 5)
via the `product_tags` table. Sticker UIDs are factory-burned — "registering"
a garment means linking its UID to a product in the database.

```
┌────────┐   POST /scan    ┌─────────┐   WS push {event: scan}   ┌──────────┐
│ ESP32  │ ──────────────▶ │   API   │ ────────────────────────▶ │ Kiosk UI │
│ (NFC)  │ ◀────────────── │ FastAPI │                           │  (cart)  │
└────────┘  product | 404  └────┬────┘ ◀──────────────────────── └──────────┘
                                │           POST /checkout
                                ▼
                          ┌──────────┐
                          │ Postgres │  products · transactions · items
                          └──────────┘
```

---

## Table of contents

- [Setup](#setup)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [Health](#health)
  - [Scan (ESP32)](#scan-esp32)
  - [WebSocket (kiosk UI)](#websocket-kiosk-ui)
  - [Products](#products)
  - [Checkout](#checkout)
  - [Transactions](#transactions)
- [Data model](#data-model)
- [Error reference](#error-reference)
- [Migrations](#migrations)
- [Deploying to Railway](#deploying-to-railway)
- [Project structure](#project-structure)

---

## Setup

Requires Python 3.12+.

```bash
git clone <repo-url> && cd self-checkout-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in real values (see Configuration)
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8123
```

Interactive Swagger docs: **http://localhost:8123/docs**

## Configuration

All settings come from `.env` (never commit this file — it is git-ignored).

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy Postgres URL. **Must use the `postgresql+psycopg://` scheme.** Local dev: Railway's public URL. Deployed on Railway: the internal URL. | `postgresql+psycopg://user:pass@host:5432/railway` |
| `API_KEY` | Shared secret required by `/scan` (`X-API-Key` header) | `a-long-random-string` |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins | `http://localhost:5173,https://kiosk.example.com` |

## Authentication

Only `/scan` requires auth in v1: header `X-API-Key: <API_KEY>`.
Wrong or missing key → `401 {"detail": "Invalid or missing API key"}`.

Product management and checkout are open — fine on a trusted LAN kiosk;
add auth before exposing to the internet.

---

## Endpoints

### Health

```
GET /health
```

Liveness check + database ping. Use as Railway healthcheck path.

```json
{ "status": "ok", "database": "ok" }
```

`database` is `"unreachable"` when Postgres can't be reached (HTTP status stays 200).

---

### Scan (ESP32)

```
POST /scan
X-API-Key: <key>
Content-Type: application/json

{ "tag_id": "04:A3:2B:1C" }
```

Looks up an **active** product owning that tag (via `product_tags`). On
success the result is returned to the ESP32 **and** broadcast to every kiosk
UI connected on `/ws`.

**200 — product found:**

```json
{
  "tag_id": "A0:D6:8E:39",
  "product": {
    "id": 1,
    "name": "Basic T-Shirt",
    "description": "100% cotton crew neck",
    "category": "t-shirts",
    "size": "M",
    "color": "black",
    "price": "12.99",
    "stock": 10,
    "is_active": true,
    "nfc_tag_ids": ["A0:D6:8E:39"],
    "created_at": "2026-07-05T20:21:34.408239Z",
    "updated_at": "2026-07-06T14:58:09.046964Z"
  }
}
```

| Status | Meaning | ESP32 action |
|---|---|---|
| 200 | Product found + pushed to UI | Happy beep |
| 404 | Unknown tag, or product soft-deleted | Error beep |
| 401 | Bad/missing `X-API-Key` | Check firmware config |

On 404 the API broadcasts `{"event": "unknown_tag", "tag_id": "..."}` to the
kiosk (which shows the UID on screen) — nothing is broadcast on 401.

#### `GET /scans/recent`

Last 50 scans, newest first, known and unknown alike — the operator's tool
for registering new garments: scan the sticker, read its UID here (or off
the kiosk toast), create the product with it.

```json
[
  { "tag_id": "DE:AD:BE:EF", "known": false, "product_id": null,
    "product_name": null, "scanned_at": "2026-07-06T16:02:12.210139+00:00" },
  { "tag_id": "A0:D6:8E:39", "known": true, "product_id": 1,
    "product_name": "Basic T-Shirt", "scanned_at": "2026-07-06T16:02:11.922047+00:00" }
]
```

In-memory only — the list resets when the API restarts.

**Arduino-style sketch of the call:**

```cpp
HTTPClient http;
http.begin("http://<api-host>:8123/scan");
http.addHeader("Content-Type", "application/json");
http.addHeader("X-API-Key", API_KEY);
int code = http.POST("{\"tag_id\":\"" + tagId + "\"}");
// 200 = ok, 404 = unknown tag, 401 = bad key
```

---

### WebSocket (kiosk UI)

```
WS /ws
```

Listen-only stream of scan events. Every successful `/scan` produces:

```json
{
  "event": "scan",
  "tag_id": "A0:D6:8E:39",
  "product": { "...": "same shape as the /scan response product" }
}
```

`tag_id` identifies the **physical garment**. Since each sticker is one item,
the UI should treat a repeated `tag_id` as "already in cart" instead of
incrementing quantity — different tags of the same product stack normally.

**Frontend example:**

```js
const ws = new WebSocket("ws://<api-host>:8123/ws");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.event === "scan") addToCart(msg.product);
};
```

Prices are decimal **strings** (`"1.75"`) to avoid float rounding — parse with
care, never `float` them for money math.

---

### Products

Product management (register NFC tags, prices, stock).

#### `GET /products`

| Query param | Default | Description |
|---|---|---|
| `include_inactive` | `false` | Also return soft-deleted products |
| `category` | — | Filter by category (e.g. `t-shirts`) |
| `limit` | `100` | Page size (1–500) |
| `offset` | `0` | Pagination offset |

Returns an array of product objects (shape as in `/scan` 200 response).

#### `GET /products/{id}`

Single product. `404` if the id doesn't exist.

#### `POST /products` → `201`

```json
{
  "name": "Classic Hoodie",
  "description": "Fleece-lined pullover hoodie",
  "category": "hoodies",
  "size": "L",
  "color": "grey",
  "price": "29.99",
  "stock": 5,
  "nfc_tag_id": "9C:4C:52:07"
}
```

`description`, `category`, `size`, `color`, `stock` (default 0) and
`is_active` (default true) are optional. `price` must be > 0 with max 2
decimal places. `nfc_tag_id` optionally registers the first sticker along
with the product — add the rest via the tags endpoints below (`409` if the
sticker already belongs to a product).

#### `PATCH /products/{id}`

Partial update — send only the fields to change:

```json
{ "price": "24.99", "stock": 8 }
```

#### `DELETE /products/{id}`

**Soft delete**: sets `is_active = false` and returns the updated product.
The row stays (transaction history references it), its tags stop scanning,
and it disappears from default listings. Reactivate with
`PATCH {"is_active": true}`.

#### Tags — one row per physical sticker

| Method | Path | Purpose |
|---|---|---|
| GET | `/products/{id}/tags` | List stickers registered to a product |
| POST | `/products/{id}/tags` | Register another unit: `{"nfc_tag_id": "..."}` → 201, or 409 if taken |
| DELETE | `/products/{id}/tags/{nfc_tag_id}` | Unregister a sticker → 204 |

Typical flow for 5 identical shirts: create the product once (first sticker
inline), then `POST /products/{id}/tags` for the other four.

---

### Checkout

```
POST /checkout
Content-Type: application/json

{
  "items": [
    { "product_id": 1, "quantity": 2 },
    { "product_id": 2, "quantity": 1 }
  ]
}
```

Completes a purchase. Guarantees:

- **Total recomputed server-side** from current DB prices — any client-sent
  total is ignored by design.
- **Duplicate lines merged** — two entries for product 1 become quantity 2.
- **Row locking** (`SELECT … FOR UPDATE`) — concurrent checkouts cannot
  oversell the same stock.
- **Price snapshot** — `unit_price` is copied onto each item, so receipts
  stay correct after price changes.
- **All-or-nothing** — any invalid item aborts the whole purchase; stock is
  never partially decremented.

**201 — receipt:**

```json
{
  "id": 1,
  "total": "5.75",
  "status": "completed",
  "created_at": "2026-07-05T20:25:41.038090Z",
  "items": [
    { "product_id": 1, "quantity": 2, "unit_price": "1.75", "subtotal": "3.50" },
    { "product_id": 2, "quantity": 1, "unit_price": "2.25", "subtotal": "2.25" }
  ]
}
```

**409 — stock or product problem** (nothing saved):

```json
{ "detail": "Insufficient stock for 'Coca-Cola 500ml': have 22, need 999" }
```

```json
{ "detail": "Product 42 not found or inactive" }
```

**422** — empty `items` array or `quantity < 1` (request never reaches the DB).

---

### Transactions

#### `GET /transactions`

Purchase history, newest first. Query params: `limit` (default 50, max 200),
`offset`. Each entry has the full receipt shape shown above.

#### `GET /transactions/{id}`

Single receipt. `404` if not found.

---

## Data model

```
products                        product_tags (1 sticker = 1 garment)
├── id            serial PK     ├── id          serial PK
├── name                        ├── nfc_tag_id  unique, idx
├── description                 ├── product_id  FK → products
├── category      idx           └── created_at  timestamptz
├── size
├── color                       transactions
├── price         numeric(10,2) ├── id          serial PK
├── stock         int           ├── total       numeric(10,2)
├── is_active     bool          ├── status      completed | cancelled
├── created_at    timestamptz   └── created_at  timestamptz
└── updated_at    timestamptz
                                transaction_items
                                ├── id             serial PK
                                ├── transaction_id FK → transactions
                                ├── product_id     FK → products
                                ├── quantity       int
                                ├── unit_price     numeric(10,2)  ← snapshot
                                └── subtotal       numeric(10,2)
```

## Error reference

Errors are always `{ "detail": "<message>" }` (FastAPI validation errors on
422 return a structured list instead).

| Status | Where | Meaning |
|---|---|---|
| 401 | `/scan` | Bad or missing `X-API-Key` |
| 404 | `/scan`, `/products/{id}`, `/transactions/{id}` | Resource not found / inactive tag |
| 409 | `POST /products`, `POST /products/{id}/tags` | NFC sticker already assigned |
| 409 | `/checkout` | Insufficient stock, or unknown/inactive product |
| 422 | any | Request body failed validation |

## Migrations

Schema changes go through Alembic:

```bash
# after editing app/models.py
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

`alembic check` verifies models and DB are in sync.

## Deploying to Railway

1. New Railway service from this repo.
2. Variables: set `DATABASE_URL` to the **internal** URL (add the
   `+psycopg` scheme: `postgresql+psycopg://...@postgres.railway.internal:5432/railway`),
   plus `API_KEY` and `CORS_ORIGINS`.
3. Start command:
   ```
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
4. Healthcheck path: `/health`.

## Project structure

```
app/
  main.py               # app factory, CORS, router mounting, /health
  config.py             # settings loaded from .env
  database.py           # engine, session dependency, Base
  models.py             # SQLAlchemy models
  schemas.py            # Pydantic request/response schemas
  deps.py               # X-API-Key dependency
  ws.py                 # WebSocket connection manager
  routers/
    products.py         # products CRUD
    scan.py             # POST /scan + WS /ws
    checkout.py         # POST /checkout + transactions
alembic/                # migrations
firmware/               # ESP32-CAM + PN532 scanner sketch (see firmware/README.md)
requirements.txt
.env.example
```
