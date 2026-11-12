"""knowledge-service: поиск по базе знаний с учётом прав (контракт E)."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .access import KnowledgeAccessError
from .knowledge import KnowledgeBase, KnowledgeUnavailableError, knowledge_for_request
from .search import validate_request

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


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config.from_mapping(
        JWT_SECRET=os.environ.get("JWT_SECRET", ""),
        KB_DIR=os.environ.get("KB_DIR") or str(Path(__file__).resolve().parents[2] / "data" / "kb"),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.config.update(config or {})
    if not isinstance(app.config["JWT_SECRET"], str) or not app.config["JWT_SECRET"].strip():
        raise ValueError("JWT_SECRET must be configured")
    app.extensions["knowledge_base"] = KnowledgeBase.load(app.config["KB_DIR"])

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": SERVICE, "version": VERSION})

    @app.post("/v1/search")
    def search():
        view = knowledge_for_request()
        try:
            query, top_k = validate_request(request.get_json(silent=True))
        except ValueError:
            return error_response(422)
        return jsonify({"results": view.search(query, top_k)})

    @app.get("/v1/documents/<doc_id>")
    def document(doc_id):
        return jsonify(knowledge_for_request().document(doc_id).to_dict())

    @app.after_request
    def private_responses(response):
        if request.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(413)
    def oversized_request(exc):
        return error_response(422)

    @app.errorhandler(KnowledgeUnavailableError)
    def unavailable(exc):
        return error_response(503)

    @app.errorhandler(KnowledgeAccessError)
    def knowledge_error(exc: KnowledgeAccessError):
        return error_response(exc.status)

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return error_response(exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        app.logger.exception("необработанная ошибка: %s", exc)
        return error_response(500)

    return app
