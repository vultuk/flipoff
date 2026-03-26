from __future__ import annotations

from .base import (
    PluginContext,
    PluginField,
    PluginManifest,
    PluginRefreshResult,
    ScreenPlugin,
)
from .github_common import (
    DEFAULT_GITHUB_REPOSITORY,
    compact_repository,
    fetch_repository,
    normalize_repository,
)


class GitHubRepoStatsPlugin(ScreenPlugin):
    manifest = PluginManifest(
        plugin_id='github_repo_stats',
        name='GitHub Stars, Watches, Forks',
        description='Show stars, watches, and forks for a public GitHub repository.',
        default_refresh_interval_seconds=300,
        settings_schema=(
            PluginField(
                name='repository',
                label='Repository',
                field_type='text',
                default=DEFAULT_GITHUB_REPOSITORY,
                placeholder='owner/repo',
                help_text="Uses the GitHub REST API for public repositories. Leave blank for 'magnum6actual/flipoff'.",
            ),
        ),
        design_schema=(
            PluginField(
                name='title',
                label='Title Override',
                field_type='text',
                default='',
                placeholder='GITHUB STATS',
            ),
        ),
    )

    async def refresh(
        self,
        *,
        settings,
        design,
        context: PluginContext,
        http_session,
    ) -> PluginRefreshResult:
        owner, repo = normalize_repository(settings.get('repository'))
        payload = await fetch_repository(owner, repo, http_session)

        title = str(design.get('title') or 'GITHUB STATS').strip().upper()
        repo_label = compact_repository(owner, repo).upper()

        lines = [
            self._fit(title, context.cols),
            self._fit(repo_label, context.cols),
            self._fit(f"STAR {self._number(payload.get('stargazers_count'))}", context.cols),
            self._fit(f"WATCH {self._number(payload.get('subscribers_count', payload.get('watchers_count')))}", context.cols),
            self._fit(f"FORK {self._number(payload.get('forks_count'))}", context.cols),
        ]

        return PluginRefreshResult(lines=lines[: context.rows])

    def placeholder_lines(self, *, settings, design, context: PluginContext, error=None):
        owner, repo = normalize_repository(settings.get('repository'))
        title = str(design.get('title') or 'GITHUB STATS').strip().upper()
        detail = (error or compact_repository(owner, repo)).upper()
        return [
            self._fit(title, context.cols),
            self._fit(detail, context.cols),
            self._fit('STAR --', context.cols),
            self._fit('WATCH --', context.cols),
            self._fit('FORK --', context.cols),
        ][: context.rows]

    def _number(self, value) -> str:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return '--'

    def _fit(self, value: str, cols: int) -> str:
        return value[:cols]


PLUGIN = GitHubRepoStatsPlugin()
