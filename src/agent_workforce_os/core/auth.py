from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from .models import Membership, Role, User


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.OWNER: {"*"},
    Role.ADMIN: {
        "org:read",
        "org:write",
        "project:read",
        "project:write",
        "users:write",
        "workers:read",
        "workers:write",
        "tasks:read",
        "tasks:write",
        "documents:read",
        "documents:write",
        "agents:run",
        "queue:read",
        "queue:write",
        "approvals:read",
        "approvals:write",
        "traces:read",
        "evals:run",
    },
    Role.MANAGER: {
        "org:read",
        "org:write",
        "project:read",
        "project:write",
        "users:write",
        "workers:read",
        "tasks:read",
        "tasks:write",
        "documents:read",
        "documents:write",
        "agents:run",
        "queue:read",
        "queue:write",
        "approvals:read",
        "approvals:write",
        "traces:read",
        "evals:run",
    },
    Role.AGENT_OPERATOR: {
        "project:read",
        "workers:read",
        "tasks:read",
        "tasks:write",
        "documents:read",
        "documents:write",
        "agents:run",
        "queue:read",
        "queue:write",
        "approvals:read",
        "traces:read",
        "evals:run",
    },
    Role.VIEWER: {
        "org:read",
        "project:read",
        "workers:read",
        "tasks:read",
        "documents:read",
        "queue:read",
        "approvals:read",
        "traces:read",
    },
}


@dataclass
class Principal:
    user: User
    memberships: list[Membership]

    @property
    def organization_id(self) -> str:
        return self.user.organization_id


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return f"agos_{secrets.token_urlsafe(32)}"


def has_permission(principal: Principal, permission: str, project_id: str | None = None) -> bool:
    for membership in principal.memberships:
        if project_id and membership.project_id and membership.project_id != project_id:
            continue
        permissions = ROLE_PERMISSIONS[membership.role]
        if "*" in permissions or permission in permissions:
            return True
    return False


def require_permission(principal: Principal, permission: str, project_id: str | None = None) -> None:
    if not has_permission(principal, permission, project_id):
        raise PermissionError(f"Missing permission: {permission}")
