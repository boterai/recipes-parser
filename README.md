# Recipe Parser

Парсер рецептов с кулинарных сайтов с использованием Selenium и ChatGPT API.



## Запуск

```bash
# Запустить Chrome с отладкой
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug_9222
```

## скрипты 
1. scripts/prepare_site - генерация запросов для поиска в duck duck go, поиск сайтов, анализ сайтов, генерация примеров для создания парсера
2. scripts/parse - парсинг сайтов (для которых есть парсеры в extractor директории) в один или несколкьо потоков
3. scripts/translate - перевод страниц с рецептами и доабвление их в clickhouse
4. scripts/vectorise - поиск похожих и векторизация данных (пока без изображений)
5. scripts/search - поиск похожих в clickhouse по рецептам и по запросу