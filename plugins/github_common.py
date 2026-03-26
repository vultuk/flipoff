from __future__ import annotations

from typing import Any

DEFAULT_GITHUB_REPOSITORY = 'magnum6actual/flipoff'
GITHUB_API_BASE_URL = 'https://api.github.com'


def normalize_repository(value: Any) -> tuple[str, str]:
    repository = str(value or DEFAULT_GITHUB_REPOSITORY).strip()
    if not repository:
        repository = DEFAULT_GITHUB_REPOSITORY

    parts = [part.strip() for part in repository.split('/', 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Repository must use the format 'owner/name'.")

    return parts[0], parts[1]


def compact_repository(owner: str, repo: str) -> str:
    return f'{owner}/{repo}'


async def fetch_repository(owner: str, repo: str, http_session) -> dict[str, Any]:
    async with http_session.get(
        f'{GITHUB_API_BASE_URL}/repos/{owner}/{repo}',
        headers={'Accept': 'application/vnd.github+json'},
    ) as response:
        payload = await response.json(content_type=None)
        if not response.ok:
            error = payload.get('message') if isinstance(payload, dict) else None
            raise ValueError(error or 'GitHub repository request failed.')
    return payload


async def count_open_pull_requests(owner: str, repo: str, http_session) -> int:
    async with http_session.get(
        f'{GITHUB_API_BASE_URL}/repos/{owner}/{repo}/pulls',
        params={'state': 'open', 'per_page': 1, 'page': 1},
        headers={'Accept': 'application/vnd.github+json'},
    ) as response:
        payload = await response.json(content_type=None)
        if not response.ok:
            error = payload.get('message') if isinstance(payload, dict) else None
            raise ValueError(error or 'GitHub pull request request failed.')

        if not isinstance(payload, list):
            raise ValueError('GitHub pull request response was not a list.')

        link_header = response.headers.get('Link', '')
        if 'rel="last"' in link_header:
            last_page = extract_last_page(link_header)
            if last_page is not None:
                return last_page

        return len(payload)


def extract_last_page(link_header: str) -> int | None:
    for segment in link_header.split(','):
        if 'rel="last"' not in segment:
            continue

        marker = 'page='
        page_index = segment.find(marker)
        if page_index == -1:
            continue

        page_fragment = segment[page_index + len(marker):]
        digits = []
        for char in page_fragment:
            if char.isdigit():
                digits.append(char)
                continue
            break

        if digits:
            return int(''.join(digits))

    return None
