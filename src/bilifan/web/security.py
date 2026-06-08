from __future__ import annotations

import secrets
from dataclasses import dataclass


def generate_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class TokenAuth:
    token: str

    def require(self, *, header_token: str | None, query_token: str | None) -> None:
        if not any(
            candidate and secrets.compare_digest(candidate, self.token)
            for candidate in (header_token, query_token)
        ):
            raise PermissionError("Invalid Bilifan Web UI token.")
