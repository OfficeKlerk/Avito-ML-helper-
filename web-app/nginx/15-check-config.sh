#!/bin/sh
# Вставляем в конфигурацию nginx только адрес без пути, параметров и учётных данных.
if ! valid_url=$(printf '%s\n' "$CORE_API_URL" | grep -Ex 'https?://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?') ||
    [ "$valid_url" != "$CORE_API_URL" ]; then
    echo "web-app: CORE_API_URL должен быть HTTP(S)-адресом без пути, например http://core-api:8080" >&2
    exit 1
fi
