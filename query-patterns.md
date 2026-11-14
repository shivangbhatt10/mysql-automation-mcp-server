# Query Patterns Reference

Use this file when the user asks for advanced SQL patterns. Load only the relevant section.

---

## Window Functions

```sql
-- Rank customers by total spend within each region
SELECT 
  customer_id,
  region,
  total_spent,
  RANK() OVER (PARTITION BY region ORDER BY total_spent DESC) AS rank_in_region
FROM customer_summary;

-- Running total
SELECT 
  order_date,
  amount,
  SUM(amount) OVER (ORDER BY order_date) AS running_total
FROM orders;

-- Compare current row to previous row (LAG)
SELECT 
  month,
  revenue,
  LAG(revenue, 1) OVER (ORDER BY month) AS prev_month_revenue,
  revenue - LAG(revenue, 1) OVER (ORDER BY month) AS growth
FROM monthly_revenue;
```

---

## Recursive CTEs

Use for hierarchical data (org charts, category trees, threaded comments).

```sql
-- Get full org chart under a manager
WITH RECURSIVE org_tree AS (
  -- Base case: start with the root manager
  SELECT id, name, manager_id, 0 AS depth
  FROM employees
  WHERE id = 5  -- starting manager ID

  UNION ALL

  -- Recursive case: find their direct reports
  SELECT e.id, e.name, e.manager_id, ot.depth + 1
  FROM employees e
  INNER JOIN org_tree ot ON e.manager_id = ot.id
)
SELECT * FROM org_tree ORDER BY depth, name;
```

---

## JSON Column Queries

For MySQL 5.7.8+ with JSON column type.

```sql
-- Extract a value from JSON
SELECT 
  id,
  JSON_EXTRACT(metadata, '$.city') AS city
FROM users;

-- Shorthand arrow syntax
SELECT id, metadata->>'$.city' AS city FROM users;

-- Filter by JSON value
SELECT * FROM users
WHERE metadata->>'$.plan' = 'premium';

-- All keys in a JSON object
SELECT JSON_KEYS(metadata) FROM users LIMIT 1;
```

---

## Full-Text Search

Requires a FULLTEXT index on the column(s).

```sql
-- Natural language search
SELECT *, MATCH(title, body) AGAINST ('database optimization') AS relevance
FROM articles
WHERE MATCH(title, body) AGAINST ('database optimization')
ORDER BY relevance DESC
LIMIT 20;

-- Boolean mode (more control)
SELECT * FROM articles
WHERE MATCH(title, body) AGAINST ('+MySQL -Oracle' IN BOOLEAN MODE);
```

---

## EXPLAIN / Query Optimization

```sql
-- See how MySQL executes a query
EXPLAIN SELECT * FROM orders WHERE customer_id = 42;

-- More detailed output
EXPLAIN FORMAT=JSON SELECT * FROM orders WHERE customer_id = 42;

-- Check if indexes are being used
-- Look for: type = 'ref' or 'range' (good), 'ALL' (bad — full table scan)
-- Check: key column — should show which index is used
-- Check: rows column — estimate of rows scanned
```

**Common fixes:**
- `type: ALL` on a large table → add an index on the WHERE column
- `Using filesort` → add an index on the ORDER BY column
- `Using temporary` → restructure GROUP BY or add composite index

```sql
-- Add an index
ALTER TABLE orders ADD INDEX idx_customer_id (customer_id);

-- Check existing indexes
SHOW INDEX FROM orders;
```

---

## Stored Procedure Calls

```sql
-- Call a stored procedure
CALL get_customer_report(42, '2024-01-01', '2024-12-31');

-- Call with OUT parameter
SET @result = 0;
CALL calculate_discount(42, @result);
SELECT @result AS discount_amount;

-- List available stored procedures
SHOW PROCEDURE STATUS WHERE Db = 'your_database';

-- See the code of a procedure
SHOW CREATE PROCEDURE get_customer_report;
```

---

## Useful Diagnostic Queries

```sql
-- Show all running queries
SHOW PROCESSLIST;

-- Show table sizes
SELECT 
  table_name,
  ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb
FROM information_schema.TABLES
WHERE table_schema = DATABASE()
ORDER BY size_mb DESC;

-- Show row counts for all tables
SELECT table_name, table_rows
FROM information_schema.TABLES
WHERE table_schema = DATABASE()
ORDER BY table_rows DESC;

-- Find duplicate values
SELECT email, COUNT(*) AS count
FROM users
GROUP BY email
HAVING count > 1;
```