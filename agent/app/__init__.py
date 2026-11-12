"""agent: понимание запроса, выбор инструментов и формирование ответа (контракт B)."""

from __future__ import annotations

from typing import Callable

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from . import contract
from .chat import answer
from .context import InvalidRequest
from .tools import Tools, tools_from_env

SERVICE = "agent"
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


def create_app(tools_factory: Callable[[str, str], Tools] = tools_from_env) -> Flask:
    """`tools_factory(token, request_id)` даёт клиенты инструментов; в тестах его подменяют."""
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": SERVICE, "version": VERSION})

    @app.post("/v1/chat")
    def chat():
        # Токен не проверяем: его подписал core-api, агент лишь пересылает его соседям (A4).
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not request.headers.get("Authorization", "").startswith("Bearer ") or not token:
            return error_response(401)
        body = request.get_json(silent=True)
        problems = ["тело запроса не JSON"] if body is None else contract.errors(body, "ChatRequest")
        if problems:
            app.logger.info("запрос не по контракту B: %s", "; ".join(problems))
            return error_response(422)
        try:
            return jsonify(answer(body, tools_factory(token, body["request_id"])))
        except InvalidRequest as exc:
            return error_response(422, str(exc))

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return error_response(exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        app.logger.exception("необработанная ошибка: %s", exc)
        return error_response(500)

    return app
