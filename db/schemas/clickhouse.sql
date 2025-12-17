-- clickhouse schemas
CREATE TABLE IF NOT EXISTS recipe_ru -- таблица переводов рецептов на русский язык
(
    page_id UInt64,
    site_id UInt32,
    dish_name String,
    description String,
    instructions String,
    ingredients Array(String),
    tags Array(String),

    cook_time Nullable(String),
    prep_time Nullable(String),
    total_time Nullable(String),
    nutrition_info Nullable(String),
    category Nullable(String),
    last_updated DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY page_id;
