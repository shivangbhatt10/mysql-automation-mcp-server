"""Schema introspection, extraction, formatting, and two-tier caching for MySQL databases."""

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Union

from mysql_mcp.config import get_settings
from mysql_mcp.db import execute_query

# Tier 1: In-memory cache mapping database_name -> schema dictionary
_IN_MEMORY_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_SCHEMA_CACHE_LOCK = threading.Lock()


def _get_cache_file_path(database: Optional[str] = None) -> Path:
    """Return the filesystem path for the Tier 2 disk cache file for a specific database."""
    settings = get_settings()
    settings.ensure_directories()
    target_db = database or settings.mysql_database or "default"
    return settings.mysql_cache_dir / f"schema_{target_db}.json"


def extract_database_schema(database: Optional[str] = None) -> Dict[str, Any]:
    """
    Introspect information_schema for all tables, views, columns, indexes,
    and foreign key constraints for the specified database.
    """
    settings = get_settings()
    target_db = database or settings.mysql_database
    if not target_db:
        raise ValueError(
            "No active database selected. Use 'list_databases()' to see available databases "
            "and 'use_database(<database_name>)' to select one."
        )

    # 1. Fetch Tables and Views
    tables_result = execute_query(
        """
        SELECT
            TABLE_NAME,
            TABLE_TYPE,
            IFNULL(TABLE_ROWS, 0) AS TABLE_ROWS,
            IFNULL(TABLE_COMMENT, '') AS TABLE_COMMENT
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME;
        """,
        (target_db,),
        auto_limit=False,
    )

    tables_meta: Dict[str, Dict[str, Any]] = {}
    for row in tables_result["rows"]:
        tname = row["TABLE_NAME"]
        tables_meta[tname] = {
            "name": tname,
            "type": row["TABLE_TYPE"],
            "comment": row["TABLE_COMMENT"],
            "estimated_rows": int(row["TABLE_ROWS"]),
            "primary_key": [],
            "columns": [],
            "indexes": [],
            "foreign_keys": [],
        }

    # 2. Fetch Columns
    columns_result = execute_query(
        """
        SELECT
            TABLE_NAME,
            COLUMN_NAME,
            ORDINAL_POSITION,
            COLUMN_DEFAULT,
            IS_NULLABLE,
            DATA_TYPE,
            COLUMN_TYPE,
            COLUMN_KEY,
            EXTRA,
            COLUMN_COMMENT
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, ORDINAL_POSITION;
        """,
        (target_db,),
        auto_limit=False,
    )

    for col in columns_result["rows"]:
        tname = col["TABLE_NAME"]
        if tname in tables_meta:
            col_info = {
                "name": col["COLUMN_NAME"],
                "position": int(col["ORDINAL_POSITION"]),
                "data_type": col["DATA_TYPE"],
                "column_type": col["COLUMN_TYPE"],
                "nullable": col["IS_NULLABLE"].upper() == "YES",
                "default": col["COLUMN_DEFAULT"],
                "key": col["COLUMN_KEY"],
                "extra": col["EXTRA"],
                "comment": col["COLUMN_COMMENT"],
            }
            tables_meta[tname]["columns"].append(col_info)
            if col["COLUMN_KEY"] == "PRI":
                tables_meta[tname]["primary_key"].append(col["COLUMN_NAME"])

    # 3. Fetch Indexes
    indexes_result = execute_query(
        """
        SELECT
            TABLE_NAME,
            INDEX_NAME,
            NON_UNIQUE,
            SEQ_IN_INDEX,
            COLUMN_NAME,
            INDEX_TYPE
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
        """,
        (target_db,),
        auto_limit=False,
    )

    indexes_by_table: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for idx_row in indexes_result["rows"]:
        tname = idx_row["TABLE_NAME"]
        iname = idx_row["INDEX_NAME"]
        if tname not in indexes_by_table:
            indexes_by_table[tname] = {}
        if iname not in indexes_by_table[tname]:
            indexes_by_table[tname][iname] = {
                "name": iname,
                "unique": int(idx_row["NON_UNIQUE"]) == 0,
                "type": idx_row["INDEX_TYPE"],
                "columns": [],
            }
        indexes_by_table[tname][iname]["columns"].append(idx_row["COLUMN_NAME"])

    for tname, idict in indexes_by_table.items():
        if tname in tables_meta:
            tables_meta[tname]["indexes"] = list(idict.values())

    # 4. Fetch Foreign Keys
    fks_result = execute_query(
        """
        SELECT
            kcu.TABLE_NAME,
            kcu.COLUMN_NAME,
            kcu.CONSTRAINT_NAME,
            kcu.REFERENCED_TABLE_NAME,
            kcu.REFERENCED_COLUMN_NAME,
            rc.UPDATE_RULE,
            rc.DELETE_RULE
        FROM information_schema.KEY_COLUMN_USAGE kcu
        JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
            ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
            AND kcu.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA
        WHERE kcu.REFERENCED_TABLE_NAME IS NOT NULL
          AND kcu.TABLE_SCHEMA = %s
        ORDER BY kcu.TABLE_NAME, kcu.ORDINAL_POSITION;
        """,
        (target_db,),
        auto_limit=False,
    )

    all_relationships: List[Dict[str, Any]] = []
    for fk in fks_result["rows"]:
        rel = {
            "from_table": fk["TABLE_NAME"],
            "from_column": fk["COLUMN_NAME"],
            "to_table": fk["REFERENCED_TABLE_NAME"],
            "to_column": fk["REFERENCED_COLUMN_NAME"],
            "constraint_name": fk["CONSTRAINT_NAME"],
            "on_update": fk["UPDATE_RULE"],
            "on_delete": fk["DELETE_RULE"],
        }
        all_relationships.append(rel)
        if fk["TABLE_NAME"] in tables_meta:
            tables_meta[fk["TABLE_NAME"]]["foreign_keys"].append({
                "constraint_name": fk["CONSTRAINT_NAME"],
                "column": fk["COLUMN_NAME"],
                "referenced_table": fk["REFERENCED_TABLE_NAME"],
                "referenced_column": fk["REFERENCED_COLUMN_NAME"],
                "on_update": fk["UPDATE_RULE"],
                "on_delete": fk["DELETE_RULE"],
            })

    # 5. Fetch Views
    views_result = execute_query(
        """
        SELECT
            TABLE_NAME,
            VIEW_DEFINITION,
            CHECK_OPTION,
            IS_UPDATABLE
        FROM information_schema.VIEWS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME;
        """,
        (target_db,),
        auto_limit=False,
    )

    views_meta: Dict[str, Dict[str, Any]] = {}
    for v in views_result["rows"]:
        vname = v["TABLE_NAME"]
        views_meta[vname] = {
            "name": vname,
            "definition": v["VIEW_DEFINITION"],
            "check_option": v["CHECK_OPTION"],
            "is_updatable": v["IS_UPDATABLE"].upper() == "YES",
        }

    base_tables = {k: v for k, v in tables_meta.items() if v["type"] != "VIEW"}
    extracted_at = datetime.now(timezone.utc).isoformat()

    return {
        "database": target_db,
        "extracted_at": extracted_at,
        "tables_count": len(base_tables),
        "views_count": len(views_meta),
        "tables": base_tables,
        "views": views_meta,
        "relationships": all_relationships,
    }


