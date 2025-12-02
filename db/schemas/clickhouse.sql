-- clickhouse keyword and translation schema
CREATE TABLE IF NOT EXISTS translation
(
    word String, -- word for translation
    translations Map(String, String),  -- {'en': 'chicken', 'ru': 'курица', 'es': 'pollo'}
    updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY word;
-- схема для хранения ключевых слов рецептов (+ тестово эмбединга)
CREATE TABLE IF NOT EXISTS recipe_keywords
(
    page_id UInt64,                      -- ID рецепта
    dish_name String,                    -- название блюда
    language String,                     -- язык рецепта ('en', 'ru', 'es')
    keywords Array(String),              -- ['курица', 'рис', 'острый', 'азиатская']
    keyword_types Map(String, String) DEFAULT map(),   -- {'курица': 'ingredient', 'острый': 'taste'}
    keyword_weights Map(String, Float32) DEFAULT map(), -- {'курица': 1.0, 'рис': 0.8}
    recipe_embedding Array(Float32),     -- векторное представление текста рецепта (тестовое поле)
    ingredient_embedding Array(Float32), -- векторное представление ингредиентов (тестовое поле)
    description_embedding Array(Float32), -- векторное представление описания рецепта (тестовое поле)
    instruction_embedding Array(Float32), -- векторное представление инструкции рецепта (тестовое поле)
    updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (page_id, language);