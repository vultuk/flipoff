from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

GRID_COLS = 18
GRID_ROWS = 5
EMPTY_LINES = [''] * GRID_ROWS
PROJECT_ROOT = Path(__file__).resolve().parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass
class MessageState:
    has_override: bool = False
    lines: list[str] = field(default_factory=lambda: EMPTY_LINES.copy())
    updated_at: str | None = None

    def serialize(self) -> dict[str, Any]:
        return {
            'hasOverride': self.has_override,
            'lines': self.lines.copy(),
            'updatedAt': self.updated_at,
        }

    def set_override(self, lines: list[str]) -> None:
        self.has_override = True
        self.lines = lines.copy()
        self.updated_at = _utc_now()

    def clear(self) -> None:
        self.has_override = False
        self.lines = EMPTY_LINES.copy()
        self.updated_at = None


MESSAGE_STATE_KEY = web.AppKey('message_state', MessageState)
WS_CLIENTS_KEY = web.AppKey('ws_clients', set)


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({'error': message}, status=status)


def normalize_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')

    has_message = 'message' in payload
    has_lines = 'lines' in payload

    if has_message == has_lines:
        raise ValueError("Request body must include exactly one of 'message' or 'lines'.")

    if has_message:
        return normalize_message(payload['message'])

    return normalize_lines(payload['lines'])


def normalize_message(message: Any) -> list[str]:
    if not isinstance(message, str):
        raise ValueError("The 'message' field must be a string.")

    collapsed = re.sub(r'\s+', ' ', message.strip())
    if not collapsed:
        return EMPTY_LINES.copy()

    words = collapsed.split(' ')
    if any(len(word) > GRID_COLS for word in words):
        raise ValueError(f"Each word in 'message' must be {GRID_COLS} characters or fewer.")

    lines: list[str] = []
    current_line = ''

    for word in words:
        candidate = word if not current_line else f'{current_line} {word}'
        if len(candidate) <= GRID_COLS:
            current_line = candidate
            continue

        lines.append(current_line.upper())
        current_line = word

        if len(lines) >= GRID_ROWS:
            raise ValueError(f"'message' must fit within {GRID_ROWS} lines of {GRID_COLS} characters.")

    if current_line:
        lines.append(current_line.upper())

    if len(lines) > GRID_ROWS:
        raise ValueError(f"'message' must fit within {GRID_ROWS} lines of {GRID_COLS} characters.")

    return center_lines(lines)


def normalize_lines(lines: Any) -> list[str]:
    if not isinstance(lines, list):
        raise ValueError("The 'lines' field must be an array of strings.")

    if not 1 <= len(lines) <= GRID_ROWS:
        raise ValueError(f"'lines' must contain between 1 and {GRID_ROWS} items.")

    normalized: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, str):
            raise ValueError(f"Line {index} must be a string.")

        normalized_line = line.strip().upper()
        if len(normalized_line) > GRID_COLS:
            raise ValueError(f'Line {index} exceeds {GRID_COLS} characters.')

        normalized.append(normalized_line)

    return normalized + [''] * (GRID_ROWS - len(normalized))


def center_lines(lines: list[str]) -> list[str]:
    top_padding = max(0, (GRID_ROWS - len(lines)) // 2)
    bottom_padding = max(0, GRID_ROWS - len(lines) - top_padding)
    return [''] * top_padding + lines + [''] * bottom_padding


def build_message_event(state: MessageState) -> dict[str, Any]:
    return {
        'type': 'message_state',
        'payload': state.serialize(),
    }


async def broadcast_state(app: web.Application) -> None:
    message = build_message_event(app[MESSAGE_STATE_KEY])
    stale_clients = []

    for ws in set(app[WS_CLIENTS_KEY]):
        if ws.closed:
            stale_clients.append(ws)
            continue

        try:
            await ws.send_json(message)
        except ConnectionResetError:
            stale_clients.append(ws)

    for ws in stale_clients:
        app[WS_CLIENTS_KEY].discard(ws)


async def index_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'index.html')


async def get_message(request: web.Request) -> web.Response:
    return web.json_response(request.app[MESSAGE_STATE_KEY].serialize())


async def post_message(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    try:
        normalized_lines = normalize_payload(payload)
    except ValueError as exc:
        return _json_error(str(exc))

    state = request.app[MESSAGE_STATE_KEY]
    state.set_override(normalized_lines)
    await broadcast_state(request.app)
    return web.json_response(state.serialize())


async def delete_message(request: web.Request) -> web.Response:
    state = request.app[MESSAGE_STATE_KEY]
    state.clear()
    await broadcast_state(request.app)
    return web.json_response(state.serialize())


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    request.app[WS_CLIENTS_KEY].add(ws)
    await ws.send_json(build_message_event(request.app[MESSAGE_STATE_KEY]))

    try:
        async for _ in ws:
            continue
    finally:
        request.app[WS_CLIENTS_KEY].discard(ws)

    return ws


async def screenshot_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'screenshot.png')


async def favicon_handler(_: web.Request) -> web.Response:
    return web.Response(status=204)


def create_app() -> web.Application:
    app = web.Application()
    app[MESSAGE_STATE_KEY] = MessageState()
    app[WS_CLIENTS_KEY] = set()

    app.router.add_get('/', index_handler)
    app.router.add_get('/index.html', index_handler)
    app.router.add_get('/api/message', get_message)
    app.router.add_post('/api/message', post_message)
    app.router.add_delete('/api/message', delete_message)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_static('/css', PROJECT_ROOT / 'css')
    app.router.add_static('/js', PROJECT_ROOT / 'js')
    app.router.add_get('/screenshot.png', screenshot_handler)
    app.router.add_get('/favicon.ico', favicon_handler)

    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    web.run_app(create_app(), host='0.0.0.0', port=port)
