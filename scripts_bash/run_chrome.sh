#!/bin/bash

PORTS=(9222 9223 9224 9225 9226)

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