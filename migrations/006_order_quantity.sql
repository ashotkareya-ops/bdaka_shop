-- Order quantity support (PostgreSQL)
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1;

-- One order can now contain multiple delivered digital keys.
ALTER TABLE digital_keys
    DROP CONSTRAINT IF EXISTS digital_keys_order_id_key;

CREATE INDEX IF NOT EXISTS ix_digital_keys_order_id
    ON digital_keys(order_id);
