#!/bin/sh
# Без адреса core-api страница откроется, но вход упадёт с 502 — лучше сразу остановиться с понятной ошибкой.
if [ -z "$CORE_API_URL" ]; then
    echo "web-app: не задан CORE_API_URL (адрес core-api без пути, например http://core-api:8080)" >&2
    exit 1
fi
