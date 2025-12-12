# Recipe Parser

Парсер рецептов с кулинарных сайтов с использованием Selenium и ChatGPT API.



## Запуск

```bash
# Запустить Chrome с отладкой
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug_9222
```

документация qdrant - https://qdrant.tech/documentation/quickstart/
```bash
# запус qdrant локально
docker pull qdrant/qdrant
docker run -p 6333:6333 -p 6334:6334 \
    -v "$(pwd)/qdrant_storage:/qdrant/storage:z" \
    qdrant/qdrant
```