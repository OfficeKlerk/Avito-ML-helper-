"""K3: verify JWT before applying public/team/role visibility rules."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import jwt


class KnowledgeAccessError(Exception):
    def __init__(self, status: int):
        self.status = status
        # Never include a JWT, title, path or document id in an access error.
        super().__init__({401: "Нужно войти заново.", 403: "Нет доступа.", 404: "Не найдено."}[status])


@dataclass(frozen=True)
class Principal:
    user_id: str
    login: str
    role: str
    team_id: str | None


def authenticate(authorization: str | None, secret: str) -> Principal:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("JWT_SECRET must be configured")
    parts = authorization.split() if isinstance(authorization, str) else []
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise KnowledgeAccessError(401)
    try:
        claims = jwt.decode(parts[1], secret, algorithms=["HS256"], options={
            "require": ["sub", "login", "role", "exp"],
        })
        user_id, login, role = claims["sub"], claims["login"], claims["role"]
        # team_id is required but null is valid for a user without a team (e.g. HR).
        team_id, expires = claims["team_id"], claims["exp"]
        if not isinstance(user_id, str) or not re.fullmatch(r"u_[a-z0-9_]+", user_id):
            raise ValueError
        if not isinstance(login, str) or not login.strip():
            raise ValueError
        if not isinstance(role, str) or role not in {"intern", "mentor", "manager", "hr"}:
            raise ValueError
        if team_id is not None and (not isinstance(team_id, str) or not re.fullmatch(r"team_[a-z0-9_]+", team_id)):
            raise ValueError
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
            raise ValueError
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise KnowledgeAccessError(401) from exc
    return Principal(user_id, login, role, team_id)


def can_read(visibility: tuple[str, ...], principal: Principal) -> bool:
    allowed = {"public", f"role:{principal.role}"}
    if principal.team_id is not None:
        allowed.add(f"team:{principal.team_id}")
    return bool(allowed.intersection(visibility))
