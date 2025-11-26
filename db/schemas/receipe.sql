-- Таблица сайтов
CREATE TABLE IF NOT EXISTS sites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    pattern VARCHAR(500),
    base_url VARCHAR(500) NOT NULL UNIQUE,
    language VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_name (name)
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
    metadata_path VARCHAR(500),
    
    -- Данные рецепта (NULL = отсутствует)
    ingredients TEXT, -- 100% обязательное поле
    step_by_step TEXT, -- 100% обязательное поле
    dish_name VARCHAR(500), -- 100 % обязательное поле
    image_blob BLOB,
    nutrition_info TEXT,
    rating DECIMAL(3,2),
    author VARCHAR(255),
    category VARCHAR(255),
    prep_time VARCHAR(100),
    cook_time VARCHAR(100),
    total_time VARCHAR(100),
    servings VARCHAR(50),
    difficulty_level VARCHAR(50),
    description TEXT,
    
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