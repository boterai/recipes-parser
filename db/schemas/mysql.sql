-- Таблица сайтов
CREATE TABLE IF NOT EXISTS sites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE, -- доменное имя сайта
    pattern VARCHAR(500),
    base_url VARCHAR(500) NOT NULL UNIQUE,
    language VARCHAR(10),
    is_recipe_site BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Таблица спарсенных страниц
CREATE TABLE IF NOT EXISTS pages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_id INT NOT NULL,
    url VARCHAR(1000) NOT NULL,
    pattern VARCHAR(500),
    title TEXT,
    language VARCHAR(10),
    html_path VARCHAR(500),
    
    -- Данные рецепта (NULL = отсутствует)
    ingredients JSON, -- 100% обязательное поле
    instructions TEXT, -- 100% обязательное поле
    dish_name VARCHAR(500), -- 100 % обязательное поле
    nutrition_info TEXT,
    category VARCHAR(255),
    prep_time VARCHAR(100),
    cook_time VARCHAR(100),
    total_time VARCHAR(100),
    image_urls TEXT,
    description TEXT,
    notes TEXT,
    tags TEXT, -- теги через запятую (лучше бы мигрировать на JSON)

    -- Оценка
    confidence_score DECIMAL(5,2) DEFAULT 0.00,
    is_recipe BOOLEAN DEFAULT FALSE,
    
    -- Метаданные
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    UNIQUE KEY unique_site_url (site_id, url(500)),
    INDEX idx_is_recipe (is_recipe),
    INDEX idx_confidence (confidence_score)
) ENGINE=InnoDB;

-- Таблица поисковых запросов
CREATE TABLE IF NOT EXISTS search_query (
    id INT AUTO_INCREMENT PRIMARY KEY,
    query VARCHAR(500) NOT NULL,
    language VARCHAR(10),
    url_count INT DEFAULT 0, -- число полученных ссылок из этого запроса
    recipe_url_count INT DEFAULT 0, -- число уникальных сайтов, признанных рецептами
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_query (query(191))
) ENGINE=InnoDB;