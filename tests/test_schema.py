"""Unit and integration tests for schema extraction, formatting, and two-tier caching."""

import json
from pathlib import Path
import pytest

from mysql_mcp.schema import (
    _IN_MEMORY_SCHEMA_CACHE,
    _get_cache_file_path,
    clear_schema_cache,
    extract_database_schema,
    format_schema_as_markdown,
    get_schema,
    get_schema_markdown,
    refresh_schema,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure clean cache before and after each test."""
    clear_schema_cache()
    yield
    clear_schema_cache()


class TestSchemaExtraction:
    """Test extracting database metadata from information_schema."""

    def test_extract_database_schema_structure(self):
        schema = extract_database_schema()

        assert isinstance(schema, dict)
        assert schema["database"] == "ecommerce_demo"
        assert "extracted_at" in schema
        assert schema["tables_count"] == 5
        assert schema["views_count"] == 0

        # Check tables
        tables = schema["tables"]
        expected_tables = {"users", "products", "orders", "order_items", "reviews"}
        assert set(tables.keys()) == expected_tables

        for tname in expected_tables:
            tinfo = tables[tname]
            assert tinfo["name"] == tname
            assert tinfo["type"] == "BASE TABLE"
            assert tinfo["primary_key"] == ["id"]
            assert len(tinfo["columns"]) > 0
            assert len(tinfo["indexes"]) > 0

    def test_users_table_columns_and_indexes(self):
        schema = extract_database_schema()
        users = schema["tables"]["users"]
        col_names = [c["name"] for c in users["columns"]]

        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "role" in col_names
        assert "status" in col_names
        assert "preferences" in col_names

        # Column properties
        id_col = next(c for c in users["columns"] if c["name"] == "id")
        assert id_col["data_type"] == "int"
        assert id_col["nullable"] is False
        assert id_col["key"] == "PRI"
        assert "auto_increment" in id_col["extra"]

        email_col = next(c for c in users["columns"] if c["name"] == "email")
        assert email_col["data_type"] == "varchar"
        assert email_col["key"] == "UNI"

        pref_col = next(c for c in users["columns"] if c["name"] == "preferences")
        assert pref_col["data_type"] == "json"

        # Indexes
        idx_names = [idx["name"] for idx in users["indexes"]]
        assert "PRIMARY" in idx_names
        assert "idx_users_role_status" in idx_names
        assert "idx_users_created_at" in idx_names

    def test_foreign_key_relationships(self):
        schema = extract_database_schema()
        relationships = schema["relationships"]
        assert len(relationships) == 5

        # Verify orders -> users FK
        order_user_fk = next(
            (r for r in relationships if r["from_table"] == "orders" and r["from_column"] == "user_id"),
            None,
        )
        assert order_user_fk is not None
        assert order_user_fk["to_table"] == "users"
        assert order_user_fk["to_column"] == "id"
        assert order_user_fk["on_delete"] == "CASCADE"

        # Verify order_items -> products FK
        item_prod_fk = next(
            (r for r in relationships if r["from_table"] == "order_items" and r["from_column"] == "product_id"),
            None,
        )
        assert item_prod_fk is not None
        assert item_prod_fk["to_table"] == "products"
        assert item_prod_fk["on_delete"] == "RESTRICT"


class TestMarkdownFormatting:
    """Test generating human-readable Markdown documentation from schema."""

    def test_format_schema_as_markdown(self):
        schema = extract_database_schema()
        md = format_schema_as_markdown(schema)

        assert isinstance(md, str)
        assert "# Database Schema: `ecommerce_demo`" in md
        assert "## Tables Overview" in md
        assert "## Detailed Table Schemas" in md
        assert "## Foreign Key Relationships Summary" in md

        # Check table names and columns present
        for tname in ["users", "products", "orders", "order_items", "reviews"]:
            assert f"`{tname}`" in md

        assert "`auto_increment`" in md or "auto_increment" in md
        assert "orders.user_id" in md
        assert "users.id" in md

    def test_get_schema_markdown_helper(self):
        md = get_schema_markdown()
        assert "# Database Schema: `ecommerce_demo`" in md
        assert "## Tables Overview" in md


class TestTwoTierCaching:
    """Test in-memory and disk cache functionality."""

    def test_cache_miss_creates_disk_and_memory_cache(self):
        cache_file = _get_cache_file_path()
        assert not cache_file.exists()
        assert "ecommerce_demo" not in _IN_MEMORY_SCHEMA_CACHE

        schema = get_schema()
        assert schema["database"] == "ecommerce_demo"

        # Both tiers populated
        assert "ecommerce_demo" in _IN_MEMORY_SCHEMA_CACHE
        assert cache_file.exists()

        # Check disk cache file contents
        with open(cache_file, "r", encoding="utf-8") as f:
            disk_content = json.load(f)
        assert disk_content["database"] == "ecommerce_demo"
        assert disk_content["tables_count"] == 5

    def test_memory_cache_hit(self):
        # Prime the cache
        get_schema()
        assert "ecommerce_demo" in _IN_MEMORY_SCHEMA_CACHE

        # Put a sentinel marker in memory
        _IN_MEMORY_SCHEMA_CACHE["ecommerce_demo"]["_test_marker"] = "in_memory_hit"

        # Next call should return memory cache with sentinel
        hit = get_schema()
        assert hit.get("_test_marker") == "in_memory_hit"

    def test_disk_cache_hit_when_memory_cache_empty(self):
        # Prime cache
        get_schema()
        cache_file = _get_cache_file_path()
        assert cache_file.exists()

        # Inject sentinel marker into disk file
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_test_marker"] = "disk_hit"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Clear in-memory cache only
        _IN_MEMORY_SCHEMA_CACHE.clear()

        # Next call should hit disk cache and populate in-memory cache
        hit = get_schema()
        assert hit.get("_test_marker") == "disk_hit"
        assert "ecommerce_demo" in _IN_MEMORY_SCHEMA_CACHE

    def test_refresh_schema_bypasses_cache(self):
        # Prime cache with sentinel marker in both tiers
        get_schema()
        _IN_MEMORY_SCHEMA_CACHE["ecommerce_demo"]["_test_marker"] = "stale"
        cache_file = _get_cache_file_path()
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_test_marker"] = "stale"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # refresh_schema should overwrite and not have the sentinel
        refreshed = refresh_schema()
        assert "_test_marker" not in refreshed
        assert _IN_MEMORY_SCHEMA_CACHE["ecommerce_demo"].get("_test_marker") is None

        with open(cache_file, "r", encoding="utf-8") as f:
            new_disk = json.load(f)
        assert "_test_marker" not in new_disk

    def test_clear_schema_cache(self):
        get_schema()
        cache_file = _get_cache_file_path()
        assert cache_file.exists()
        assert "ecommerce_demo" in _IN_MEMORY_SCHEMA_CACHE

        clear_schema_cache()
        assert not cache_file.exists()
        assert "ecommerce_demo" not in _IN_MEMORY_SCHEMA_CACHE

