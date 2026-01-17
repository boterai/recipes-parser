-- Таблица сайтов
CREATE TABLE IF NOT EXISTS sites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE, -- доменное имя сайта
    pattern VARCHAR(500), -- recipe pattern для страниц рецептов
    base_url VARCHAR(500) NOT NULL UNIQUE,
    search_url TEXT, -- URL для поиска рецептов на сайте
    searched BOOLEAN DEFAULT FALSE, -- был ли выполнен поиск рецептов на сайте
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
    category VARCHAR(255),
    prep_time VARCHAR(100),
    cook_time VARCHAR(100),
    total_time VARCHAR(100),
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

-- Таблица изображений рецептов
CREATE TABLE IF NOT EXISTS images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    page_id INT NOT NULL,
    image_url VARCHAR(1000) NOT NULL,
    image_url_hash CHAR(64) AS (SHA2(image_url, 256)) STORED,
    local_path VARCHAR(500),
    remote_storage_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    vectorised BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,
    INDEX idx_page_id (page_id),
    UNIQUE KEY unique_image_url_hash (image_url_hash)
) ENGINE=InnoDB;


-- Таблица кластеров рецептов (для векторных представлений)
CREATE TABLE IF NOT EXISTS recipe_clusters (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pages_hash_sha256 CHAR(64) NOT NULL,     -- SHA2("1,15,23", 256)
    pages_csv LONGTEXT NOT NULL,              -- "1,15,23" - CSV ID страниц рецептов в кластере
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pages_hash (pages_hash_sha256)
) ENGINE=InnoDB;

-- Таблица похожести рецептов (для векторных представлений)
CREATE TABLE IF NOT EXISTS recipe_similarities (
    page_id INT NOT NULL,               -- ID страницы рецепта
    cluster_id BIGINT NOT NULL,             -- ID кластера похожих рецептов (просто порядковый номер пока что)
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cluster_id, page_id),

    FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES recipe_clusters(id) ON DELETE CASCADE,
    UNIQUE KEY uq_pair_model_metric (page_id, cluster_id),

    INDEX idx_cluster_id (cluster_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS merged_recipes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pages_hash_sha256 CHAR(64) NOT NULL,     -- SHA2("1,15,23", 256)
    pages_csv LONGTEXT NOT NULL,              -- "1,15,23" - CSV ID страниц рецептов в кластере
    -- Данные нового рецепта (NULL = отсутствует)
    dish_name VARCHAR(500), -- 100 % обязательное поле
    ingredients JSON, -- 100% обязательное поле
    description TEXT,
    instructions TEXT, -- 100% обязательное поле
    nutrition_info TEXT,
    prep_time VARCHAR(100),
    cook_time VARCHAR(100),
    merge_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pages_hash (pages_hash_sha256)
) ENGINE=InnoDB;