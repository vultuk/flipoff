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
    count_open_pull_requests,
    fetch_repository,
    normalize_repository,
)


class GitHubOpenWorkPlugin(ScreenPlugin):
    manifest = PluginManifest(
        plugin_id='github_open_work',
        name='GitHub Open Issues and PRs',
        description='Show the current number of open issues and open pull requests for a public GitHub repository.',
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
                placeholder='OPEN WORK',
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
        repository_payload = await fetch_repository(owner, repo, http_session)
        open_prs = await count_open_pull_requests(owner, repo, http_session)
        open_issues_total = repository_payload.get('open_issues_count')
        try:
            open_issues = max(0, int(open_issues_total) - open_prs)
        except (TypeError, ValueError):
            open_issues = 0

        title = str(design.get('title') or 'OPEN WORK').strip().upper()
        repo_label = compact_repository(owner, repo).upper()

        lines = [
            self._fit(title, context.cols),
            self._fit(repo_label, context.cols),
            self._fit(f'ISSUE {open_issues}', context.cols),
            self._fit(f'PR {open_prs}', context.cols),
        ]

        return PluginRefreshResult(lines=lines[: context.rows])

    def placeholder_lines(self, *, settings, design, context: PluginContext, error=None):
        owner, repo = normalize_repository(settings.get('repository'))
        title = str(design.get('title') or 'OPEN WORK').strip().upper()
        detail = (error or compact_repository(owner, repo)).upper()
        return [
            self._fit(title, context.cols),
            self._fit(detail, context.cols),
            self._fit('ISSUE --', context.cols),
            self._fit('PR --', context.cols),
        ][: context.rows]

    def _fit(self, value: str, cols: int) -> str:
        return value[:cols]


PLUGIN = GitHubOpenWorkPlugin()
