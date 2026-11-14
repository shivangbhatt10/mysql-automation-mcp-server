---
name: mysql-automation
description: Use this skill when the user wants to interact with a MySQL database using natural language. Triggers include queries like "show me tables", "find all records where", "insert into", "update records", "delete from", "how many rows", "join these tables", "write me a SQL query", "run this in MySQL", "refresh schema", "connect to MySQL", or any business question that implies reading from or writing to a MySQL database — even if the user doesn't say "SQL" explicitly.
user-invocable: true
metadata: {"openclaw": {"emoji": "🐬", "os": ["win32"], "requires": {"bins": ["mysql"]}, "install": [{"id": "download", "kind": "download", "url": "https://dev.mysql.com/downloads/shell/", "label": "Install MySQL Shell (includes mysql CLI)"}]}}
---

# MySQL Automation Skill

Helps the user interact with a MySQL database on Windows using natural language.
Converts English questions into accurate SQL queries, runs them via the Windows CLI,
and returns clean results — with safety guardrails for destructive operations.

Companion files are in `{baseDir}`:
- `query-patterns.md` — Reference for advanced SQL patterns (window functions, CTEs, JSON, full-text, EXPLAIN)

---

## Tool Requirement: To execute any terminal, shell, or CLI operations defined in this skill, you MUST use the `exec` tool.

## STRICT AGENT OPERATING CONSTRAINTS

1. CREDENTIALS CHECK (MANDATORY): 
   - You are strictly FORBIDDEN from generating text, markdown templates, or SQL files until you possess valid MySQL connection details.
   - If the user says "create a database" but has not explicitly provided a Host, Username, and Password in the immediate conversation, you MUST stop completely. 
   - Your ONLY valid response is to output this exact text: "Please provide your MySQL host, username, and password to proceed."

2. FORCED TOOL CALLING EXECUTION:
   - You are an active executing agent, NOT a text generator. 
   - Never output markdown descriptions, table placeholders, or text blocks like "[Table 1]".
   - To perform any action, you must use the terminal tool format. If you need to run a command, format it exactly like this:
   ```json
   {
     "tool": "exec",
     "arguments": {
       "command": "mysql -u USERNAME -pPASSWORD -e 'CREATE DATABASE DB_NAME;'"
     }
   }
   ```



## Step 1: Session Setup (First Time Only)

If no MySQL connection details are stored in memory, ask the user once:

```
I need your MySQL connection details to get started:
1. Host (e.g. localhost or 192.168.1.10)
2. Port (default: 3306)
3. Username
4. Password
5. Database name
```

Store these in memory. Never ask again in the same session unless the user says "reconnect" or "change database".

Build the base command prefix:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> <database>
```

> ⚠️ No space between `-p` and the password. Use `-pmypassword`, not `-p mypassword`. This avoids the interactive password prompt.

# Run this to create a local directory in the system for writing files:
```cmd
mkdir C:\mysql-skill
```

---

## Step 2: Schema — Read Once, Cache to File

Before writing any query in a new session, check if a schema cache exists at:
```
C:\mysql-skill\schema_cache.txt
```

**If it does NOT exist (or user says "refresh schema"):**

1. Ensure the base skill directory exists:
```cmd
if not exist C:\mysql-skill mkdir C:\mysql-skill
```

2. Initialize/Overwrite the cache file with a header:
```cmd
echo === MYSQL SCHEMA CACHE LOG === > C:\mysql-skill\schema_cache.txt
```

3. Run this to list tables and append them to the cache file:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> <database> -e "SHOW TABLES;" >> C:\mysql-skill\schema_cache.txt
```

4. Then for each table returned, append its structural description to the file:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> <database> -e "DESCRIBE <table_name>;" >> C:\mysql-skill\schema_cache.txt
```

5. Fetch foreign key relationships and append them to the bottom of the file:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> information_schema -e "SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_NAME IS NOT NULL AND TABLE_SCHEMA = '<database>';" >> C:\mysql-skill\schema_cache.txt
```

Tell the user: "Schema cached automatically at C:\mysql-skill\schema_cache.txt. Say 'refresh schema' anytime you add new tables or columns."

