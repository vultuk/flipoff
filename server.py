from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / 'flipoff.config.json'
ADMIN_PASSWORD_ENV = 'FLIPOFF_ADMIN_PASSWORD'

DEFAULT_COLS = 18
DEFAULT_ROWS = 5
DEFAULT_API_MESSAGE_DURATION_SECONDS = 30
DEFAULT_MESSAGES = [
    ['', 'GOD IS IN', 'THE DETAILS .', '- LUDWIG MIES', ''],
    ['', 'STAY HUNGRY', 'STAY FOOLISH', '- STEVE JOBS', ''],
    ['', 'GOOD DESIGN IS', 'GOOD BUSINESS', '- THOMAS WATSON', ''],
    ['', 'LESS IS MORE', '', '- MIES VAN DER', 'ROHE'],
    ['', 'MAKE IT SIMPLE', 'BUT SIGNIFICANT', '- DON DRAPER', ''],
    ['', 'HAVE NO FEAR OF', 'PERFECTION', '- SALVADOR DALI', ''],
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass
class DisplayConfig:
    cols: int
    rows: int
    default_messages: list[list[str]]
    api_message_duration_seconds: int

    def serialize(self) -> dict[str, Any]:
        return {
            'cols': self.cols,
            'rows': self.rows,
            'defaultMessages': [message.copy() for message in self.default_messages],
            'apiMessageDurationSeconds': self.api_message_duration_seconds,
        }


@dataclass
class MessageState:
    has_override: bool = False
    lines: list[str] = field(default_factory=list)
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

    def clear(self, rows: int) -> None:
        self.has_override = False
        self.lines = [''] * rows
        self.updated_at = None


@dataclass
class OverrideTaskState:
    task: asyncio.Task | None = None


DISPLAY_CONFIG_KEY = web.AppKey('display_config', DisplayConfig)
MESSAGE_STATE_KEY = web.AppKey('message_state', MessageState)
WS_CLIENTS_KEY = web.AppKey('ws_clients', set)
ADMIN_PASSWORD_KEY = web.AppKey('admin_password', str)
GENERATED_ADMIN_PASSWORD_KEY = web.AppKey('generated_admin_password', bool)
SESSION_TOKENS_KEY = web.AppKey('session_tokens', set)
CONFIG_PATH_KEY = web.AppKey('config_path', object)
OVERRIDE_TASK_KEY = web.AppKey('override_task', OverrideTaskState)


def default_display_config() -> DisplayConfig:
    return DisplayConfig(
        cols=DEFAULT_COLS,
        rows=DEFAULT_ROWS,
        default_messages=[message.copy() for message in DEFAULT_MESSAGES],
        api_message_duration_seconds=DEFAULT_API_MESSAGE_DURATION_SECONDS,
    )


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({'error': message}, status=status)


def _coerce_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"'{field_name}' must be an integer.")

    if not minimum <= value <= maximum:
        raise ValueError(f"'{field_name}' must be between {minimum} and {maximum}.")

    return value


def pad_lines(lines: list[str], rows: int) -> list[str]:
    return lines + [''] * max(0, rows - len(lines))


