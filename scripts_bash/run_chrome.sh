#!/bin/bash

# Дефолтные порты
DEFAULT_PORTS=(9222 9223 9224 9225 9226)

# Если переданы аргументы, использовать их, иначе дефолтные
if [ $# -gt 0 ]; then
    PORTS=("$@")
else
    PORTS=("${DEFAULT_PORTS[@]}")
fi

echo "Запуск Chrome на портах: ${PORTS[@]}"

# Запустить Chrome на каждом порту в фоне
for PORT in "${PORTS[@]}"; do
    google-chrome \
        --remote-debugging-port=$PORT \
        --user-data-dir=/tmp/chrome-debug_$PORT \
        --no-default-browser-check \
        --no-sandbox \
        --no-first-run &
    echo "Chrome запущен на порту $PORT (PID: $!)"
done