from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.config import Settings


class Role(StrEnum):
    INSPECTOR = "inspector"
    EDGE_GATEWAY = "edge_gateway"
    QUALITY_MANAGER = "quality_manager"
    ML_ENGINEER = "ml_engineer"
    ADMIN = "admin"
    AUDITOR = "auditor"
    FDE = "fde"


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor_id: str
    tenant_id: str
    roles: frozenset[Role]


bearer = HTTPBearer(auto_error=False)


def create_access_token(
    settings: Settings,
    *,
    actor_id: str,
    tenant_id: str,
    roles: list[Role | str],
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": actor_id,
        "tenant_id": tenant_id,
        "roles": [str(role) for role in roles],
        "iss": settings.auth_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes or settings.access_token_minutes),
    }
    return jwt.encode(
        payload,
        settings.auth_secret.get_secret_value(),
        algorithm=settings.auth_algorithm,
    )


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    settings: Settings = request.app.state.settings
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.auth_secret.get_secret_value(),
            algorithms=[settings.auth_algorithm],
            issuer=settings.auth_issuer,
        )
        roles = frozenset(Role(role) for role in payload.get("roles", []))
        return Principal(actor_id=payload["sub"], tenant_id=payload["tenant_id"], roles=roles)
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token"
        ) from exc


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_roles(*allowed: Role) -> Callable[[Principal], Principal]:
    allowed_set = frozenset(allowed)

    def dependency(principal: PrincipalDep) -> Principal:
        if principal.roles.isdisjoint(allowed_set):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return dependency
