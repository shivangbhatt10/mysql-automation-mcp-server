# MySQL Automation MCP Server

An MCP (Model Context Protocol) server for MySQL database operations, schema exploration, safety guardrails, and natural language analytics.

## Features

- **AST-Based Query Safety (`sqlparse`)**:
  - Differentiates read-only operations (`SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH ... SELECT`) from mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc.).
  - Rejects dangerous `UPDATE` and `DELETE` queries lacking a `WHERE` clause unless `allow_unfiltered=True` is explicitly specified.
  - Automatically injects default `LIMIT 50` into `SELECT` queries without one and clamps queries exceeding `LIMIT 1000`.
- **Pure-Python PyMySQL Connection Pooling**:
  - Thread-safe connection pool with configurable pool size, overflow, and timeouts.
  - Active connection health validation and auto-recovery.
  - Transaction context manager (`transaction()`) with automatic commit on success and rollback on exceptions.
- **Diagnostic Error Handling**:
  - Translates cryptic MySQL error codes (`1045`, `1049`, `1054`, `1064`, `1146`, `1215`, `1451`) into user-friendly diagnostic guidance and actionable solutions.
- **Demo Database Seeding**:
  - Automated seeding script (`scripts/seed_demo_db.py`) creating an `ecommerce_demo` database with realistic tables (`users`, `products`, `orders`, `order_items`, `reviews`), foreign keys, JSON attributes, and indexes.

## Project Structure

```text
mysql-automation-mcp-server/
├── src/
│   └── mysql_mcp/
│       ├── __init__.py
│       ├── config.py       # Pydantic Settings & environment config
│       ├── db.py           # Pure-Python PyMySQL pooling & transactions
│       ├── errors.py       # MySQL error diagnostics & guidance
│       └── safety.py       # sqlparse query classification & safety rules
├── scripts/
│   └── seed_demo_db.py     # Database initializer and sample data generator
├── tests/
│   ├── test_safety.py      # Unit tests for query safety rules
│   └── test_seed.py        # Database schema and seeding verification
├── .env.example            # Environment configuration template
├── pyproject.toml          # Project configuration & pytest settings
├── requirements.txt        # Production & development dependencies
└── SKILL.md                # Agent skill specification
```

## Setup & Installation

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/shivangbhatt10/mysql-automation-mcp-server.git
cd mysql-automation-mcp-server
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your MySQL connection details:

```bash
cp .env.example .env
```

### 3. Seed Demo Database

Run the database setup and seeding script:

```bash
python scripts/seed_demo_db.py
```

### 4. Run Test Suite

```bash
pytest -v
```

## License

MIT License

