CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS crm_events (
    event_id TEXT PRIMARY KEY,
    event_time TIMESTAMP NOT NULL,
    customer_id TEXT NOT NULL,
    age_group TEXT,
    gender TEXT,
    region TEXT,
    membership_grade TEXT,
    is_new_customer BOOLEAN NOT NULL,
    session_id TEXT,
    channel TEXT,
    traffic_source TEXT,
    device_type TEXT,
    event_type TEXT NOT NULL,
    page_stay_seconds INTEGER,
    search_keyword TEXT,
    product_id TEXT,
    product_name TEXT,
    product_category TEXT,
    product_price NUMERIC(12, 2),
    discount_rate NUMERIC(5, 2),
    discounted_price NUMERIC(12, 2),
    cart_item_count INTEGER,
    quantity INTEGER,
    order_id TEXT,
    order_amount NUMERIC(12, 2),
    is_purchase BOOLEAN NOT NULL,
    campaign_name TEXT,
    coupon_used BOOLEAN NOT NULL,
    coupon_downloaded BOOLEAN NOT NULL,
    previous_purchase_count INTEGER,
    days_since_last_purchase INTEGER,
    crm_tags TEXT[] NOT NULL DEFAULT '{}',
    estimated_segment TEXT
);
CREATE INDEX IF NOT EXISTS idx_crm_events_customer_time ON crm_events (customer_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_crm_events_event_type ON crm_events (event_type);
CREATE INDEX IF NOT EXISTS idx_crm_events_product ON crm_events (product_id);
CREATE INDEX IF NOT EXISTS idx_crm_events_category ON crm_events (product_category);
CREATE INDEX IF NOT EXISTS idx_crm_events_purchase ON crm_events (is_purchase);

CREATE TABLE IF NOT EXISTS crm_entities (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    content TEXT NOT NULL,
    source_count INTEGER NOT NULL CHECK (source_count > 0),
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_name)
);
CREATE INDEX IF NOT EXISTS idx_crm_entities_hnsw_cosine
ON crm_entities USING hnsw (embedding vector_cosine_ops);
