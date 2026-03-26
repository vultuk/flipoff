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

from aiohttp import ClientSession, ClientTimeout, web

from plugins import load_plugins
from plugins.base import PluginContext, PluginField, ScreenPlugin

PROJECT_ROOT = Path(__file__).resolve().parent
USER_DATA_DIR = Path.home() / '.flipoff'
CONFIG_PATH = USER_DATA_DIR / 'config.json'
SCREENS_PATH = USER_DATA_DIR / 'screens.json'
ADMIN_PASSWORD_ENV = 'FLIPOFF_ADMIN_PASSWORD'

DEFAULT_COLS = 18
DEFAULT_ROWS = 5
DEFAULT_MESSAGE_DURATION_SECONDS = 4
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
    message_duration_seconds: int
    api_message_duration_seconds: int

    def serialize(self) -> dict[str, Any]:
        return {
            'cols': self.cols,
            'rows': self.rows,
            'defaultMessages': [message.copy() for message in self.default_messages],
            'messageDurationSeconds': self.message_duration_seconds,
            'apiMessageDurationSeconds': self.api_message_duration_seconds,
        }

    def serialize_settings(self) -> dict[str, Any]:
        return {
            'cols': self.cols,
            'rows': self.rows,
            'messageDurationSeconds': self.message_duration_seconds,
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


@dataclass
class ScreenState:
    screens: list[dict[str, Any]] = field(default_factory=list)
    common_settings: dict[str, Any] = field(default_factory=dict)
    refresh_tasks: dict[str, asyncio.Task] = field(default_factory=dict)


DISPLAY_CONFIG_KEY = web.AppKey('display_config', DisplayConfig)
MESSAGE_STATE_KEY = web.AppKey('message_state', MessageState)
SCREEN_STATE_KEY = web.AppKey('screen_state', ScreenState)
WS_CLIENTS_KEY = web.AppKey('ws_clients', set)
ADMIN_PASSWORD_KEY = web.AppKey('admin_password', str)
GENERATED_ADMIN_PASSWORD_KEY = web.AppKey('generated_admin_password', bool)
SESSION_TOKENS_KEY = web.AppKey('session_tokens', set)
CONFIG_PATH_KEY = web.AppKey('config_path', object)
SCREENS_PATH_KEY = web.AppKey('screens_path', object)
PLUGINS_KEY = web.AppKey('plugins', dict)
PLUGIN_HTTP_SESSION_KEY = web.AppKey('plugin_http_session', object)
OVERRIDE_TASK_KEY = web.AppKey('override_task', OverrideTaskState)


def default_display_config() -> DisplayConfig:
    return DisplayConfig(
        cols=DEFAULT_COLS,
        rows=DEFAULT_ROWS,
        default_messages=[message.copy() for message in DEFAULT_MESSAGES],
        message_duration_seconds=DEFAULT_MESSAGE_DURATION_SECONDS,
        api_message_duration_seconds=DEFAULT_API_MESSAGE_DURATION_SECONDS,
    )


def build_default_manual_screens() -> list[dict[str, Any]]:
    return [
        {
            'id': f'manual-{index + 1}',
            'type': 'manual',
            'name': '',
            'enabled': True,
            'lines': trim_message_lines(message),
        }
        for index, message in enumerate(DEFAULT_MESSAGES)
    ]


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({'error': message}, status=status)


def _coerce_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"'{field_name}' must be an integer.")

    if not minimum <= value <= maximum:
        raise ValueError(f"'{field_name}' must be between {minimum} and {maximum}.")

    return value


def _coerce_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"'{field_name}' must be a boolean.")
    return value


def _coerce_optional_string(value: Any, field_name: str) -> str:
    if value is None:
        return ''

    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a string.")

    return value.strip()


def pad_lines(lines: list[str], rows: int) -> list[str]:
    return lines + [''] * max(0, rows - len(lines))


