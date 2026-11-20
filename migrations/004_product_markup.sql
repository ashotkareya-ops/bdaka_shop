-- Per-product markup percentage. Default 30% for imported supplier items.
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS markup_percent DOUBLE PRECISION NOT NULL DEFAULT 30.0;

-- Recalculate existing Sandromania products using their current supplier cost.
UPDATE products
SET price = ROUND((supplier_cost * (1 + markup_percent / 100.0))::numeric, 2)
WHERE supplier_name = 'sandromania'
  AND supplier_cost IS NOT NULL
  AND supplier_cost > 0;
