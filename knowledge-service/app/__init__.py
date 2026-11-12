"""knowledge-service: поиск по базе знаний с учётом прав (контракт E)."""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

SERVICE = "knowledge-service"
VERSION = "0.1.0"

# HTTP-статус → код ошибки единого формата (contracts/common.yaml, ErrorResponse).
ERROR_CODES = {
    400: "validation",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "not_found",
    409: "conflict",
    422: "validation",
    429: "rate_limited",
    503: "unavailable",
}
ERROR_MESSAGES = {
    "validation": "Запрос не прошёл проверку.",
    "unauthorized": "Нужно войти заново.",
    "forbidden": "Нет доступа.",
    "not_found": "Не найдено.",
    "conflict": "Действие сейчас невозможно.",
    "rate_limited": "Слишком много запросов. Попробуй чуть позже.",
    "unavailable": "Сервис временно недоступен. Попробуй ещё раз чуть позже.",
    "internal": "Что-то пошло не так. Мы уже разбираемся.",
}


def error_response(status: int, message: str | None = None):
    code = ERROR_CODES.get(status, "internal")
    return jsonify({"error": {"code": code, "message": message or ERROR_MESSAGES[code]}}), status


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": SERVICE, "version": VERSION})

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return error_response(exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        app.logger.exception("необработанная ошибка: %s", exc)
        return error_response(500)

    return app
