from __future__ import annotations
from __future__ import annotations

import csv
from contextlib import closing
import hmac
import io
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import count
from math import hypot
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Inspire2Door Simulation API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(os.getenv("INSPIRE2DOOR_DB_PATH", Path(__file__).parent / "data" / "catalog.db"))
MERCHANT_IMPORT_TOKEN = os.getenv("MERCHANT_IMPORT_TOKEN", "")
BASE_CATEGORIES = ["Clothing", "Accessories", "Home", "Plants", "Food", "Beauty", "Books", "Gifts"]
CSV_COLUMNS = {"sku", "name", "category", "price", "merchant", "neighborhood", "stock_count"}


def _connect_catalog() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS merchant_items (
            merchant TEXT NOT NULL,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price TEXT NOT NULL,
            neighborhood TEXT NOT NULL,
            stock_count INTEGER NOT NULL CHECK (stock_count >= 0),
            image_url TEXT NOT NULL,
            tags TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (merchant, sku)
        )"""
    )
    connection.commit()
    return connection


def import_merchant_csv(csv_text: str) -> dict[str, Any]:
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames:
            reader.fieldnames = [header.strip() for header in reader.fieldnames]
        headers = {header.strip() for header in (reader.fieldnames or []) if header}
        missing = CSV_COLUMNS - headers
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required CSV columns: {', '.join(sorted(missing))}")

        rows = list(reader)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV has no inventory rows")
        if len(rows) > 5000:
            raise HTTPException(status_code=413, detail="CSV is limited to 5,000 inventory rows")

        imported_at = datetime.now(timezone.utc).isoformat()
        records = []
        for line_number, row in enumerate(rows, start=2):
            values = {key.strip(): (value or "").strip() for key, value in row.items() if key}
            required_values = [values.get(key, "") for key in CSV_COLUMNS]
            if any(not value for value in required_values):
                raise HTTPException(status_code=400, detail=f"Missing required value on CSV row {line_number}")
            category = next((known for known in BASE_CATEGORIES if known.casefold() == values["category"].casefold()), None)
            if category is None:
                raise HTTPException(status_code=400, detail=f"Unsupported category on CSV row {line_number}")
            try:
                price = Decimal(values["price"])
                stock_count = int(values["stock_count"])
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid price or stock_count on CSV row {line_number}") from None
            if not price.is_finite() or price < 0 or price > Decimal("1000000000"):
                raise HTTPException(status_code=400, detail=f"Price is out of range on CSV row {line_number}")
            if stock_count < 0 or stock_count > 100000:
                raise HTTPException(status_code=400, detail=f"stock_count is out of range on CSV row {line_number}")

            image_url = values.get("image_url", "")
            if image_url and urlparse(image_url).scheme not in {"http", "https"}:
                raise HTTPException(status_code=400, detail=f"image_url must use http or https on CSV row {line_number}")
            records.append((
                values["merchant"], values["sku"], values["name"], category,
                str(price), values["neighborhood"], stock_count, image_url,
                json.dumps([tag.strip() for tag in values.get("tags", "").split(",") if tag.strip()]),
                imported_at,
            ))

        with closing(_connect_catalog()) as connection:
            connection.executemany(
                """INSERT INTO merchant_items
                    (merchant, sku, name, category, price, neighborhood, stock_count, image_url, tags, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(merchant, sku) DO UPDATE SET
                        name=excluded.name, category=excluded.category, price=excluded.price,
                        neighborhood=excluded.neighborhood, stock_count=excluded.stock_count,
                        image_url=excluded.image_url, tags=excluded.tags, updated_at=excluded.updated_at""",
                records,
            )
            connection.commit()
        return {"source": "merchant_csv", "upserted": len(records), "imported_at": imported_at}
    except HTTPException:
        raise
    except csv.Error as error:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {error}") from error


def _merchant_catalog_items() -> list[dict[str, Any]]:
    with closing(_connect_catalog()) as connection:
        rows = connection.execute("SELECT * FROM merchant_items WHERE stock_count > 0").fetchall()
    return [
        {
            "id": f"merchant:{row['merchant']}:{row['sku']}",
            "name": row["name"],
            "category": row["category"],
            "price": float(row["price"]),
            "merchant": row["merchant"],
            "neighborhood": row["neighborhood"],
            "eta_minutes": None,
            "stock_count": row["stock_count"],
            "image_url": row["image_url"],
            "tags": json.loads(row["tags"]),
            "popularity": 50,
            "source": "merchant_csv",
            "inventory_updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _public_merchant_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in {"shop", "prep_minutes", "popularity"}}


def _matches_terms(item: dict[str, Any], query: str | None) -> bool:
    terms = query.casefold().split() if query else []
    searchable = " ".join([item["name"], item["category"], *item["tags"]]).casefold()
    return all(term in searchable for term in terms)

# Coordinates are synthetic local kilometres, not real merchant locations.
ITEMS: list[dict[str, Any]] = [
    {"id": "look-101", "name": "Moss linen co-ord", "category": "Clothing", "price": 1890, "merchant": "Common Thread Studio", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 24, "image_url": "https://images.unsplash.com/photo-1539109136881-3be0616acf4b?auto=format&fit=crop&w=800&q=80", "tags": ["linen", "green", "co-ord", "summer", "clothing"], "popularity": 84, "prep_minutes": 6, "shop": [1.2, 1.8]},
    {"id": "look-102", "name": "Hand-thrown Sunday mug", "category": "Home", "price": 780, "merchant": "Clay Habit", "neighborhood": "Brookefield (simulation)", "eta_minutes": 31, "image_url": "https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?auto=format&fit=crop&w=800&q=80", "tags": ["ceramic", "mug", "pottery", "home", "coffee"], "popularity": 63, "prep_minutes": 4, "shop": [2.4, 1.1]},
    {"id": "look-103", "name": "Chilli crisp rice bowl", "category": "Food", "price": 290, "merchant": "Little Sesame Kitchen", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 19, "image_url": "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=800&q=80", "tags": ["spicy", "rice", "chilli", "lunch", "food"], "popularity": 95, "prep_minutes": 11, "shop": [0.8, 1.4]},
    {"id": "look-104", "name": "Terracotta table lamp", "category": "Home", "price": 2450, "merchant": "House of Laterite", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 35, "image_url": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?auto=format&fit=crop&w=800&q=80", "tags": ["lamp", "terracotta", "lighting", "home", "handmade"], "popularity": 58, "prep_minutes": 5, "shop": [3.1, 2.5]},
    {"id": "look-105", "name": "Everyday striped tote", "category": "Accessories", "price": 950, "merchant": "Sunday Supply", "neighborhood": "Brookefield (simulation)", "eta_minutes": 27, "image_url": "https://images.unsplash.com/photo-1590874103328-eac38a683ce7?auto=format&fit=crop&w=800&q=80", "tags": ["tote", "bag", "canvas", "stripes", "accessories"], "popularity": 74, "prep_minutes": 3, "shop": [2.2, 0.9]},
    {"id": "look-106", "name": "Cardamom cold coffee", "category": "Food", "price": 210, "merchant": "Soft Corner Cafe", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 16, "image_url": "https://images.unsplash.com/photo-1461023058943-07fcbe16d735?auto=format&fit=crop&w=800&q=80", "tags": ["coffee", "cardamom", "drink", "cafe", "food"], "popularity": 89, "prep_minutes": 7, "shop": [0.6, 1.0]},
    {"id": "look-107", "name": "Palm-print cotton shirt", "category": "Clothing", "price": 1590, "merchant": "Common Thread Studio", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 24, "image_url": "https://images.unsplash.com/photo-1598033129183-c4f50c736f10?auto=format&fit=crop&w=800&q=80", "tags": ["cotton", "shirt", "print", "green", "clothing"], "popularity": 71, "prep_minutes": 6, "shop": [1.2, 1.8]},
    {"id": "look-108", "name": "Woven cane catch-all", "category": "Home", "price": 620, "merchant": "House of Laterite", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 35, "image_url": "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?auto=format&fit=crop&w=800&q=80", "tags": ["woven", "cane", "basket", "storage", "home"], "popularity": 52, "prep_minutes": 4, "shop": [3.1, 2.5]},
    {"id": "look-109", "name": "Amber acetate sunglasses", "category": "Accessories", "price": 1290, "merchant": "Sunday Supply", "neighborhood": "Brookefield (simulation)", "eta_minutes": 27, "image_url": "https://images.unsplash.com/photo-1511499767150-a48a237f0083?auto=format&fit=crop&w=800&q=80", "tags": ["sunglasses", "amber", "eyewear", "accessories"], "popularity": 67, "prep_minutes": 3, "shop": [2.2, 0.9]},
    {"id": "look-110", "name": "Rosehip face oil", "category": "Beauty", "price": 890, "merchant": "Kindred Botanics", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 22, "image_url": "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?auto=format&fit=crop&w=800&q=80", "tags": ["skincare", "rosehip", "face oil", "beauty"], "popularity": 73, "prep_minutes": 3, "shop": [1.4, 1.2]},
    {"id": "look-111", "name": "Calendula hand balm", "category": "Beauty", "price": 420, "merchant": "Kindred Botanics", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 22, "image_url": "https://images.unsplash.com/photo-1608571423902-eed4a5ad8108?auto=format&fit=crop&w=800&q=80", "tags": ["balm", "calendula", "hand care", "beauty"], "popularity": 61, "prep_minutes": 3, "shop": [1.4, 1.2]},
    {"id": "look-112", "name": "A Field Guide to Slow Days", "category": "Books", "price": 640, "merchant": "Paper Plane Books", "neighborhood": "Brookefield (simulation)", "eta_minutes": 28, "image_url": "https://images.unsplash.com/photo-1544947950-fa07a98d237f?auto=format&fit=crop&w=800&q=80", "tags": ["book", "reading", "journaling", "books"], "popularity": 69, "prep_minutes": 2, "shop": [2.5, 1.4]},
    {"id": "look-113", "name": "Pocket sketchbook set", "category": "Books", "price": 380, "merchant": "Paper Plane Books", "neighborhood": "Brookefield (simulation)", "eta_minutes": 28, "image_url": "https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=800&q=80", "tags": ["sketchbook", "notebook", "paper", "books"], "popularity": 57, "prep_minutes": 2, "shop": [2.5, 1.4]},
    {"id": "look-114", "name": "Mini monstera", "category": "Plants", "price": 550, "merchant": "Little Leaf Room", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 23, "image_url": "https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=800&q=80", "tags": ["plant", "monstera", "green", "indoor", "plants"], "popularity": 78, "prep_minutes": 4, "shop": [1.1, 2.0]},
    {"id": "look-115", "name": "Basil starter pot", "category": "Plants", "price": 290, "merchant": "Little Leaf Room", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 23, "image_url": "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?auto=format&fit=crop&w=800&q=80", "tags": ["herb", "basil", "plant", "garden", "plants"], "popularity": 62, "prep_minutes": 4, "shop": [1.1, 2.0]},
    {"id": "look-116", "name": "Evening glow candle set", "category": "Gifts", "price": 720, "merchant": "Small Hours Studio", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 33, "image_url": "https://images.unsplash.com/photo-1603006905003-be475563bc59?auto=format&fit=crop&w=800&q=80", "tags": ["candle", "gift", "home fragrance", "gifts"], "popularity": 66, "prep_minutes": 4, "shop": [3.0, 2.2]},
    {"id": "look-117", "name": "Chocolate tasting box", "category": "Gifts", "price": 980, "merchant": "Cocoa & Co.", "neighborhood": "AECS Layout (simulation)", "eta_minutes": 20, "image_url": "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=800&q=80", "tags": ["chocolate", "gift box", "cocoa", "gifts"], "popularity": 81, "prep_minutes": 5, "shop": [0.9, 1.7]},
]
INITIAL_STOCK_COUNTS = {item["id"]: 2 + index % 4 for index, item in enumerate(ITEMS)}
STOCK_COUNTS = INITIAL_STOCK_COUNTS.copy()

RIDERS = [
    {"name": "Rider Asha", "position": [0.4, 1.6]},
    {"name": "Rider Kabir", "position": [2.8, 0.7]},
    {"name": "Rider Nila", "position": [3.7, 2.9]},
]
CUSTOMER_POSITION = [2.0, 3.2]
CATEGORY_INTEREST = {
    "Clothing": 1.0,
    "Accessories": 0.94,
    "Beauty": 0.9,
    "Home": 0.84,
    "Plants": 0.82,
    "Gifts": 0.8,
    "Food": 0.76,
    "Books": 0.74,
}
ORDER_SEQUENCE = count(1)


class VisualSearchRequest(BaseModel):
    filename: str


class CheckoutRequest(BaseModel):
    item_ids: list[str]


def _item_score(item: dict[str, Any]) -> float:
    interest = CATEGORY_INTEREST.get(item["category"], 0.5)
    eta_minutes = item.get("eta_minutes")
    eta_penalty = eta_minutes * 0.35 if eta_minutes is not None else 0
    return item.get("popularity", 50) * 0.65 + interest * 20 - eta_penalty


def rank_and_diversify(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use a deterministic interest-weighted score, then round-robin categories."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(items, key=_item_score, reverse=True):
        groups.setdefault(item["category"], []).append(item)

    ranked: list[dict[str, Any]] = []
    while groups:
        for category in list(groups):
            ranked.append(groups[category].pop(0))
            if not groups[category]:
                del groups[category]
    return ranked


def list_items(
    q: str | None = None,
    category: str | None = None,
    ranker: Literal["diverse", "popular"] = "diverse",
) -> list[dict[str, Any]]:
    results = [item for item in ITEMS if STOCK_COUNTS[item["id"]] > 0]
    if category:
        results = [item for item in results if item["category"].casefold() == category.casefold()]
    if q:
        terms = q.casefold().split()
        results = [
            item for item in results
            if all(term in " ".join([item["name"], item["category"], *item["tags"]]).casefold() for term in terms)
        ]
    if ranker == "popular":
        return sorted(results, key=lambda item: item["popularity"], reverse=True)
    return rank_and_diversify(results)


def visual_search(filename: str) -> list[dict[str, Any]]:
    """Filename/tag lexical match only; no image pixels or embeddings are used."""
    terms = [term for term in filename.casefold().replace("_", " ").replace("-", " ").rsplit(".", 1)[0].split() if len(term) > 2]
    scored = []
    for item in ITEMS:
        if STOCK_COUNTS[item["id"]] == 0:
            continue
        searchable = " ".join([item["name"], item["category"], *item["tags"]]).casefold()
        score = sum(term in searchable for term in terms)
        scored.append((score, item))
    scored = [entry for entry in scored if entry[0] > 0]
    return [item for _, item in sorted(scored, key=lambda entry: (entry[0], _item_score(entry[1])), reverse=True)]


def create_order(item_ids: list[str]) -> dict[str, Any]:
    requested_counts = Counter(item_ids)
    if not requested_counts:
        raise HTTPException(status_code=400, detail="Add at least one synthetic item")
    items_by_id = {item["id"]: item for item in ITEMS}
    if any(item_id not in items_by_id for item_id in requested_counts):
        raise HTTPException(status_code=404, detail="Synthetic item not found")
    if any(STOCK_COUNTS[item_id] < quantity for item_id, quantity in requested_counts.items()):
        raise HTTPException(status_code=409, detail="Synthetic stock is no longer available")

    route_items = [items_by_id[item_id] for item_id in item_ids]
    first_shop = route_items[0]["shop"]
    rider = min(RIDERS, key=lambda candidate: hypot(candidate["position"][0] - first_shop[0], candidate["position"][1] - first_shop[1]))
    route = [first_shop, *(item["shop"] for item in route_items[1:]), CUSTOMER_POSITION]
    distance_km = hypot(rider["position"][0] - first_shop[0], rider["position"][1] - first_shop[1])
    distance_km += sum(hypot(end[0] - start[0], end[1] - start[1]) for start, end in zip(route, route[1:]))
    prep_minutes = sum(item["prep_minutes"] for item in route_items)
    eta_minutes = round(prep_minutes + 4 + distance_km / 20 * 60)
    for item_id, quantity in requested_counts.items():
        STOCK_COUNTS[item_id] -= quantity
    return {
        "order_id": f"SIM-{next(ORDER_SEQUENCE):04d}",
        "rider": rider["name"],
        "item_count": len(route_items),
        "eta_minutes": eta_minutes,
        "distance_km": round(distance_km, 1),
        "baseline": "nearest rider to first shop + bag-order multi-stop straight-line travel at 20 km/h + synthetic prep time",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-simulation"}


@app.post("/api/merchant-catalog/import")
async def post_merchant_catalog_import(request: Request) -> dict[str, Any]:
    supplied_token = request.headers.get("x-merchant-import-token", "")
    if not MERCHANT_IMPORT_TOKEN or not hmac.compare_digest(supplied_token, MERCHANT_IMPORT_TOKEN):
        raise HTTPException(status_code=401, detail="Merchant CSV import is disabled or the import token is invalid")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type != "text/csv":
        raise HTTPException(status_code=415, detail="Upload a CSV file with Content-Type: text/csv")
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 2_000_000:
        raise HTTPException(status_code=413, detail="CSV upload is limited to 2 MB")
    body = await request.body()
    if len(body) > 2_000_000:
        raise HTTPException(status_code=413, detail="CSV upload is limited to 2 MB")
    try:
        csv_text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from error
    return import_merchant_csv(csv_text)


@app.get("/api/items")
def get_items(
    q: str | None = Query(default=None, description="All terms must match item name, category, or tags"),
    category: str | None = None,
    ranker: Literal["diverse", "popular"] = "diverse",
) -> list[dict[str, Any]]:
    merchant_items = [
        item for item in _merchant_catalog_items()
        if (not category or item["category"].casefold() == category.casefold()) and _matches_terms(item, q)
    ]
    catalog_items = [
        {**_public_merchant_item(item), "stock_count": STOCK_COUNTS[item["id"]], "source": "simulation"}
        for item in list_items(q, category, ranker)
    ] + merchant_items
    if ranker == "popular":
        catalog_items.sort(key=lambda item: item.get("popularity", 50), reverse=True)
        return catalog_items
    return [_public_merchant_item(item) for item in rank_and_diversify(catalog_items)]


@app.post("/api/visual-search")
def post_visual_search(request: VisualSearchRequest) -> list[dict[str, Any]]:
    filename_query = request.filename.casefold().replace("_", " ").replace("-", " ").rsplit(".", 1)[0]
    merchant_items = [item for item in _merchant_catalog_items() if _matches_terms(item, filename_query)]
    return [
        {**_public_merchant_item(item), "stock_count": STOCK_COUNTS[item["id"]], "source": "simulation"}
        for item in visual_search(request.filename)
    ] + merchant_items


@app.post("/api/checkout")
def checkout(request: CheckoutRequest) -> dict[str, Any]:
    return create_order(request.item_ids)