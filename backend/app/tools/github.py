"""GitHub via a fine-grained Personal Access Token (stored encrypted). Read-only tools."""
from __future__ import annotations

import httpx

from app.services.integrations_store import get_secret
from app.tools.registry import ToolContext, ToolError, tool

API = "https://api.github.com"


async def _get(ctx: ToolContext, path: str, params: dict | None = None, require_token: bool = False):
    s = await get_secret(ctx.db, ctx.user.id, "github")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if s and s.get("token"):
        headers["Authorization"] = f"Bearer {s['token']}"
    elif require_token:
        raise ToolError("GitHub isn't connected. Ask the user to add a GitHub token in Integrations.")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(API + path, params=params, headers=headers)
    if r.status_code == 404:
        raise ToolError("Not found on GitHub (or token lacks access).")
    if r.status_code >= 400:
        raise ToolError(f"GitHub error {r.status_code}: {r.text[:200]}")
    return r.json()


@tool("github_list_repos", "List the user's GitHub repositories (most recently updated first). Uses their token, or a public username.",
      {"username": {"type": "string", "description": "Optional public username if no token"}}, category="github")
async def github_list_repos(ctx: ToolContext, a: dict):
    s = await get_secret(ctx.db, ctx.user.id, "github")
    if a.get("username") and not (s and s.get("token")):
        data = await _get(ctx, f"/users/{a['username']}/repos", {"sort": "updated", "per_page": 30})
    else:
        data = await _get(ctx, "/user/repos", {"sort": "updated", "per_page": 30, "affiliation": "owner,collaborator"}, require_token=True)
    return [{"name": r["full_name"], "description": r.get("description"), "language": r.get("language"), "stars": r.get("stargazers_count"),
             "updated": r.get("pushed_at"), "url": r.get("html_url"), "private": r.get("private")} for r in data]


@tool("github_repo_activity", "Recent commits, open issues and PRs for a repository (owner/name).",
      {"repo": {"type": "string", "description": "owner/name"}}, ["repo"], category="github")
async def github_repo_activity(ctx: ToolContext, a: dict):
    repo = a["repo"].strip().strip("/")
    commits = await _get(ctx, f"/repos/{repo}/commits", {"per_page": 10})
    issues = await _get(ctx, f"/repos/{repo}/issues", {"state": "open", "per_page": 10})
    return {"recent_commits": [{"sha": c["sha"][:7], "message": c["commit"]["message"].split("\n")[0], "date": c["commit"]["author"]["date"]} for c in commits],
            "open_issues_and_prs": [{"number": i["number"], "title": i["title"], "is_pr": "pull_request" in i} for i in issues]}
