# Inspire2Door (Simulation)

> This is a portfolio simulation, not a product or startup claim. Users, merchants, inventory, riders, orders, locations, and metrics are synthetic.

Inspire2Door is a portfolio simulation of hyperlocal visual commerce: browse a diverse local-style feed, search by text or an inspiration-image filename, and explore merchant-submitted stock around AECS Layout/Brookefield. A React/TypeScript frontend and FastAPI backend demonstrate category-diverse ranking, CSV-backed merchant inventory, and a separately labeled synthetic delivery simulator. It is not a live marketplace, has no retailer-app integrations, and makes no real-world performance or market-demand claims.

## Run

```bash
export MERCHANT_IMPORT_TOKEN='choose-a-long-local-random-value'
docker compose up --build
```

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/api/health

Run services independently:

```bash
# Web (Node 18+)
npm install
npm run dev -- --host 0.0.0.0 --port 3000

# API (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
export MERCHANT_IMPORT_TOKEN='choose-a-long-local-random-value'
.venv/bin/uvicorn main:app --app-dir api --reload --port 8000
```

## What's implemented

- Responsive visual-discovery feed with eight synthetic catalog categories, keyword search, saved items, and a local bag.
- Deterministic interest-weighted, category-diversifying ranker compared with a selectable popularity-only baseline.
- Visual-search interaction that matches the uploaded filename against synthetic item names and tags. It does not inspect image pixels or use embeddings.
- Synthetic stock counts, sold-out filtering, and checkout reservations across multi-item rider routes.
- Checkout simulation that assigns the closest synthetic rider and estimates travel time from fixed synthetic coordinates.
- Public Google Maps search link for AECS Layout/Brookefield; store listings open externally and are not scraped or persisted.
- Authenticated merchant CSV import with SQLite persistence, stock timestamps, and a downloadable template. Imported items are not eligible for simulated checkout or ETA.
- FastAPI endpoints with interactive OpenAPI docs and unit tests for the simulation logic.

## Merchant CSV import

Download [`merchant-inventory-template.csv`](public/merchant-inventory-template.csv), fill it with inventory you are authorized to use, set `MERCHANT_IMPORT_TOKEN` in the same environment as the API, enter that token in the page, then upload the CSV. Required columns are `sku,name,category,price,merchant,neighborhood,stock_count`; `image_url` and comma-separated `tags` are optional. Categories must match the eight catalog categories. Imports upsert by merchant and SKU and are stored in `api/data/catalog.db` (or the mounted Compose data directory).

Imported stock is only as current as the CSV's `inventory_updated_at`; this does not connect to a POS system or provide real-time synchronization. Never commit the import token or private merchant data.

## What's not implemented yet

Kafka/Redpanda, Redis feature serving, Parquet training data, vector search, learned ranking or ETA models, OR-Tools dispatch, fraud graphs, moderation, support agents, and demand forecasting are documented as future tiers. No performance number is claimed until a reproducible experiment and baseline are added.

See [architecture and trade-offs](docs/architecture.md), [image provenance](docs/image-sources.md), and the explicitly hypothetical [concierge pilot plan](docs/pilot-plan.md).
