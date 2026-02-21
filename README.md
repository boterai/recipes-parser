# Recipe Parser

Автоматизированный парсер рецептов с веб-сайтов: поиск, парсинг, векторизация и слияние рецептов.

## Быстрый старт

```bash
# 1. Запустить Chrome с отладкой
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug_9222 --no-first-run --no-default-browser-check

# 2. Полный pipeline через main.py
python scripts/main.py <command> [options]
```

## Команды

### 1. **prepare** — Подготовка сайтов для парсинга
Поиск новых сайтов с рецептами через DuckDuckGo, анализ и генерация тестовых данных.
```bash
python scripts/main.py prepare --ports 9222 9223 --target-sites-count 100 --with-gpt
```

### 2. **create_parsers** — Создание парсеров (полуавтомат)
Создание GitHub issues и проверка PR для новых парсеров.
```bash
python scripts/main.py create_parsers --create-issues --merge-prs
```

### 3. **parse** — Парсинг рецептов
Запуск парсинга сайтов (для которых есть экстракторы в `extractor/`).
```bash
python scripts/main.py parse --ports 9222 --modules 24kitchen_nl allrecipes_com
```

### 4. **vectorize** — Векторизация
Перевод, векторизация рецептов и изображений для семантического поиска.
```bash
python scripts/main.py vectorize --all --translate --target-language en
```

### 5. **merge** — Слияние похожих рецептов
Создание новых рецептов из кластеров похожих.
```bash
python scripts/main.py merge --threshold 0.94 --cluster-type ingredients --validate-gpt
```