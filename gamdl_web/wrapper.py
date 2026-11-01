from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from gamdl.api.wrapper import TARGET_WRAPPER_API_VERSION

from . import docker_ctl
from .config import Settings

LOGOUT_WAIT_SECS = 45
# A dialog from Apple that nobody can answer; the wrapper only clicks through sign-in.
APPLE_DIALOG_RE = re.compile(r'ProtocolDialog id=\d+ title="(.*)" buttons=.*picked_existing_apple_id=no')
APPLE_REFUSALS = {
    "device limit": "이 Apple 계정의 기기 등록 한도가 찼습니다. Apple Music 앱의 계정 설정 → 기기 관리에서 안 쓰는 기기를 제거하세요.",
    "more than one device": "이 Apple 계정이 다른 기기에서 재생 중입니다. 다른 기기의 재생을 멈추고 다시 시도하세요.",
    "no longer available": "이 Apple 계정의 스토어에서는 받을 수 없는 곡입니다.",
}

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


async def explain_error(settings: Settings, message: str) -> str:
    """Why Apple refused a song. The wrapper's error only carries a meaningless
    number; Apple's reason reaches its log as a dialog."""
    if "playback_dispatch_failed" not in message:
        return message
    try:
        titles = APPLE_DIALOG_RE.findall(await docker_ctl.logs(settings.wrapper_container, tail=30))
    except ValueError:
        return message
    if not titles:
        return message
    title = titles[-1]
    for phrase, text in APPLE_REFUSALS.items():
        if phrase in title.lower():
            return text
    return f"Apple 안내: {title}"


async def login(settings: Settings, username: str, password: str) -> tuple[int, Any]:
    status, body = await _post(settings, "/login", {"username": username, "password": password})
    return status, _scrub(body)


async def login_2fa(settings: Settings, code: str) -> tuple[int, Any]:
    status, body = await _post(settings, "/login/2fa", {"code": code})
    return status, _scrub(body)


async def _settled_state(settings: Settings) -> str | None:
    """The sign-in state once a restarted wrapper has finished starting up."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(5, connect=3)) as client:
        for _ in range(LOGOUT_WAIT_SECS):
            try:
                response = await client.get(f"{settings.wrapper_url}/me")
                state = (_body(response).get("auth") or {}).get("state") if response.is_success else None
            except (httpx.HTTPError, AttributeError):
                state = None
            if state and state != "in_progress":
                return state
            await asyncio.sleep(1)
    return None


async def logout(settings: Settings) -> tuple[int, Any]:
    """Sign out for good. DELETE /login only clears the wrapper's memory: Apple's
    session files stay, and the next /me signs straight back in from them. So the
    files go first, then the memory, and a restart drops what the Apple libraries
    still hold."""
    container = settings.wrapper_container
    ok, detail = await docker_ctl.clear_session(container)
    if not ok:
        return 502, {"error": f"wrapper 로그인 파일을 지우지 못했습니다: {detail[-200:]}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
        try:
            await client.delete(f"{settings.wrapper_url}/login")
        except httpx.HTTPError as e:
            return 502, {"error": f"wrapper에 연결할 수 없습니다: {type(e).__name__}"}
    ok, detail = await docker_ctl.action(container, "restart")
    if not ok:
        return 502, {"error": f"wrapper를 재시작하지 못했습니다: {detail[-200:]}"}
    state = await _settled_state(settings)
    if state != "logged_out":
        return 502, {"error": f"로그아웃을 확인하지 못했습니다 (상태: {state or '응답 없음'})"}
    return 200, {"state": state}
