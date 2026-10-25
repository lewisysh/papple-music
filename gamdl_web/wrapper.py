from __future__ import annotations

import asyncio
from typing import Any

import httpx
from gamdl.api.wrapper import TARGET_WRAPPER_API_VERSION

from .config import Settings

# Never forward Apple session tokens to the browser.
SAFE_AUTH_KEYS = {"state", "apple_id", "username", "storefront", "logged_in_at", "error", "error_code"}


def _sanitize_me(me: dict[str, Any]) -> dict[str, Any]:
    auth = me.get("auth") or {}
    return {
        "version": me.get("version"),
        "runtime": me.get("runtime"),
        "auth": {
            **{k: v for k, v in auth.items() if k in SAFE_AUTH_KEYS},
            "has_tokens": bool(auth.get("music_user_token") and auth.get("dev_token")),
        },
    }


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if k not in {"music_user_token", "dev_token", "dsid"}
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"error": response.text[:500]}


async def _port_open(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def get_status(settings: Settings) -> dict[str, Any]:
    status: dict[str, Any] = {
        "url": settings.wrapper_url,
        "decrypt": f"{settings.wrapper_decrypt_host}:{settings.wrapper_decrypt_port}",
        "required_version": TARGET_WRAPPER_API_VERSION,
        "reachable": False,
        "health": None,
        "me": None,
        "error": None,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
        try:
            response = await client.get(f"{settings.wrapper_url}/health")
            status["health"] = _body(response)
            status["reachable"] = True
        except httpx.HTTPError as e:
            status["error"] = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        if status["reachable"]:
            try:
                response = await client.get(f"{settings.wrapper_url}/me")
                me = _body(response)
                if response.is_success:
                    status["me"] = _sanitize_me(me)
                else:
                    status["error"] = f"/me → HTTP {response.status_code}: {_scrub(me)}"
            except httpx.HTTPError as e:
                status["error"] = f"/me 요청 실패: {type(e).__name__}"
    status["decrypt_open"] = await _port_open(
        settings.wrapper_decrypt_host, settings.wrapper_decrypt_port
    )
    version = (status["me"] or {}).get("version") or (status["health"] or {}).get("version")
    status["version"] = version
    status["version_ok"] = version == TARGET_WRAPPER_API_VERSION
    return status


async def _post(settings: Settings, path: str, payload: dict | None) -> tuple[int, Any]:
    # Apple's AuthenticateFlow can take a while; wrapper's own worker timeout is 60s.
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as client:
        try:
            response = await client.post(f"{settings.wrapper_url}{path}", json=payload)
        except httpx.HTTPError as e:
            return 502, {"error": f"wrapper에 연결할 수 없습니다: {type(e).__name__}"}
    return response.status_code, _scrub(_body(response))


async def login(settings: Settings, username: str, password: str) -> tuple[int, Any]:
    status, body = await _post(settings, "/login", {"username": username, "password": password})
    return status, _scrub(body)


async def login_2fa(settings: Settings, code: str) -> tuple[int, Any]:
    status, body = await _post(settings, "/login/2fa", {"code": code})
    return status, _scrub(body)


async def logout(settings: Settings) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
        try:
            response = await client.delete(f"{settings.wrapper_url}/login")
        except httpx.HTTPError as e:
            return 502, {"error": f"wrapper에 연결할 수 없습니다: {type(e).__name__}"}
    return response.status_code, _scrub(_body(response))