def center_lines(lines: list[str], rows: int) -> list[str]:
    top_padding = max(0, (rows - len(lines)) // 2)
    bottom_padding = max(0, rows - len(lines) - top_padding)
    return [''] * top_padding + lines + [''] * bottom_padding


def normalize_default_messages(messages: Any, cols: int, rows: int) -> list[list[str]]:
    if not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("'defaultMessages' must be a non-empty array of message arrays.")

    normalized_messages: list[list[str]] = []
    for message_index, message in enumerate(messages, start=1):
        if not isinstance(message, list) or len(message) == 0:
            raise ValueError(f'Default message {message_index} must be a non-empty array of strings.')

        if len(message) > rows:
            raise ValueError(f'Default message {message_index} exceeds the configured row count of {rows}.')

        normalized_lines: list[str] = []
        for line_index, line in enumerate(message, start=1):
            if not isinstance(line, str):
                raise ValueError(f'Default message {message_index}, line {line_index} must be a string.')

            normalized_line = line.strip().upper()
            if len(normalized_line) > cols:
                raise ValueError(
                    f'Default message {message_index}, line {line_index} exceeds {cols} characters.'
                )

            normalized_lines.append(normalized_line)

        normalized_messages.append(pad_lines(normalized_lines, rows))

    return normalized_messages


def normalize_display_config_payload(payload: Any) -> DisplayConfig:
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')

    cols = _coerce_int(payload.get('cols'), 'cols', 6, 40)
    rows = _coerce_int(payload.get('rows'), 'rows', 1, 10)
    api_message_duration_seconds = _coerce_int(
        payload.get('apiMessageDurationSeconds'),
        'apiMessageDurationSeconds',
        1,
        86400,
    )
    default_messages = normalize_default_messages(payload.get('defaultMessages'), cols, rows)

    return DisplayConfig(
        cols=cols,
        rows=rows,
        default_messages=default_messages,
        api_message_duration_seconds=api_message_duration_seconds,
    )


def load_display_config(config_path: Path | None) -> DisplayConfig:
    if config_path is None or not config_path.exists():
        return default_display_config()

    with config_path.open('r', encoding='utf-8') as config_file:
        payload = json.load(config_file)

    return normalize_display_config_payload(payload)


def save_display_config(config_path: Path | None, config: DisplayConfig) -> None:
    if config_path is None:
        return

    with config_path.open('w', encoding='utf-8') as config_file:
        json.dump(config.serialize(), config_file, indent=2)
        config_file.write('\n')


def build_message_event(state: MessageState) -> dict[str, Any]:
    return {
        'type': 'message_state',
        'payload': state.serialize(),
    }


def build_config_event(config: DisplayConfig) -> dict[str, Any]:
    return {
        'type': 'config_state',
        'payload': config.serialize(),
    }


async def broadcast_event(app: web.Application, event: dict[str, Any]) -> None:
    stale_clients = []

    for ws in set(app[WS_CLIENTS_KEY]):
        if ws.closed:
            stale_clients.append(ws)
            continue

        try:
            await ws.send_json(event)
        except ConnectionResetError:
            stale_clients.append(ws)

    for ws in stale_clients:
        app[WS_CLIENTS_KEY].discard(ws)


async def broadcast_message_state(app: web.Application) -> None:
    await broadcast_event(app, build_message_event(app[MESSAGE_STATE_KEY]))


async def broadcast_display_config(app: web.Application) -> None:
    await broadcast_event(app, build_config_event(app[DISPLAY_CONFIG_KEY]))


def normalize_message(message: Any, cols: int, rows: int) -> list[str]:
    if not isinstance(message, str):
        raise ValueError("The 'message' field must be a string.")

    collapsed = re.sub(r'\s+', ' ', message.strip())
    if not collapsed:
        return [''] * rows

    words = collapsed.split(' ')
    if any(len(word) > cols for word in words):
        raise ValueError(f"Each word in 'message' must be {cols} characters or fewer.")

    lines: list[str] = []
    current_line = ''

    for word in words:
        candidate = word if not current_line else f'{current_line} {word}'
        if len(candidate) <= cols:
            current_line = candidate
            continue

        lines.append(current_line.upper())
        current_line = word

        if len(lines) >= rows:
            raise ValueError(f"'message' must fit within {rows} lines of {cols} characters.")

    if current_line:
        lines.append(current_line.upper())

    if len(lines) > rows:
        raise ValueError(f"'message' must fit within {rows} lines of {cols} characters.")

    return center_lines(lines, rows)


def normalize_lines(lines: Any, cols: int, rows: int) -> list[str]:
    if not isinstance(lines, list):
        raise ValueError("The 'lines' field must be an array of strings.")

    if not 1 <= len(lines) <= rows:
        raise ValueError(f"'lines' must contain between 1 and {rows} items.")

    normalized: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, str):
            raise ValueError(f'Line {index} must be a string.')

        normalized_line = line.strip().upper()
        if len(normalized_line) > cols:
            raise ValueError(f'Line {index} exceeds {cols} characters.')

        normalized.append(normalized_line)

    return pad_lines(normalized, rows)


