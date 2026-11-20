-- BDAKA SHOP: supplier catalog fields.
-- Safe for existing installations: adds columns only if they do not exist.
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS supplier_cost DOUBLE PRECISION NULL,
    ADD COLUMN IF NOT EXISTS supplier_stock INTEGER NULL,
    ADD COLUMN IF NOT EXISTS supplier_available BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS supplier_synced_at TIMESTAMP WITHOUT TIME ZONE NULL;

CREATE INDEX IF NOT EXISTS ix_products_supplier_lookup
    ON products (supplier_name, supplier_product_id);
