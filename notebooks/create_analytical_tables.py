# Fabric IQ Restaurant - Create Lakehouse Analytical Tables
# Executed via Spark SQL in Fabric Notebook

# CELL 1: Create fact_orders table
spark.sql("""
CREATE TABLE IF NOT EXISTS fact_orders (
    order_id STRING,
    order_date DATE,
    order_hour INT,
    channel STRING,
    status STRING,
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    delay_minutes DOUBLE,
    is_delayed BOOLEAN,
    is_on_sla BOOLEAN,
    total_items INT,
    priority STRING,
    station_id STRING,
    created_ts TIMESTAMP
)
USING DELTA
PARTITIONED BY (order_date)
COMMENT "Order facts with SLA and delay metrics"
""")
print("✓ Created fact_orders")

# CELL 2: Create fact_kitchen_flow table
spark.sql("""
CREATE TABLE IF NOT EXISTS fact_kitchen_flow (
    flow_id STRING,
    order_id STRING,
    station_id STRING,
    event_time TIMESTAMP,
    event_date DATE,
    event_hour INT,
    queue_length INT,
    processing_time_minutes DOUBLE,
    station_status STRING,
    saturation_pct DOUBLE,
    orders_ahead INT,
    created_ts TIMESTAMP
)
USING DELTA
PARTITIONED BY (event_date)
COMMENT "Kitchen station queue and processing metrics"
""")
print("✓ Created fact_kitchen_flow")

# CELL 3: Create fact_agent_decisions table
spark.sql("""
CREATE TABLE IF NOT EXISTS fact_agent_decisions (
    decision_id STRING,
    decision_timestamp TIMESTAMP,
    decision_date DATE,
    order_id STRING,
    agent_id STRING,
    decision_type STRING,
    confidence_score DOUBLE,
    context_json STRING,
    action_taken STRING,
    created_ts TIMESTAMP
)
USING DELTA
PARTITIONED BY (decision_date)
COMMENT "Operations Agent decisions and recommendations"
""")
print("✓ Created fact_agent_decisions")

# CELL 4: Create dimension tables
spark.sql("""
CREATE TABLE IF NOT EXISTS dim_stations (
    station_id STRING,
    station_name STRING,
    station_type STRING,
    capacity INT,
    is_active BOOLEAN,
    created_at TIMESTAMP
)
USING DELTA
COMMENT "Kitchen stations reference dimension"
""")
print("✓ Created dim_stations")

spark.sql("""
CREATE TABLE IF NOT EXISTS dim_channels (
    channel_id STRING,
    channel_name STRING,
    channel_type STRING,
    sla_minutes INT,
    priority_default INT,
    is_active BOOLEAN,
    created_at TIMESTAMP
)
USING DELTA
COMMENT "Order channels (delivery, in_store, pickup)"
""")
print("✓ Created dim_channels")

spark.sql("""
CREATE TABLE IF NOT EXISTS dim_order_status (
    status_id STRING,
    status_name STRING,
    status_sequence INT,
    is_terminal BOOLEAN,
    description STRING
)
USING DELTA
COMMENT "Order lifecycle statuses"
""")
print("✓ Created dim_order_status")

# CELL 5: Populate dim_stations
spark.sql("""
INSERT INTO dim_stations (station_id, station_name, station_type, capacity, is_active, created_at)
SELECT * FROM (
    VALUES
        ('kitchen-main', 'Main Kitchen', 'primary', 20, true, current_timestamp()),
        ('kitchen-secondary', 'Secondary Kitchen', 'secondary', 10, true, current_timestamp()),
        ('grill', 'Grill Station', 'specialized', 8, true, current_timestamp()),
        ('prep', 'Prep Station', 'specialized', 12, true, current_timestamp()),
        ('delivery', 'Delivery Counter', 'output', 15, true, current_timestamp())
) AS t(station_id, station_name, station_type, capacity, is_active, created_at)
WHERE NOT EXISTS (SELECT 1 FROM dim_stations)
""")
print("✓ Populated dim_stations")

# CELL 6: Populate dim_channels
spark.sql("""
INSERT INTO dim_channels (channel_id, channel_name, channel_type, sla_minutes, priority_default, is_active, created_at)
SELECT * FROM (
    VALUES
        ('delivery', 'Delivery', 'external', 45, 1, true, current_timestamp()),
        ('in_store', 'In-Store', 'internal', 30, 2, true, current_timestamp()),
        ('pickup', 'Pickup', 'external', 20, 3, true, current_timestamp())
) AS t(channel_id, channel_name, channel_type, sla_minutes, priority_default, is_active, created_at)
WHERE NOT EXISTS (SELECT 1 FROM dim_channels)
""")
print("✓ Populated dim_channels")

# CELL 7: Populate dim_order_status
spark.sql("""
INSERT INTO dim_order_status (status_id, status_name, status_sequence, is_terminal, description)
SELECT * FROM (
    VALUES
        ('created', 'Created', 1, false, 'Order created'),
        ('confirmed', 'Confirmed', 2, false, 'Order confirmed'),
        ('prep_started', 'Prep Started', 3, false, 'Preparation started'),
        ('prep_completed', 'Prep Completed', 4, false, 'Preparation completed'),
        ('ready', 'Ready', 5, false, 'Ready for pickup/delivery'),
        ('delivered', 'Delivered', 6, true, 'Delivered to customer'),
        ('completed', 'Completed', 7, true, 'Order completed'),
        ('cancelled', 'Cancelled', 8, true, 'Order cancelled')
) AS t(status_id, status_name, status_sequence, is_terminal, description)
WHERE NOT EXISTS (SELECT 1 FROM dim_order_status)
""")
print("✓ Populated dim_order_status")

# CELL 8: Verify tables created
result = spark.sql("""
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'default'
AND table_name IN ('fact_orders', 'fact_kitchen_flow', 'fact_agent_decisions', 'dim_stations', 'dim_channels', 'dim_order_status')
ORDER BY table_name
""")
print("\n✅ Tables created successfully:")
result.show(truncate=False)

# Display row counts
spark.sql("SELECT 'dim_stations' as table_name, COUNT(*) as row_count FROM dim_stations UNION ALL SELECT 'dim_channels', COUNT(*) FROM dim_channels UNION ALL SELECT 'dim_order_status', COUNT(*) FROM dim_order_status").show()