def normalize_payload(payload: Any, config: DisplayConfig) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')

    has_message = 'message' in payload
    has_lines = 'lines' in payload

    if has_message == has_lines:
        raise ValueError("Request body must include exactly one of 'message' or 'lines'.")

    if has_message:
        return normalize_message(payload['message'], config.cols, config.rows)

    return normalize_lines(payload['lines'], config.cols, config.rows)


def is_authenticated(request: web.Request) -> bool:
    session_token = request.cookies.get('flipoff_admin_session')
    return bool(session_token and session_token in request.app[SESSION_TOKENS_KEY])


def require_admin(request: web.Request) -> None:
    if not is_authenticated(request):
        raise web.HTTPUnauthorized(
            text=json.dumps({'error': 'Authentication required.'}),
            content_type='application/json',
        )


def cancel_override_task(app: web.Application) -> None:
    override_task_state = app[OVERRIDE_TASK_KEY]
    if override_task_state.task is not None:
        override_task_state.task.cancel()
        override_task_state.task = None


async def clear_override(app: web.Application, *, broadcast: bool = True) -> None:
    cancel_override_task(app)
    state = app[MESSAGE_STATE_KEY]

    if not state.has_override:
        return

    state.clear(app[DISPLAY_CONFIG_KEY].rows)

    if broadcast:
        await broadcast_message_state(app)


def schedule_override_clear(app: web.Application) -> None:
    cancel_override_task(app)
    duration = app[DISPLAY_CONFIG_KEY].api_message_duration_seconds
    override_task_state = app[OVERRIDE_TASK_KEY]

    async def _expire_override() -> None:
        try:
            await asyncio.sleep(duration)
            await clear_override(app)
        except asyncio.CancelledError:
            raise

    override_task_state.task = asyncio.create_task(_expire_override())


async def index_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'index.html')


async def admin_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'admin.html')


async def get_display_config(_: web.Request) -> web.Response:
    return web.json_response(apply_runtime_display_config(_.app[DISPLAY_CONFIG_KEY]))


def apply_runtime_display_config(config: DisplayConfig) -> dict[str, Any]:
    return config.serialize()


async def get_message(request: web.Request) -> web.Response:
    return web.json_response(request.app[MESSAGE_STATE_KEY].serialize())


