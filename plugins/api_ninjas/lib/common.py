from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...base import PluginField

API_NINJAS_QUOTES_URL = 'https://api.api-ninjas.com/v1/quotes'
API_NINJAS_CRYPTO_PRICE_URL = 'https://api.api-ninjas.com/v1/cryptoprice'
API_NINJAS_API_KEY_ENV = 'API_NINJAS_API_KEY'
API_NINJAS_COMMON_SETTINGS_NAMESPACE = 'quotes'
API_NINJAS_COMMON_SETTINGS_SCHEMA = (
    PluginField(
        name='apiNinjasApiKey',
        label='API Ninjas API Key',
        field_type='text',
        default='',
        placeholder='Required for API Ninjas plugins',
        help_text='Shared by all API Ninjas plugins.',
    ),
)


def current_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def compact_author(value: Any, max_length: int) -> str:
    author = str(value or 'UNKNOWN').strip().upper()
    return author[:max_length]


def fit(value: Any, cols: int) -> str:
    return str(value or '')[:cols]


def build_headers(api_key: str) -> dict[str, str]:
    return {
        'Accept': 'application/json',
        'X-Api-Key': api_key,
    }


def resolve_api_key(common_settings: dict[str, Any] | None, env) -> str:
    api_key = (common_settings or {}).get('apiNinjasApiKey') or env.get(API_NINJAS_API_KEY_ENV)
    if not api_key:
        raise ValueError(f'{API_NINJAS_API_KEY_ENV} is not configured on the server.')
    return str(api_key)


def wrap_text(value: Any, cols: int, max_lines: int) -> list[str]:
    if max_lines <= 0 or cols <= 0:
        return []

    collapsed = ' '.join(str(value or '').strip().upper().split())
    if not collapsed:
        return []

    words = collapsed.split(' ')
    lines: list[str] = []
    current = ''

    for word in words:
        while len(word) > cols:
            if current:
                lines.append(current)
                if len(lines) >= max_lines:
                    return lines[:max_lines]
                current = ''
            lines.append(word[:cols])
            if len(lines) >= max_lines:
                return lines[:max_lines]
            word = word[cols:]

        candidate = word if not current else f'{current} {word}'
        if len(candidate) <= cols:
            current = candidate
            continue

        lines.append(current)
        if len(lines) >= max_lines:
            return lines[:max_lines]
        current = word

    if current and len(lines) < max_lines:
        lines.append(current)

    return lines[:max_lines]


def build_quote_lines(
    *,
    quote_text: Any,
    author: Any,
    cols: int,
    rows: int,
    has_title: bool,
) -> list[str]:
    available_rows = max(0, rows - (2 if has_title else 0))
    if available_rows <= 0:
        return []

    if available_rows == 1:
        return wrap_text(quote_text, cols, 1)

    author_line = fit(f"- {compact_author(author, max(0, cols - 2))}", cols)
    quote_lines = wrap_text(quote_text, cols, available_rows - 1)

    if not quote_lines:
        return [author_line]

    return [*quote_lines, author_line][:available_rows]