def format_schema_as_markdown(schema: Dict[str, Any]) -> str:
    """Format structured schema dictionary into a human-readable Markdown summary."""
    lines: List[str] = []
    db_name = schema.get("database", "unknown")
    extracted_at = schema.get("extracted_at", "")
    tables = schema.get("tables", {})
    views = schema.get("views", {})
    relationships = schema.get("relationships", [])

    lines.append(f"# Database Schema: `{db_name}`")
    lines.append("")
    lines.append(
        f"*Extracted at: {extracted_at} | Total Tables: {len(tables)} | Total Views: {len(views)}*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Overview table
    lines.append("## Tables Overview")
    lines.append("")
    lines.append("| Table | Type | Est. Rows | Columns | Primary Key | Foreign Keys |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for tname, tinfo in sorted(tables.items()):
        pk_str = ", ".join(tinfo.get("primary_key", [])) or "None"
        fk_list = [f"{fk['column']}→{fk['referenced_table']}({fk['referenced_column']})" for fk in tinfo.get("foreign_keys", [])]
        fk_str = ", ".join(fk_list) or "None"
        lines.append(
            f"| `{tname}` | {tinfo.get('type', 'BASE TABLE')} | "
            f"{tinfo.get('estimated_rows', 0)} | {len(tinfo.get('columns', []))} | "
            f"`{pk_str}` | {fk_str} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed Table Schemas
    lines.append("## Detailed Table Schemas")
    lines.append("")

    for tname, tinfo in sorted(tables.items()):
        lines.append(f"### Table: `{tname}`")
        if tinfo.get("comment"):
            lines.append(f"*{tinfo['comment']}*")
            lines.append("")

        lines.append("**Columns:**")
        lines.append("")
        lines.append("| Column | Type | Nullable | Default | Key | Extra |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for col in tinfo.get("columns", []):
            nullable = "YES" if col["nullable"] else "NO"
            default = str(col["default"]) if col["default"] is not None else "-"
            key = col.get("key") or ""
            extra = col.get("extra") or ""
            lines.append(f"| `{col['name']}` | `{col['column_type']}` | {nullable} | {default} | {key} | {extra} |")
        lines.append("")

        indexes = tinfo.get("indexes", [])
        if indexes:
            lines.append("**Indexes:**")
            for idx in indexes:
                unique_badge = "UNIQUE " if idx.get("unique") else ""
                cols_joined = ", ".join(idx.get("columns", []))
                lines.append(f"- `{idx['name']}` ({unique_badge}{idx.get('type', 'BTREE')}) on (`{cols_joined}`)")
            lines.append("")

        fks = tinfo.get("foreign_keys", [])
        if fks:
            lines.append("**Foreign Keys:**")
            for fk in fks:
                lines.append(
                    f"- `{fk['column']}` → `{fk['referenced_table']}({fk['referenced_column']})` "
                    f"[ON UPDATE {fk['on_update']}, ON DELETE {fk['on_delete']}]"
                )
            lines.append("")

    # Views section
    if views:
        lines.append("---")
        lines.append("")
        lines.append("## Views")
        lines.append("")
        for vname, vinfo in sorted(views.items()):
            lines.append(f"### View: `{vname}`")
            lines.append(f"- Updatable: {vinfo.get('is_updatable', False)}")
            lines.append("```sql")
            lines.append(vinfo.get("definition", "").strip())
            lines.append("```")
            lines.append("")

    # Global Relationships Summary
    if relationships:
        lines.append("---")
        lines.append("")
        lines.append("## Foreign Key Relationships Summary")
        lines.append("")
        for rel in relationships:
            lines.append(
                f"- `{rel['from_table']}.{rel['from_column']}` → "
                f"`{rel['to_table']}.{rel['to_column']}` "
                f"(Constraint: `{rel['constraint_name']}`, ON DELETE {rel['on_delete']})"
            )
        lines.append("")

    return "\n".join(lines)


def get_schema(
    refresh: bool = False,
    as_markdown: bool = False,
    database: Optional[str] = None,
) -> Union[Dict[str, Any], str]:
    """
    Retrieve database schema using two-tier caching:
    1. Tier 1: In-memory cache
    2. Tier 2: Disk cache (~/.mysql-mcp/cache/schema_<db>.json)
    3. Fallback: Live query from information_schema
    """
    settings = get_settings()
    target_db = database or settings.mysql_database
    if not target_db:
        raise ValueError(
            "No active database selected. Use 'list_databases()' to see available databases "
            "and 'use_database(<db_name>)' to choose one."
        )

    cache_file = _get_cache_file_path(target_db)
    legacy_file = settings.mysql_cache_dir / "schema_cache.json"

    schema_data: Optional[Dict[str, Any]] = None

    with _SCHEMA_CACHE_LOCK:
        if not refresh:
            # 1. Tier 1 check: in-memory
            if target_db in _IN_MEMORY_SCHEMA_CACHE:
                schema_data = _IN_MEMORY_SCHEMA_CACHE[target_db]

            # 2. Tier 2 check: disk cache (check database-specific file, then legacy file)
            else:
                for candidate in (cache_file, legacy_file):
                    if candidate.exists():
                        try:
                            with open(candidate, "r", encoding="utf-8") as f:
                                disk_data = json.load(f)
                            if disk_data.get("database") == target_db:
                                schema_data = disk_data
                                _IN_MEMORY_SCHEMA_CACHE[target_db] = schema_data
                                break
                        except Exception:
                            schema_data = None

        # 3. Cache miss or refresh requested: query database
        if schema_data is None:
            schema_data = extract_database_schema(target_db)
            _IN_MEMORY_SCHEMA_CACHE[target_db] = schema_data
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(schema_data, f, indent=2)
            except Exception:
                pass

    if as_markdown:
        return format_schema_as_markdown(schema_data)
    return schema_data


def refresh_schema(
    as_markdown: bool = False,
    database: Optional[str] = None,
) -> Union[Dict[str, Any], str]:
    """Force a fresh extraction of the database schema, updating both cache tiers."""
    return get_schema(refresh=True, as_markdown=as_markdown, database=database)


def get_schema_markdown(
    refresh: bool = False,
    database: Optional[str] = None,
) -> str:
    """Convenience helper returning schema formatted as Markdown."""
    res = get_schema(refresh=refresh, as_markdown=True, database=database)
    return str(res)


def clear_schema_cache(database: Optional[str] = None) -> None:
    """Clear Tier 1 in-memory and Tier 2 disk caches for a database (or all if None)."""
    settings = get_settings()

    with _SCHEMA_CACHE_LOCK:
        if database:
            if database in _IN_MEMORY_SCHEMA_CACHE:
                del _IN_MEMORY_SCHEMA_CACHE[database]
            cache_file = _get_cache_file_path(database)
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except Exception:
                    pass
        else:
            _IN_MEMORY_SCHEMA_CACHE.clear()
            legacy_file = settings.mysql_cache_dir / "schema_cache.json"
            if legacy_file.exists():
                try:
                    legacy_file.unlink()
                except Exception:
                    pass
            # Clear all schema_*.json
            if settings.mysql_cache_dir.exists():
                for f in settings.mysql_cache_dir.glob("schema_*.json"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