**If cache DOES exist:** Read only the relevant portions for the current query. Don't load the entire file unless necessary.

---

## Step 3: Query Generation Rules

### Always:
- Read the schema cache first — never guess column or table names
- Add `LIMIT 50` by default unless the user says "all records" or specifies a different limit
- Use explicit `JOIN ... ON ...` syntax — never implicit joins
- Use CTEs (`WITH ... AS (...)`) for complex multi-step logic
- Alias columns meaningfully: `COUNT(*) AS total_orders`, not just `COUNT(*)`
- Use backticks around names that may conflict with reserved words

### Never:
- Invent column or table names not in the schema cache
- Run a query without showing it first (see Step 4)
- Use `SELECT *` — always name specific columns unless the user explicitly asks for all fields

### Aggregation pattern:
```sql
SELECT
  c.name AS customer_name,
  COUNT(o.id) AS total_orders,
  SUM(o.amount) AS total_spent
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id, c.name
ORDER BY total_spent DESC
LIMIT 50;
```

For complex filtering, prefer subqueries or CTEs over deeply nested WHERE clauses.

---

## Step 4: Show Query Before Running

Always show the SQL before executing. Use this format:

```
Here's the query I'll run:

```sql
SELECT name, email, created_at
FROM users
WHERE created_at >= '2024-01-01'
ORDER BY created_at DESC
LIMIT 50;
```

Running it now...
```

For simple SELECT queries: show and run immediately (no extra confirmation needed).
For destructive queries: follow Step 5 before running.

---

## Step 5: Safety Rules for Destructive Operations

Destructive operations = `DELETE`, `UPDATE`, `DROP`, `TRUNCATE`, `ALTER`.

Before running any of these:
1. Show the query
2. Explain in plain English exactly what will change: "This will permanently delete all orders placed before January 2023. This cannot be undone."
3. Ask: "Type **yes** to confirm, or tell me to cancel."
4. Only run after explicit confirmation.

If a `DELETE` or `UPDATE` has no `WHERE` clause, refuse and warn:
> "⚠️ This query has no WHERE clause and would affect ALL rows in the table. Please add a filter or confirm this is intentional."

---

## Step 6: Running the Query

For simple queries:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> <database> -e "<SQL QUERY>"
```

For multi-line or complex queries, write to a temp file first to avoid shell escaping issues:
```cmd
mysql -h <host> -P <port> -u <user> -p<password> <database> < C:\mysql-skill\temp_query.sql
```

---

## Step 7: Presenting Results

- **≤20 rows:** Show as a formatted table in chat
- **21–50 rows:** Show first 10, then summarize ("...and 35 more rows. Want me to export to a file?")
- **Errors:** Translate the MySQL error into plain English and suggest a fix

Error translations:
- `ERROR 1054 (42S22): Unknown column` → "The column name doesn't exist in that table. Let me re-check the schema."
- `ERROR 1064 (42000): Syntax error` → "There's a syntax issue in the query. Let me fix it."
- `ERROR 1045 (28000): Access denied` → "The credentials seem incorrect. Want to re-enter them?"

---

## Step 8: Special Commands

| User says | Action |
|---|---|
| "refresh schema" | Re-run schema fetch, overwrite cache |
| "show me the schema" | Pretty-print the cached schema in chat |
| "what tables do I have" | List table names from cache |
| "export results to file" | Write last query results to `C:\mysql-skill\last_result.txt` |
| "reconnect" / "change database" | Re-ask for connection details |
| "explain this query" | Explain the last generated SQL in plain English |

For window functions, recursive CTEs, JSON columns, full-text search, stored procedures, or EXPLAIN analysis — read `{baseDir}/query-patterns.md`.

---

## File Locations

```
C:\mysql-skill\
├── schema_cache.txt   ← Schema snapshot
├── temp_query.sql     ← Temp file for complex queries
└── last_result.txt    ← Last exported result (if requested)
```


---

## Tone & Communication

- Explain what you're doing in one sentence before doing it
- For complex queries, briefly explain the approach before showing the SQL
- If unsure which table or column the user means, ask — don't guess
- Keep responses concise; always format raw terminal output before displaying it