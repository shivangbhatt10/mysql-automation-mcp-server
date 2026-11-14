# MySQL Automation MCP Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)
[![Tests](https://img.shields.io/badge/tests-79%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server for MySQL database operations, schema exploration, dynamic database switching, query execution, safety guardrails, and natural language analytics.

Designed for universal, portable distribution across **OpenClaw**, **Claude Desktop**, and agentic AI systems on Windows, macOS, and Linux.

---

## Key Features

- **11 Production-Ready MCP Tools**: Connection health testing, dynamic runtime credential reconfiguration, multi-database discovery (`list_databases`), on-the-fly database switching (`use_database`), table listing, deep schema inspection, safe read query execution, transactional mutations, multi-format `EXPLAIN` query plans, and CSV/JSON query exports.
- **Multi-Database Support**:
  - Connects gracefully at the MySQL instance level without requiring a hardcoded initial database.
  - Dynamically discover all databases with `list_databases()`.
  - Switch active database context instantly at runtime via `use_database(database_name)`.
  - Maintains separate schema caches per database.
- **Universal, Zero-Hardcoding Portability**:
  - Automatically defaults data storage to the user home directory (`~/.mysql-mcp/exports` and `~/.mysql-mcp/cache`).
  - Supports packaging and instant execution via `uvx` without needing hardcoded paths or manual environment configuration.
  - Persists dynamic runtime configurations to `~/.mysql-mcp/config.json`.
- **AST-Based Query Safety Guardrails (`sqlparse`)**:
  - Differentiates read-only statements (`SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH ... SELECT`) from mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc.).
  - Rejects dangerous unconstrained `UPDATE` and `DELETE` queries lacking a `WHERE` clause unless `allow_unfiltered=True` is explicitly specified.
  - Requires explicit `confirmed=True` for destructive DDL operations (`DROP`, `TRUNCATE`, `ALTER`).
  - Automatically injects default `LIMIT 50` into `SELECT` queries without one, respects lock clauses (`FOR UPDATE`), and clamps queries exceeding `LIMIT 1000`.
- **Pure-Python PyMySQL Connection Pooling**:
  - Thread-safe connection pool with configurable pool size, overflow capacity, and timeouts.
  - Proactive health pings (`conn.ping()`) and automatic recovery of stale or severed connections.
  - Transaction context manager (`transaction()`) with automatic commit on success and rollback on exceptions.
- **Two-Tier Schema Introspection & Caching**:
  - Deep introspection of tables, views, column types, nullability, defaults, indexes, and foreign key constraints (`ON UPDATE`, `ON DELETE`) from `information_schema`.
  - In-memory Tier 1 cache + persistent disk Tier 2 cache (`~/.mysql-mcp/cache/schema_<db>.json`).
  - Dual output modes: structured JSON/dictionary and human-readable Markdown summary.
- **User-Friendly Error Diagnostics**:
  - Translates cryptic MySQL error codes (`1045`, `1049`, `1054`, `1064`, `1146`, `1215`, `1451`) into clear diagnostic explanations and suggested remediation actions.
- **MCP Resources & Prompts**:
  - Resources: `mysql://schema` and `mysql://query-patterns`.
  - Prompts: `generate_sql` and `optimize_query`.

---

## Project Structure

```text
mysql-automation-mcp-server/
├── src/
│   └── mysql_mcp/
│       ├── __init__.py
│       ├── config.py             # Pydantic Settings, ~/.mysql-mcp persistence, & env config
│       ├── db.py                 # Pure-Python PyMySQL pooling & transactions
│       ├── errors.py             # MySQL error diagnostics & guidance catalog
│       ├── safety.py             # sqlparse query classification & safety rules
│       ├── schema.py             # Per-database schema extraction, Markdown, & two-tier cache
│       └── server.py             # FastMCP server with 11 tools, 2 resources, 2 prompts
├── scripts/
│   ├── seed_demo_db.py           # Database initializer and sample data generator
│   └── verify_server_e2e.py      # Complete end-to-end server verification script
├── tests/
│   ├── test_safety.py            # Unit tests for query safety rules (41 tests)
│   ├── test_schema.py            # Unit tests for schema extraction & caching (10 tests)
│   ├── test_seed.py              # Verification of seeded demo database (1 test)
│   └── test_server.py            # Tests for FastMCP tools, resources & prompts (27 tests)
├── .env.example                  # Environment configuration template
├── openclaw_config.json          # Sanitized OpenClaw / Claude Desktop MCP client configuration
├── pyproject.toml                # Project metadata, CLI script entrypoint, & pytest settings
├── query-patterns.md             # Advanced SQL reference (CTEs, Window, JSON)
├── requirements.txt              # Project dependencies
├── SKILL.md                      # OpenClaw agent skill definition
└── README.md
```

---

## Universal Setup & Execution

### Option A: Direct Execution via `uvx` (Recommended for End Users)

Any user on Windows, macOS, or Linux can run the MCP server with zero installation:

```json
{
  "mcpServers": {
    "mysql-automation": {
      "command": "uvx",
      "args": ["mysql-automation-mcp-server"],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "your_mysql_username",
        "MYSQL_PASSWORD": "your_mysql_password"
      }
    }
  }
}
```

### Option B: Local Source Setup (Developers)

```bash
git clone https://github.com/shivangbhatt10/mysql-automation-mcp-server.git
cd mysql-automation-mcp-server

# Create virtual environment with Python 3.10+
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies and local package in editable mode
pip install -e .

# Configure environment
cp .env.example .env

# Optional: Seed demo database
python scripts/seed_demo_db.py

# Run verification and tests
python scripts/verify_server_e2e.py
pytest -v
```

---

## Multi-Database Management Workflow

When connecting to MySQL instances hosting multiple databases:

1. **Initial Connect**: If no database is specified in `MYSQL_DATABASE`, the server connects at the instance level.
2. **List Databases**: Call `list_databases()` to see all databases accessible by the user (with system catalogs flagged).
3. **Switch Active Database**: Call `use_database("analytics_db")` to switch context at runtime without restarting the server.
4. **Inspect & Query**: All subsequent queries and schema inspections target the newly selected database.

---

## MCP Tools Reference

The server exposes **11 MCP tools**:

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| **`test_connection`** | None | Pings the active MySQL instance and returns connection status, roundtrip latency (ms), MySQL version, active database, and pool statistics. |
| **`configure_connection`** | `host` *(opt)*, `port` *(opt)*, `user` *(opt)*, `password` *(opt)*, `database` *(opt)*, `save_config: bool = True` | Reconfigures connection credentials dynamically at runtime, rebuilds the connection pool, invalidates caches, confirms connectivity, and optionally persists credentials to `~/.mysql-mcp/config.json`. |
| **`list_databases`** | None | Returns a list of all databases on the connected MySQL server, identifying the active database and filtering/flagging system catalogs. |
| **`use_database`** | `database_name: str` | Validates that the database exists, switches the active database context, reinitializes the pool, and updates persistent settings. |
| **`list_tables`** | None | Returns a list of all base tables and views in the active database with estimated row counts, column counts, and primary keys. |
| **`describe_table`** | `table_name: str` | Returns detailed column definitions (types, nullability, defaults, keys, extra) and indexes for the specified table. |
| **`get_schema`** | `refresh: bool = False`, `format: str = "markdown"` | Returns the database schema in human-readable Markdown (`format="markdown"`) or structured JSON (`format="json"`). Uses two-tier caching per database. |
| **`execute_query`** | `sql: str`, `limit: int = 50` | Validates that the query is read-only, safely injects or clamps the `LIMIT` clause, executes the query, and returns columns, rows, and execution time (ms). |
| **`execute_mutation`** | `sql: str`, `confirmed: bool = False`, `allow_unfiltered: bool = False` | Executes `INSERT`, `UPDATE`, `DELETE`, or DDL inside an ACID transaction. Blocks unconstrained `UPDATE`/`DELETE` unless `allow_unfiltered=True`. Requires `confirmed=True` for destructive DDL (`DROP`, `TRUNCATE`, `ALTER`). |
| **`explain_query`** | `sql: str`, `format: str = "TRADITIONAL"` | Runs `EXPLAIN` on a SQL query and returns the execution plan. Supports `format="TRADITIONAL"`, `format="JSON"`, or `format="TREE"`. |
| **`export_query_results`** | `sql: str`, `format: str = "csv"`, `filename: str = None` | Executes a read-only query and exports the results to `~/.mysql-mcp/exports/<filename>` in CSV or JSON format. Returns file path, row count, and file size. |

---

## MCP Resources Reference

The server exposes **2 MCP resources**:

| URI | Content Type | Description |
| :--- | :--- | :--- |
| **`mysql://schema`** | `text/markdown` | Returns the active MySQL database schema documentation in Markdown format (tables, columns, indexes, foreign keys). |
| **`mysql://query-patterns`** | `text/markdown` | Streams the contents of [`query-patterns.md`](query-patterns.md), providing reference patterns for CTEs, window functions, JSON manipulation, and EXPLAIN analysis. |

---

## MCP Prompts Reference

The server exposes **2 MCP prompts**:

| Prompt Name | Arguments | Description |
| :--- | :--- | :--- |
| **`generate_sql`** | `user_request: str`, `table_context: str = ""` | Instructs the model to generate safe, performant SQL following strict guidelines: explicit `JOIN ... ON` syntax, avoiding `SELECT *`, leveraging CTEs, using JSON operators (`->>`, `JSON_CONTAINS`), and filtering on indexed columns. |
| **`optimize_query`** | `sql_query: str`, `explain_plan: str = ""` | Diagnostic checklist for interpreting MySQL query execution plans: identifying full table scans (`type: ALL`), inspecting index coverage, diagnosing filesorts, and generating `CREATE INDEX` recommendations. |

---

## Safety Guardrails Reference

1. **Read-Only vs Mutation Enforcement**:
   - `execute_query` permits only `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, and `WITH ... SELECT` queries.
   - Any attempt to execute `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `ALTER` via `execute_query` raises a `QuerySafetyError`.
2. **Unconstrained Mutation Protection**:
   - Any `UPDATE` or `DELETE` statement lacking a top-level `WHERE` clause is blocked.
   - Empty `WHERE` clauses, comment-only clauses, or subqueries that leave the outer statement unconstrained are detected and rejected.
   - Set `allow_unfiltered=True` in `execute_mutation` to explicitly bypass when intended.
3. **Destructive DDL Confirmation**:
   - `DROP`, `TRUNCATE`, and `ALTER` statements require explicit confirmation via `confirmed=True` in `execute_mutation`.
4. **Automatic Result Pagination**:
   - `SELECT` queries without a `LIMIT` clause automatically receive `LIMIT 50`.
   - Existing `LIMIT` clauses exceeding `1000` rows are automatically clamped to `1000`.
   - Semicolons and trailing lock clauses (`FOR UPDATE`, `FOR SHARE`) are preserved in their valid SQL syntax order.

---

## OpenClaw / Claude Desktop Integration

This server can be integrated directly with **OpenClaw** or **Claude Desktop** by adding the configuration block from [`openclaw_config.json`](openclaw_config.json).

### Sanitized Client Configuration Template

```json
{
  "mcpServers": {
    "mysql-automation": {
      "command": "uvx",
      "args": [
        "mysql-automation-mcp-server"
      ],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "${MYSQL_USER:-root}",
        "MYSQL_PASSWORD": "${MYSQL_PASSWORD:-}",
        "MYSQL_DATABASE": "${MYSQL_DATABASE:-}"
      }
    }
  }
}
```

---

## License

This project is licensed under the [MIT License](LICENSE).