async def post_message(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    try:
        normalized_lines = normalize_payload(payload, request.app[DISPLAY_CONFIG_KEY])
    except ValueError as exc:
        return _json_error(str(exc))

    state = request.app[MESSAGE_STATE_KEY]
    state.set_override(normalized_lines)
    schedule_override_clear(request.app)
    await broadcast_message_state(request.app)
    return web.json_response(state.serialize())


async def delete_message(request: web.Request) -> web.Response:
    await clear_override(request.app)
    return web.json_response(request.app[MESSAGE_STATE_KEY].serialize())


async def admin_session_create(request: web.Request) -> web.Response:
    configured_password = request.app[ADMIN_PASSWORD_KEY]
    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    password = payload.get('password') if isinstance(payload, dict) else None
    if password != configured_password:
        return _json_error('Invalid password.', status=401)

    session_token = secrets.token_urlsafe(32)
    request.app[SESSION_TOKENS_KEY].add(session_token)

    response = web.json_response({'authenticated': True})
    response.set_cookie(
        'flipoff_admin_session',
        session_token,
        httponly=True,
        samesite='Lax',
        secure=request.secure,
        max_age=60 * 60 * 12,
        path='/',
    )
    return response


async def admin_session_delete(request: web.Request) -> web.Response:
    session_token = request.cookies.get('flipoff_admin_session')
    if session_token:
        request.app[SESSION_TOKENS_KEY].discard(session_token)

    response = web.json_response({'authenticated': False})
    response.del_cookie('flipoff_admin_session', path='/')
    return response


async def admin_config_get(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(apply_runtime_display_config(request.app[DISPLAY_CONFIG_KEY]))


async def admin_config_put(request: web.Request) -> web.Response:
    require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    try:
        updated_config = normalize_display_config_payload(payload)
    except ValueError as exc:
        return _json_error(str(exc))

    current_config = request.app[DISPLAY_CONFIG_KEY]
    current_config.cols = updated_config.cols
    current_config.rows = updated_config.rows
    current_config.default_messages = updated_config.default_messages
    current_config.api_message_duration_seconds = updated_config.api_message_duration_seconds

    save_display_config(request.app[CONFIG_PATH_KEY], current_config)
    await clear_override(request.app)
    await broadcast_display_config(request.app)

    return web.json_response(apply_runtime_display_config(current_config))


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    request.app[WS_CLIENTS_KEY].add(ws)
    await ws.send_json(build_config_event(request.app[DISPLAY_CONFIG_KEY]))
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


async def cleanup_background_tasks(app: web.Application) -> None:
    override_task = app[OVERRIDE_TASK_KEY].task
    cancel_override_task(app)
    if override_task is not None:
        with suppress(asyncio.CancelledError):
            await override_task


async def close_websockets(app: web.Application) -> None:
    websocket_close_tasks = [
        ws.close(code=1001, message=b'server shutdown')
        for ws in set(app[WS_CLIENTS_KEY])
        if not ws.closed
    ]

    if websocket_close_tasks:
        await asyncio.gather(*websocket_close_tasks, return_exceptions=True)

    app[WS_CLIENTS_KEY].clear()


def resolve_admin_password(admin_password: str | None) -> tuple[str, bool]:
    if admin_password:
        return admin_password, False

    env_password = os.environ.get(ADMIN_PASSWORD_ENV)
    if env_password:
        return env_password, False

    return secrets.token_urlsafe(16), True


async def announce_admin_password(app: web.Application) -> None:
    if app[GENERATED_ADMIN_PASSWORD_KEY]:
        print(f'[flipoff] Generated admin password: {app[ADMIN_PASSWORD_KEY]}', flush=True)


def create_app(*, admin_password: str | None = None, config_path: Path | None = CONFIG_PATH) -> web.Application:
    display_config = load_display_config(config_path)
    message_state = MessageState(lines=[''] * display_config.rows)
    resolved_admin_password, generated_admin_password = resolve_admin_password(admin_password)

    app = web.Application()
    app[DISPLAY_CONFIG_KEY] = display_config
    app[MESSAGE_STATE_KEY] = message_state
    app[WS_CLIENTS_KEY] = set()
    app[ADMIN_PASSWORD_KEY] = resolved_admin_password
    app[GENERATED_ADMIN_PASSWORD_KEY] = generated_admin_password
    app[SESSION_TOKENS_KEY] = set()
    app[CONFIG_PATH_KEY] = config_path
    app[OVERRIDE_TASK_KEY] = OverrideTaskState()

    app.on_startup.append(announce_admin_password)
    app.on_shutdown.append(close_websockets)
    app.on_cleanup.append(cleanup_background_tasks)

    app.router.add_get('/', index_handler)
    app.router.add_get('/index.html', index_handler)
    app.router.add_get('/admin', admin_handler)
    app.router.add_get('/admin/', admin_handler)
    app.router.add_get('/api/config', get_display_config)
    app.router.add_get('/api/message', get_message)
    app.router.add_post('/api/message', post_message)
    app.router.add_delete('/api/message', delete_message)
    app.router.add_post('/api/admin/session', admin_session_create)
    app.router.add_delete('/api/admin/session', admin_session_delete)
    app.router.add_get('/api/admin/config', admin_config_get)
    app.router.add_put('/api/admin/config', admin_config_put)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_static('/css', PROJECT_ROOT / 'css')
    app.router.add_static('/js', PROJECT_ROOT / 'js')
    app.router.add_get('/screenshot.png', screenshot_handler)
    app.router.add_get('/favicon.ico', favicon_handler)

    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    web.run_app(create_app(), host='0.0.0.0', port=port)
