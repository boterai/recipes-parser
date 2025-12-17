-- clickhouse schemas
CREATE TABLE IF NOT EXISTS recipe_en -- таблица переводов рецептов на русский язык
(
    page_id UInt64,
    site_id UInt32,
    dish_name String DEFAULT '',
    description String DEFAULT '',
    instructions String,
    ingredients Array(String),
    tags Array(String),

    cook_time String DEFAULT '',
    prep_time String DEFAULT '',
    total_time String DEFAULT '',
    nutrition_info String DEFAULT '',
    category String DEFAULT '',
    vectorised BOOLEAN DEFAULT FALSE, -- была ли векторизация рецепта
    last_updated DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY page_id;
