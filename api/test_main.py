import unittest
import asyncio
import tempfile
import unittest
from pathlib import Path

import main
from main import INITIAL_STOCK_COUNTS, STOCK_COUNTS, create_order, list_items, visual_search
from starlette.requests import Request


class SimulationTests(unittest.TestCase):
    def setUp(self):
        STOCK_COUNTS.clear()
        STOCK_COUNTS.update(INITIAL_STOCK_COUNTS)

    def test_feed_diversifies_categories(self):
        results = list_items()
        self.assertEqual(len(results), 17)
        self.assertNotEqual(results[0]["category"], results[1]["category"])

    def test_all_eight_categories_have_catalog_items(self):
        categories = {item["category"] for item in list_items()}
        self.assertEqual(categories, {"Clothing", "Accessories", "Home", "Plants", "Food", "Beauty", "Books", "Gifts"})
        for category in categories:
            self.assertTrue(list_items(category=category), category)

    def test_search_filters_by_all_terms(self):
        results = list_items(q="linen green")
        self.assertEqual([item["id"] for item in results], ["look-101"])

    def test_popularity_baseline_orders_by_popularity(self):
        results = list_items(ranker="popular")
        self.assertEqual(results[0]["id"], "look-103")
        self.assertEqual(results[1]["id"], "look-106")

    def test_visual_search_uses_filename_tokens(self):
        results = visual_search("terracotta-lamp.jpg")
        self.assertEqual(results[0]["id"], "look-104")

    def test_visual_search_without_matching_tokens_returns_no_items(self):
        self.assertEqual(visual_search("unknown-reference.png"), [])

    def test_dispatch_returns_explained_baseline(self):
        result = create_order(["look-101"])
        self.assertEqual(result["rider"], "Rider Asha")
        self.assertEqual(result["item_count"], 1)
        self.assertGreater(result["eta_minutes"], 0)
        self.assertIn("20 km/h", result["baseline"])

    def test_dispatch_includes_all_bag_items(self):
        result = create_order(["look-101", "look-102"])
        self.assertEqual(result["item_count"], 2)
        self.assertIn("multi-stop", result["baseline"])

    def test_checkout_reserves_synthetic_stock(self):
        before = STOCK_COUNTS["look-101"]
        create_order(["look-101"])
        self.assertEqual(STOCK_COUNTS["look-101"], before - 1)


class MerchantCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = main.DB_PATH
        main.DB_PATH = Path(self.temp_dir.name) / "catalog.db"

    def tearDown(self):
        main.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def make_csv_request(self, content: str, token: str = "") -> Request:
        async def receive():
            return {"type": "http.request", "body": content.encode(), "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/merchant-catalog/import",
                "headers": [(b"content-type", b"text/csv"), (b"x-merchant-import-token", token.encode())],
            },
            receive,
        )

    def test_import_route_requires_configured_token(self):
        original_token = main.MERCHANT_IMPORT_TOKEN
        main.MERCHANT_IMPORT_TOKEN = "local-test-token"
        content = "sku,name,category,price,merchant,neighborhood,stock_count\nsku-2,Tea blend,Food,250,Cedar Tea,AECS Layout,7\n"
        try:
            with self.assertRaises(main.HTTPException) as error:
                asyncio.run(main.post_merchant_catalog_import(self.make_csv_request(content)))
            self.assertEqual(error.exception.status_code, 401)
            result = asyncio.run(main.post_merchant_catalog_import(self.make_csv_request(content, "local-test-token")))
            self.assertEqual(result["upserted"], 1)
        finally:
            main.MERCHANT_IMPORT_TOKEN = original_token

    def test_import_persists_merchant_items_for_category_search(self):
        result = main.import_merchant_csv(
            "sku,name,category,price,merchant,neighborhood,stock_count,image_url,tags\n"
            "aecs-001,Fresh tulips,Plants,399,Green Corner,AECS Layout,12,,flowers, bouquet\n"
        )
        found = main.get_items(category="Plants", q="tulips", ranker="diverse")
        self.assertEqual(result["upserted"], 1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "merchant_csv")
        self.assertEqual(found[0]["stock_count"], 12)
        self.assertEqual(found[0]["eta_minutes"], None)

    def test_import_upserts_by_merchant_and_sku(self):
        main.import_merchant_csv(
            "sku,name,category,price,merchant,neighborhood,stock_count\n"
            "sku-1,Blue mug,Home,500,Clay Shop,AECS Layout,5\n"
        )
        main.import_merchant_csv(
            "sku,name,category,price,merchant,neighborhood,stock_count\n"
            "sku-1,Blue mug,Home,450,Clay Shop,AECS Layout,2\n"
        )
        found = [item for item in main.get_items(q=None, category="Home") if item["source"] == "merchant_csv"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["price"], 450)
        self.assertEqual(found[0]["stock_count"], 2)

    def test_import_rejects_bad_rows_without_writing_any_rows(self):
        invalid_csv = (
            "sku,name,category,price,merchant,neighborhood,stock_count\n"
            "sku-1,Blue mug,Home,500,Clay Shop,AECS Layout,5\n"
            "sku-2,Broken item,Unknown,10,Clay Shop,AECS Layout,1\n"
        )
        with self.assertRaises(main.HTTPException):
            main.import_merchant_csv(invalid_csv)
        self.assertEqual(main._merchant_catalog_items(), [])


if __name__ == "__main__":
    unittest.main()