def center_lines(lines: list[str], rows: int) -> list[str]:
    top_padding = max(0, (rows - len(lines)) // 2)
    bottom_padding = max(0, rows - len(lines) - top_padding)
    return [''] * top_padding + lines + [''] * bottom_padding


def trim_message_lines(message: list[str]) -> list[str]:
    trimmed = message.copy()
    while len(trimmed) > 1 and trimmed[-1] == '':
        trimmed.pop()
    return trimmed


def normalize_message_lines(
    lines: Any,
    *,
    cols: int,
    rows: int,
    field_name: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(lines, list):
        raise ValueError(f"'{field_name}' must be an array of strings.")

    if not lines and allow_empty:
        return []

    if not 1 <= len(lines) <= rows:
        raise ValueError(f"'{field_name}' must contain between 1 and {rows} items.")

    normalized: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not isinstance(line, str):
            raise ValueError(f"{field_name} line {index} must be a string.")

        normalized_line = line.strip().upper()
        if len(normalized_line) > cols:
            raise ValueError(f"{field_name} line {index} exceeds {cols} characters.")

        normalized.append(normalized_line)

    return trim_message_lines(normalized)


def normalize_default_messages(messages: Any, cols: int, rows: int) -> list[list[str]]:
    if not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("'defaultMessages' must be a non-empty array of message arrays.")

    return [
        pad_lines(
            normalize_message_lines(
                message,
                cols=cols,
                rows=rows,
                field_name=f'defaultMessages[{index}]',
            ),
            rows,
        )
        for index, message in enumerate(messages)
    ]


def normalize_runtime_settings_payload(payload: Any) -> tuple[int, int, int, int]:
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')

    cols = _coerce_int(payload.get('cols'), 'cols', 6, 40)
    rows = _coerce_int(payload.get('rows'), 'rows', 1, 10)
    message_duration_seconds = _coerce_int(
        payload.get('messageDurationSeconds', DEFAULT_MESSAGE_DURATION_SECONDS),
        'messageDurationSeconds',
        1,
        86400,
    )
    api_message_duration_seconds = _coerce_int(
        payload.get('apiMessageDurationSeconds'),
        'apiMessageDurationSeconds',
        1,
        86400,
    )

    return cols, rows, message_duration_seconds, api_message_duration_seconds


def load_display_settings(config_path: Path | None) -> DisplayConfig:
    if config_path is None or not config_path.exists():
        return default_display_config()

    with config_path.open('r', encoding='utf-8') as config_file:
        payload = json.load(config_file)

    cols, rows, message_duration_seconds, api_message_duration_seconds = normalize_runtime_settings_payload(payload)
    return DisplayConfig(
        cols=cols,
        rows=rows,
        default_messages=[],
        message_duration_seconds=message_duration_seconds,
        api_message_duration_seconds=api_message_duration_seconds,
    )


def save_display_settings(
    config_path: Path | None,
    config: DisplayConfig,
    *,
    plugin_common_settings: dict[str, Any],
) -> None:
    if config_path is None:
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open('w', encoding='utf-8') as config_file:
        payload = config.serialize_settings()
        payload['pluginCommonSettings'] = plugin_common_settings
        json.dump(payload, config_file, indent=2)
        config_file.write('\n')


def build_manual_screens_from_messages(
    messages: Any | None,
    *,
    cols: int,
    rows: int,
) -> list[dict[str, Any]]:
    if messages is None:
        messages = [message.copy() for message in DEFAULT_MESSAGES]

    normalized_messages = normalize_default_messages(messages, cols, rows)
    return [
        {
            'id': f'manual-{index + 1}',
            'type': 'manual',
            'name': '',
            'enabled': True,
            'lines': trim_message_lines(message),
        }
        for index, message in enumerate(normalized_messages)
    ]


def load_screens(
    screens_path: Path | None,
    *,
    config: DisplayConfig,
    plugins: dict[str, ScreenPlugin],
) -> list[dict[str, Any]]:
    if screens_path is not None and screens_path.exists():
        with screens_path.open('r', encoding='utf-8') as screens_file:
            payload = json.load(screens_file)
        return normalize_screens_payload(
            payload,
            config=config,
            plugins=plugins,
            existing_screens={},
        )

    return build_manual_screens_from_messages(
        [message.copy() for message in DEFAULT_MESSAGES],
        cols=config.cols,
        rows=config.rows,
    )


def serialize_screen_for_storage(screen: dict[str, Any]) -> dict[str, Any]:
    payload = {
        'id': screen['id'],
        'type': screen['type'],
        'name': screen.get('name', ''),
        'enabled': screen.get('enabled', True),
    }

    if screen['type'] == 'manual':
        payload['lines'] = trim_message_lines(screen['lines'])
        return payload

    payload.update(
        {
            'pluginId': screen['pluginId'],
            'refreshIntervalSeconds': screen['refreshIntervalSeconds'],
            'settings': screen['settings'],
            'design': screen['design'],
            'pluginState': screen.get('pluginState', {}),
            'cachedLines': trim_message_lines(screen.get('cachedLines', [])),
            'lastRefreshedAt': screen.get('lastRefreshedAt'),
            'lastError': screen.get('lastError'),
        }
    )
    return payload


def save_screens(
    screens_path: Path | None,
    screens: list[dict[str, Any]],
) -> None:
    if screens_path is None:
        return

    screens_path.parent.mkdir(parents=True, exist_ok=True)
    with screens_path.open('w', encoding='utf-8') as screens_file:
        json.dump({'screens': [serialize_screen_for_storage(screen) for screen in screens]}, screens_file, indent=2)
        screens_file.write('\n')


def collect_common_settings_schemas(plugins: dict[str, ScreenPlugin]) -> dict[str, tuple[PluginField, ...]]:
    schemas: dict[str, tuple[PluginField, ...]] = {}
    for plugin in plugins.values():
        namespace = plugin.manifest.common_settings_namespace
        if not namespace:
            continue
        schemas.setdefault(namespace, plugin.manifest.common_settings_schema)
    return schemas


def normalize_plugin_common_settings(payload: Any, *, plugins: dict[str, ScreenPlugin]) -> dict[str, Any]:
    schemas = collect_common_settings_schemas(plugins)
    normalized: dict[str, Any] = {}

    if payload is None:
        payload = {}

    if not isinstance(payload, dict):
        raise ValueError("'pluginCommonSettings' must be a JSON object.")

    for namespace, schema in schemas.items():
        normalized[namespace] = normalize_schema_values(
            payload.get(namespace),
            schema,
            section_name=f'pluginCommonSettings.{namespace}',
        )

    return normalized


def load_plugin_common_settings(
    common_settings_path: Path | None,
    *,
    plugins: dict[str, ScreenPlugin],
) -> dict[str, Any]:
    if common_settings_path is None or not common_settings_path.exists():
        return normalize_plugin_common_settings(None, plugins=plugins)

    with common_settings_path.open('r', encoding='utf-8') as config_file:
        payload = json.load(config_file)

    if isinstance(payload, dict):
        payload = payload.get('pluginCommonSettings')

    return normalize_plugin_common_settings(payload, plugins=plugins)


def save_plugin_common_settings(common_settings_path: Path | None, common_settings: dict[str, Any]) -> None:
    if common_settings_path is None:
        return

    display_config = load_display_settings(common_settings_path)
    save_display_settings(
        common_settings_path,
        display_config,
        plugin_common_settings=common_settings,
    )


def normalize_schema_values(
    values: Any,
    schema: tuple[PluginField, ...],
    *,
    section_name: str,
) -> dict[str, Any]:
    if values is None:
        values = {}

    if not isinstance(values, dict):
        raise ValueError(f"'{section_name}' must be a JSON object.")

    normalized: dict[str, Any] = {}
    for field in schema:
        raw_value = values.get(field.name, field.default)

        if field.field_type == 'text':
            if raw_value is None:
                raw_value = ''
            if not isinstance(raw_value, str):
                raise ValueError(f"'{section_name}.{field.name}' must be a string.")
            normalized_value = raw_value.strip()
            if field.required and not normalized_value:
                raise ValueError(f"'{section_name}.{field.name}' is required.")
            normalized[field.name] = normalized_value
            continue

        if field.field_type == 'select':
            if raw_value is None:
                raw_value = field.default
            if not isinstance(raw_value, str):
                raise ValueError(f"'{section_name}.{field.name}' must be a string.")
            valid_values = {option.value for option in field.options}
            if raw_value not in valid_values:
                raise ValueError(f"'{section_name}.{field.name}' must be one of the allowed options.")
            normalized[field.name] = raw_value
            continue

        if field.field_type == 'checkbox':
            normalized[field.name] = _coerce_bool(raw_value, f'{section_name}.{field.name}')
            continue

        if field.field_type == 'number':
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                raise ValueError(f"'{section_name}.{field.name}' must be numeric.")
            normalized[field.name] = raw_value
            continue

        raise ValueError(f"Unsupported schema field type '{field.field_type}'.")

    return normalized


def generate_screen_id() -> str:
    return secrets.token_hex(8)


def normalize_screens_payload(
    payload: Any,
    *,
    config: DisplayConfig,
    plugins: dict[str, ScreenPlugin],
    existing_screens: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_screens = payload.get('screens') if isinstance(payload, dict) else payload
    if not isinstance(raw_screens, list) or len(raw_screens) == 0:
        raise ValueError("'screens' must be a non-empty array.")

    normalized_screens: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw_screen in enumerate(raw_screens, start=1):
        if not isinstance(raw_screen, dict):
            raise ValueError(f'Screen {index} must be a JSON object.')

        screen_id = raw_screen.get('id') if isinstance(raw_screen.get('id'), str) else generate_screen_id()
        if screen_id in seen_ids:
            raise ValueError(f"Duplicate screen id '{screen_id}' is not allowed.")
        seen_ids.add(screen_id)

        screen_type = raw_screen.get('type')
        name = _coerce_optional_string(raw_screen.get('name'), f'screens[{index}].name')
        enabled = _coerce_bool(raw_screen.get('enabled', True), f'screens[{index}].enabled')

        if screen_type == 'manual':
            normalized_screens.append(
                {
                    'id': screen_id,
                    'type': 'manual',
                    'name': name,
                    'enabled': enabled,
                    'lines': normalize_message_lines(
                        raw_screen.get('lines'),
                        cols=config.cols,
                        rows=config.rows,
                        field_name=f'screens[{index}].lines',
                    ),
                }
            )
            continue

        if screen_type == 'plugin':
            plugin_id = raw_screen.get('pluginId')
            if not isinstance(plugin_id, str) or plugin_id not in plugins:
                raise ValueError(f"Screen {index} references an unknown plugin.")

            plugin = plugins[plugin_id]
            refresh_interval_seconds = _coerce_int(
                raw_screen.get('refreshIntervalSeconds', plugin.manifest.default_refresh_interval_seconds),
                f'screens[{index}].refreshIntervalSeconds',
                1,
                86400,
            )
            previous_screen = existing_screens.get(screen_id, {})
            previous_cached_lines = previous_screen.get('cachedLines', [])
            cached_lines = normalize_message_lines(
                previous_cached_lines,
                cols=config.cols,
                rows=config.rows,
                field_name=f'screens[{index}].cachedLines',
                allow_empty=True,
            )

            normalized_screens.append(
                {
                    'id': screen_id,
                    'type': 'plugin',
                    'name': name,
                    'enabled': enabled,
                    'pluginId': plugin_id,
                    'refreshIntervalSeconds': refresh_interval_seconds,
                    'settings': normalize_schema_values(
                        raw_screen.get('settings'),
                        plugin.manifest.settings_schema,
                        section_name=f'screens[{index}].settings',
                    ),
                    'design': normalize_schema_values(
                        raw_screen.get('design'),
                        plugin.manifest.design_schema,
                        section_name=f'screens[{index}].design',
                    ),
                    'pluginState': previous_screen.get('pluginState', {}),
                    'cachedLines': cached_lines,
                    'lastRefreshedAt': previous_screen.get('lastRefreshedAt'),
                    'lastError': previous_screen.get('lastError'),
                }
            )
            continue

        raise ValueError(f"Screen {index} must have type 'manual' or 'plugin'.")

    return normalized_screens


def reconcile_screens_for_config_change(
    screens: list[dict[str, Any]],
    *,
    cols: int,
    rows: int,
    plugins: dict[str, ScreenPlugin],
) -> list[dict[str, Any]]:
    reconciled: list[dict[str, Any]] = []

    for screen in screens:
        if screen['type'] == 'manual':
            reconciled.append(
                {
                    **screen,
                    'lines': normalize_message_lines(
                        screen['lines'],
                        cols=cols,
                        rows=rows,
                        field_name=f"screen '{screen['id']}'",
                    ),
                }
            )
            continue

        plugin = plugins[screen['pluginId']]
        reconciled.append(
            {
                **screen,
                'settings': normalize_schema_values(
                    screen.get('settings'),
                    plugin.manifest.settings_schema,
                    section_name=f"screen '{screen['id']}'.settings",
                ),
                'design': normalize_schema_values(
                    screen.get('design'),
                    plugin.manifest.design_schema,
                    section_name=f"screen '{screen['id']}'.design",
                ),
                'pluginState': {},
                'cachedLines': [],
                'lastRefreshedAt': None,
                'lastError': None,
            }
        )

    return reconciled


def resolve_screen_lines(
    screen: dict[str, Any],
    config: DisplayConfig,
    plugins: dict[str, ScreenPlugin],
) -> list[str]:
    if screen['type'] == 'manual':
        return pad_lines(screen['lines'], config.rows)

    plugin = plugins[screen['pluginId']]
    cached_lines = screen.get('cachedLines') or []
    if cached_lines:
        return center_lines(cached_lines, config.rows)

    placeholder_lines = plugin.placeholder_lines(
        settings=screen['settings'],
        design=screen['design'],
        context=PluginContext(cols=config.cols, rows=config.rows),
        error=screen.get('lastError'),
    )
    return center_lines(
        normalize_message_lines(
            placeholder_lines,
            cols=config.cols,
            rows=config.rows,
            field_name=f"screen '{screen['id']}' placeholder",
        ),
        config.rows,
    )


def resolve_default_messages(
    screens: list[dict[str, Any]],
    config: DisplayConfig,
    plugins: dict[str, ScreenPlugin],
) -> list[list[str]]:
    messages = [
        resolve_screen_lines(screen, config, plugins)
        for screen in screens
        if screen.get('enabled', True)
    ]
    return messages or normalize_default_messages([['NO SCREENS']], config.cols, config.rows)


def sync_display_messages(app: web.Application) -> None:
    config = app[DISPLAY_CONFIG_KEY]
    config.default_messages = resolve_default_messages(
        app[SCREEN_STATE_KEY].screens,
        config,
        app[PLUGINS_KEY],
    )


def apply_runtime_display_config(config: DisplayConfig) -> dict[str, Any]:
    return config.serialize()


def build_admin_config_response(config: DisplayConfig) -> dict[str, Any]:
    return config.serialize_settings()


def serialize_screen_for_admin(
    screen: dict[str, Any],
    config: DisplayConfig,
    plugins: dict[str, ScreenPlugin],
) -> dict[str, Any]:
    payload = {
        'id': screen['id'],
        'type': screen['type'],
        'name': screen.get('name', ''),
        'enabled': screen.get('enabled', True),
        'previewLines': resolve_screen_lines(screen, config, plugins),
    }

    if screen['type'] == 'manual':
        payload['lines'] = screen['lines']
        return payload

    plugin = plugins[screen['pluginId']]
    payload.update(
        {
            'pluginId': screen['pluginId'],
            'pluginName': plugin.manifest.name,
            'refreshIntervalSeconds': screen['refreshIntervalSeconds'],
            'settings': screen['settings'],
            'design': screen['design'],
            'pluginState': screen.get('pluginState', {}),
            'lastRefreshedAt': screen.get('lastRefreshedAt'),
            'lastError': screen.get('lastError'),
        }
    )
    return payload


def build_admin_screens_response(app: web.Application) -> dict[str, Any]:
    config = app[DISPLAY_CONFIG_KEY]
    plugins = app[PLUGINS_KEY]
    return {
        'pluginCommonSettings': app[SCREEN_STATE_KEY].common_settings,
        'screens': [
            serialize_screen_for_admin(screen, config, plugins)
            for screen in app[SCREEN_STATE_KEY].screens
        ],
        'plugins': [plugin.manifest.serialize() for plugin in plugins.values()],
    }


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
    sync_display_messages(app)
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


def normalize_payload(payload: Any, config: DisplayConfig) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')

    has_message = 'message' in payload
    has_lines = 'lines' in payload

    if has_message == has_lines:
        raise ValueError("Request body must include exactly one of 'message' or 'lines'.")

    if has_message:
        return normalize_message(payload['message'], config.cols, config.rows)

    return pad_lines(
        normalize_message_lines(
            payload['lines'],
            cols=config.cols,
            rows=config.rows,
            field_name='lines',
        ),
        config.rows,
    )


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


def get_screen_by_id(app: web.Application, screen_id: str) -> dict[str, Any] | None:
    for screen in app[SCREEN_STATE_KEY].screens:
        if screen['id'] == screen_id:
            return screen
    return None


async def refresh_plugin_screen(
    app: web.Application,
    screen_id: str,
    *,
    broadcast: bool,
) -> dict[str, Any] | None:
    screen = get_screen_by_id(app, screen_id)
    if screen is None or screen['type'] != 'plugin' or not screen.get('enabled', True):
        return screen

    plugin = app[PLUGINS_KEY][screen['pluginId']]
    config = app[DISPLAY_CONFIG_KEY]
    previous_last_error = screen.get('lastError')
    previous_cached_lines = screen.get('cachedLines', []).copy()

    try:
        result = await plugin.refresh(
            settings=screen['settings'],
            design=screen['design'],
            context=PluginContext(cols=config.cols, rows=config.rows),
            http_session=app[PLUGIN_HTTP_SESSION_KEY],
            previous_state=screen.get('pluginState'),
            common_settings=app[SCREEN_STATE_KEY].common_settings.get(
                plugin.manifest.common_settings_namespace,
                {},
            ),
        )
        screen['cachedLines'] = normalize_message_lines(
            result.lines,
            cols=config.cols,
            rows=config.rows,
            field_name=f"plugin screen '{screen_id}'",
        )
        screen['pluginState'] = result.meta.copy()
        screen['lastRefreshedAt'] = _utc_now()
        screen['lastError'] = None
    except Exception as exc:
        screen['pluginState'] = screen.get('pluginState', {})
        screen['lastError'] = str(exc)

    save_screens(app[SCREENS_PATH_KEY], app[SCREEN_STATE_KEY].screens)
    sync_display_messages(app)

    if broadcast and (
        screen.get('lastError') != previous_last_error or screen.get('cachedLines', []) != previous_cached_lines
    ):
        await broadcast_display_config(app)

    return screen


async def refresh_all_plugin_screens(app: web.Application, *, broadcast: bool) -> None:
    for screen in app[SCREEN_STATE_KEY].screens:
        if screen['type'] != 'plugin' or not screen.get('enabled', True):
            continue
        await refresh_plugin_screen(app, screen['id'], broadcast=False)

    sync_display_messages(app)
    if broadcast:
        await broadcast_display_config(app)


def cancel_plugin_refresh_tasks(app: web.Application) -> None:
    for task in app[SCREEN_STATE_KEY].refresh_tasks.values():
        task.cancel()
    app[SCREEN_STATE_KEY].refresh_tasks.clear()


def restart_plugin_refresh_tasks(app: web.Application) -> None:
    cancel_plugin_refresh_tasks(app)

    for screen in app[SCREEN_STATE_KEY].screens:
        if screen['type'] != 'plugin' or not screen.get('enabled', True):
            continue
        screen_id = screen['id']
        app[SCREEN_STATE_KEY].refresh_tasks[screen_id] = asyncio.create_task(plugin_refresh_loop(app, screen_id))


async def plugin_refresh_loop(app: web.Application, screen_id: str) -> None:
    try:
        while True:
            screen = get_screen_by_id(app, screen_id)
            if screen is None or screen['type'] != 'plugin' or not screen.get('enabled', True):
                return
            await asyncio.sleep(screen['refreshIntervalSeconds'])
            await refresh_plugin_screen(app, screen_id, broadcast=True)
    except asyncio.CancelledError:
        raise


async def index_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'index.html')


async def admin_handler(_: web.Request) -> web.Response:
    return web.FileResponse(PROJECT_ROOT / 'admin.html')


async def get_display_config(request: web.Request) -> web.Response:
    sync_display_messages(request.app)
    return web.json_response(apply_runtime_display_config(request.app[DISPLAY_CONFIG_KEY]))


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
    sync_display_messages(request.app)
    return web.json_response(build_admin_config_response(request.app[DISPLAY_CONFIG_KEY]))


async def admin_config_put(request: web.Request) -> web.Response:
    require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    try:
        cols, rows, message_duration_seconds, api_message_duration_seconds = normalize_runtime_settings_payload(payload)
        reconciled_screens = reconcile_screens_for_config_change(
            request.app[SCREEN_STATE_KEY].screens,
            cols=cols,
            rows=rows,
            plugins=request.app[PLUGINS_KEY],
        )
    except ValueError as exc:
        return _json_error(str(exc))

    current_config = request.app[DISPLAY_CONFIG_KEY]
    current_config.cols = cols
    current_config.rows = rows
    current_config.message_duration_seconds = message_duration_seconds
    current_config.api_message_duration_seconds = api_message_duration_seconds
    request.app[SCREEN_STATE_KEY].screens = reconciled_screens

    save_display_settings(
        request.app[CONFIG_PATH_KEY],
        current_config,
        plugin_common_settings=request.app[SCREEN_STATE_KEY].common_settings,
    )
    save_screens(request.app[SCREENS_PATH_KEY], request.app[SCREEN_STATE_KEY].screens)

    await refresh_all_plugin_screens(request.app, broadcast=False)
    restart_plugin_refresh_tasks(request.app)
    await clear_override(request.app)
    await broadcast_display_config(request.app)

    return web.json_response(build_admin_config_response(current_config))


async def admin_screens_get(request: web.Request) -> web.Response:
    require_admin(request)
    return web.json_response(build_admin_screens_response(request.app))


async def admin_screens_put(request: web.Request) -> web.Response:
    require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return _json_error('Request body must be valid JSON.')

    existing_screens = {
        screen['id']: screen
        for screen in request.app[SCREEN_STATE_KEY].screens
    }

    try:
        normalized_screens = normalize_screens_payload(
            payload,
            config=request.app[DISPLAY_CONFIG_KEY],
            plugins=request.app[PLUGINS_KEY],
            existing_screens=existing_screens,
        )
        common_settings = normalize_plugin_common_settings(
            payload.get('pluginCommonSettings'),
            plugins=request.app[PLUGINS_KEY],
        )
    except ValueError as exc:
        return _json_error(str(exc))

    request.app[SCREEN_STATE_KEY].screens = normalized_screens
    request.app[SCREEN_STATE_KEY].common_settings = common_settings
    save_screens(request.app[SCREENS_PATH_KEY], normalized_screens)
    save_plugin_common_settings(request.app[CONFIG_PATH_KEY], common_settings)

    await refresh_all_plugin_screens(request.app, broadcast=False)
    restart_plugin_refresh_tasks(request.app)
    await broadcast_display_config(request.app)

    return web.json_response(build_admin_screens_response(request.app))


async def admin_screen_refresh(request: web.Request) -> web.Response:
    require_admin(request)

    screen_id = request.match_info['screen_id']
    screen = get_screen_by_id(request.app, screen_id)
    if screen is None:
        return _json_error('Screen not found.', status=404)

    if screen['type'] != 'plugin':
        return _json_error('Only plugin screens support manual refresh.', status=400)

    await refresh_plugin_screen(request.app, screen_id, broadcast=True)

    refreshed_screen = get_screen_by_id(request.app, screen_id)
    return web.json_response(
        {
            'screen': serialize_screen_for_admin(
                refreshed_screen,
                request.app[DISPLAY_CONFIG_KEY],
                request.app[PLUGINS_KEY],
            )
        }
    )


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    request.app[WS_CLIENTS_KEY].add(ws)
    sync_display_messages(request.app)
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


@web.middleware
async def no_cache_static_assets(request: web.Request, handler) -> web.StreamResponse:
    response = await handler(request)
    if request.method == 'GET' and (
        request.path in {'/', '/index.html', '/admin', '/admin/', '/screenshot.png', '/favicon.ico'}
        or request.path.startswith('/js/')
        or request.path.startswith('/css/')
    ):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


async def initialize_plugin_runtime(app: web.Application) -> None:
    app[PLUGIN_HTTP_SESSION_KEY] = ClientSession(timeout=ClientTimeout(total=20))
    await refresh_all_plugin_screens(app, broadcast=False)
    restart_plugin_refresh_tasks(app)


async def cleanup_background_tasks(app: web.Application) -> None:
    override_task = app[OVERRIDE_TASK_KEY].task
    cancel_override_task(app)
    if override_task is not None:
        with suppress(asyncio.CancelledError):
            await override_task


async def cleanup_plugin_runtime(app: web.Application) -> None:
    cancel_plugin_refresh_tasks(app)
    for task in list(app[SCREEN_STATE_KEY].refresh_tasks.values()):
        with suppress(asyncio.CancelledError):
            await task

    session = app.get(PLUGIN_HTTP_SESSION_KEY)
    if session is not None:
        await session.close()


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


def create_app(
    *,
    admin_password: str | None = None,
    config_path: Path | None = CONFIG_PATH,
    screens_path: Path | None = SCREENS_PATH,
    plugins: dict[str, ScreenPlugin] | None = None,
) -> web.Application:
    plugin_registry = plugins or load_plugins()
    display_config = load_display_settings(config_path)
    loaded_screens = load_screens(
        screens_path,
        config=display_config,
        plugins=plugin_registry,
    )
    loaded_common_settings = load_plugin_common_settings(
        config_path,
        plugins=plugin_registry,
    )
    screen_state = ScreenState(
        screens=loaded_screens,
        common_settings=loaded_common_settings,
    )
    display_config.default_messages = resolve_default_messages(
        screen_state.screens,
        display_config,
        plugin_registry,
    )
    message_state = MessageState(lines=[''] * display_config.rows)
    resolved_admin_password, generated_admin_password = resolve_admin_password(admin_password)

    app = web.Application(middlewares=[no_cache_static_assets])
    app[DISPLAY_CONFIG_KEY] = display_config
    app[MESSAGE_STATE_KEY] = message_state
    app[SCREEN_STATE_KEY] = screen_state
    app[WS_CLIENTS_KEY] = set()
    app[ADMIN_PASSWORD_KEY] = resolved_admin_password
    app[GENERATED_ADMIN_PASSWORD_KEY] = generated_admin_password
    app[SESSION_TOKENS_KEY] = set()
    app[CONFIG_PATH_KEY] = config_path
    app[SCREENS_PATH_KEY] = screens_path
    app[PLUGINS_KEY] = plugin_registry
    app[OVERRIDE_TASK_KEY] = OverrideTaskState()

    app.on_startup.append(announce_admin_password)
    app.on_startup.append(initialize_plugin_runtime)
    app.on_shutdown.append(close_websockets)
    app.on_cleanup.append(cleanup_background_tasks)
    app.on_cleanup.append(cleanup_plugin_runtime)

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
    app.router.add_get('/api/admin/screens', admin_screens_get)
    app.router.add_put('/api/admin/screens', admin_screens_put)
    app.router.add_post('/api/admin/screens/{screen_id}/refresh', admin_screen_refresh)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_static('/css', PROJECT_ROOT / 'css')
    app.router.add_static('/js', PROJECT_ROOT / 'js')
    app.router.add_get('/screenshot.png', screenshot_handler)
    app.router.add_get('/favicon.ico', favicon_handler)

    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    web.run_app(create_app(), host='0.0.0.0', port=port)
