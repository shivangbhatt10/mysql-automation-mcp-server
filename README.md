# MySQL Automation MCP Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)
[![Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server for MySQL database operations, schema exploration, query execution, safety guardrails, and natural language analytics.

Built for seamless integration with **OpenClaw**, **Claude Desktop**, and agentic AI workflows.

---

## Key Features

- **9 Production-Ready MCP Tools**: Connection health testing, dynamic runtime credential reconfiguration, table listing, deep schema inspection, safe read query execution, transactional mutations, multi-format `EXPLAIN` query plans, and CSV/JSON query exports.
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
  - In-memory Tier 1 cache + persistent disk Tier 2 cache (`./cache/schema_cache.json`).
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
│       ├── config.py             # Pydantic Settings & environment config
│       ├── db.py                 # Pure-Python PyMySQL pooling & transactions
│       ├── errors.py             # MySQL error diagnostics & guidance catalog
│       ├── safety.py             # sqlparse query classification & safety rules
│       ├── schema.py             # Schema extraction, Markdown, & two-tier cache
│       └── server.py             # FastMCP server with 9 tools, 2 resources, 2 prompts
├── scripts/
│   ├── seed_demo_db.py           # Database initializer and sample data generator
│   └── verify_server_e2e.py      # Complete end-to-end server verification script
├── tests/
│   ├── test_safety.py            # Unit tests for query safety rules (41 tests)
│   ├── test_schema.py            # Unit tests for schema extraction & caching (10 tests)
│   ├── test_seed.py              # Verification of seeded demo database (1 test)
│   └── test_server.py            # Tests for FastMCP tools, resources & prompts (24 tests)
├── .env.example                  # Environment configuration template
├── openclaw_config.json          # OpenClaw / Claude Desktop MCP client configuration
├── pyproject.toml                # Project metadata, dependencies, & pytest settings
├── query-patterns.md             # Advanced SQL reference (CTEs, Window, JSON)
├── requirements.txt              # Project dependencies
├── SKILL.md                      # OpenClaw agent skill definition
└── README.md
```

---

## Setup & Installation

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/shivangbhatt10/mysql-automation-mcp-server.git
cd mysql-automation-mcp-server

# Create virtual environment with Python 3.10+
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your MySQL connection details:

```bash
cp .env.example .env
```

Default configuration in `.env`:
```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password_here
MYSQL_DATABASE=ecommerce_demo
MYSQL_DEFAULT_LIMIT=50
MYSQL_MAX_LIMIT=1000
MYSQL_EXPORTS_DIR=./exports
MYSQL_CACHE_DIR=./cache
```

### 3. Seed Demo Database

Run the database setup script to create `ecommerce_demo` and populate realistic tables (`users`, `products`, `orders`, `order_items`, `reviews`):

```bash
python scripts/seed_demo_db.py
```

### 4. Verify Server End-to-End

Run the automated end-to-end verification script:

```bash
python scripts/verify_server_e2e.py
```

### 5. Run Test Suite

```bash
pytest -v
```

---

## MCP Tools Reference

The server exposes **9 MCP tools**:

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| **`test_connection`** | None | Pings the active MySQL instance and returns connection status, roundtrip latency (ms), MySQL version, active database, and pool statistics. |
| **`configure_connection`** | `host` *(opt)*, `port` *(opt)*, `user` *(opt)*, `password` *(opt)*, `database` *(opt)* | Reconfigures connection credentials dynamically at runtime, rebuilds the connection pool, invalidates caches, and confirms connectivity. |
| **`list_tables`** | None | Returns a list of all base tables and views in the database with estimated row counts, column counts, and primary keys. |
| **`describe_table`** | `table_name: str` | Returns detailed column definitions (types, nullability, defaults, keys, extra) and indexes for the specified table. |
| **`get_schema`** | `refresh: bool = False`, `format: str = "markdown"` | Returns the database schema in human-readable Markdown (`format="markdown"`) or structured JSON (`format="json"`). Uses two-tier caching unless `refresh=True`. |
| **`execute_query`** | `sql: str`, `limit: int = 50` | Validates that the query is read-only, safely injects or clamps the `LIMIT` clause, executes the query, and returns columns, rows, and execution time (ms). |
| **`execute_mutation`** | `sql: str`, `confirmed: bool = False`, `allow_unfiltered: bool = False` | Executes `INSERT`, `UPDATE`, `DELETE`, or DDL inside an ACID transaction. Blocks unconstrained `UPDATE`/`DELETE` unless `allow_unfiltered=True`. Requires `confirmed=True` for destructive DDL (`DROP`, `TRUNCATE`, `ALTER`). |
| **`explain_query`** | `sql: str`, `format: str = "TRADITIONAL"` | Runs `EXPLAIN` on a SQL query and returns the execution plan. Supports `format="TRADITIONAL"`, `format="JSON"`, or `format="TREE"`. |
| **`export_query_results`** | `sql: str`, `format: str = "csv"`, `filename: str = None` | Executes a read-only query and exports the results to `./exports/<filename>` in CSV or JSON format. Returns file path, row count, and file size. |

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

### Configuration (`openclaw_config.json` / `claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "mysql-automation": {
      "command": "C:\\Users\\HP\\Desktop\\openclaw-skill\\mysql-automation-mcp-server\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "mysql_mcp.server"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\HP\\Desktop\\openclaw-skill\\mysql-automation-mcp-server\\src",
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "your_password_here",
        "MYSQL_DATABASE": "ecommerce_demo",
        "MYSQL_DEFAULT_LIMIT": "50",
        "MYSQL_MAX_LIMIT": "1000",
        "MYSQL_EXPORTS_DIR": "C:\\Users\\HP\\Desktop\\openclaw-skill\\mysql-automation-mcp-server\\exports",
        "MYSQL_CACHE_DIR": "C:\\Users\\HP\\Desktop\\openclaw-skill\\mysql-automation-mcp-server\\cache"
      }
    }
  }
}
```

---

## License

This project is licensed under the [MIT License](LICENSE).
