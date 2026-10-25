"""Synthetic and live GitHub read-only sources, limited to an explicitly configured scope."""

import json
import re
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings

# Mutable GitHub metadata (repo list, org pulse, PR details) is refetched after this interval.
MUTABLE_TTL_SECONDS = 300


def _ttl_bucket() -> int:
    return int(time.time() // MUTABLE_TTL_SECONDS)


class SourcePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    revision: str
    captured_at: str
    text: str
    offset: int
    next_offset: int | None
    synthetic: bool = True


SOURCES = {
    "github:example/widget/README.md": (
        "fixture-commit-1",
        "Widget example: requests time out after 30 seconds. "
        "The retry policy is documented in docs/retries.md. This is synthetic evidence.",
    ),
    "github:example/widget/docs/retries.md": (
        "fixture-commit-1",
        "Retry only idempotent reads. An ambiguous write must be investigated.",
    ),
    "notion:example/operations": (
        "fixture-revision-1",
        "Synthetic operations note: a timeout is not proof of no effect.",
    ),
}

BINARY_SUFFIXES = (".png", ".jpg", ".svg", ".lock", ".ico", ".woff", ".woff2", ".pdf", ".zip")
DENIED = "Source is not in the Creator allowlist; use list_sources"


class GitHubScope(BaseModel):
    """Fail-closed allowlist. Without org and repo prefix, no live GitHub repo is readable."""

    model_config = ConfigDict(frozen=True)
    org: str = ""
    name_prefix: str = ""
    context_repo: str = ""
    deployments_repo: str = ""
    local_root: Path | None = None

    @property
    def repos_enabled(self) -> bool:
        return bool(self.org and self.name_prefix)

    @property
    def context_enabled(self) -> bool:
        return bool(self.org and self.context_repo)

    @property
    def deployments_enabled(self) -> bool:
        return bool(self.org and self.deployments_repo)

    def is_canonical(self, name: str) -> bool:
        return (
            self.repos_enabled
            and bool(re.fullmatch(rf"{re.escape(self.name_prefix)}[a-z0-9-]+", name))
            and not name.endswith(("-hotfix", "-main"))
            and "-release-" not in name
        )


@lru_cache(maxsize=1)
def _scope() -> GitHubScope:
    settings = Settings()
    local = settings.local_repo_root.strip()
    return GitHubScope(
        org=settings.github_org.strip(),
        name_prefix=settings.github_repo_prefix.strip(),
        context_repo=settings.github_context_repo.strip(),
        deployments_repo=settings.github_deployments_repo.strip(),
        local_root=Path(local) if local else None,
    )


class SourceRead(BaseModel):
    source_id: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=1500, ge=1, le=4000)


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 15) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise ValueError(DENIED)
    return proc.stdout


def _local_dir(repo_name: str) -> Path | None:
    root = _scope().local_root
    return root / repo_name if root else None


def _has_local_commit(repo_dir: Path | None, sha: str) -> bool:
    if repo_dir is None or not (repo_dir / ".git").exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        check=False,
        timeout=3,
    )
    return proc.returncode == 0


def _discover_github_repos() -> tuple[str, ...]:
    return _discover_cached(_ttl_bucket())


@lru_cache(maxsize=4)
def _discover_cached(bucket: int) -> tuple[str, ...]:
    scope = _scope()
    if not scope.repos_enabled:
        return ()
    names: set[str] = set()
    proc = subprocess.run(
        [
            "gh",
            "search",
            "repos",
            f"{scope.name_prefix} in:name",
            "--owner",
            scope.org,
            "--archived=false",
            "--limit",
            "100",
            "--json",
            "name",
            "--jq",
            ".[].name",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if proc.returncode == 0:
        names.update(
            line.strip() for line in proc.stdout.splitlines() if scope.is_canonical(line.strip())
        )
    if not names and scope.local_root and scope.local_root.is_dir():
        names.update(
            p.name
            for p in scope.local_root.iterdir()
            if p.is_dir() and (p / ".git").exists() and scope.is_canonical(p.name)
        )
    return tuple(sorted(names))


def _resolve_repo_head(repo_name: str, repo_dir: Path | None) -> str:
    proc = subprocess.run(
        ["gh", "api", f"repos/{_scope().org}/{repo_name}/commits/HEAD", "--jq", ".sha[0:12]"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    if repo_dir is not None:
        for ref in ("origin/main", "HEAD"):
            local = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--short=12", ref],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if local.returncode == 0 and local.stdout.strip():
                return local.stdout.strip()
    raise ValueError(DENIED)


@lru_cache(maxsize=256)
def _repo_tree(repo_name: str, revision: str) -> tuple[str, ...]:
    repo_dir = _local_dir(repo_name)
    if _has_local_commit(repo_dir, revision):
        raw = _run(["git", "ls-tree", "-r", "--name-only", revision], cwd=repo_dir)
        return tuple(line for line in raw.splitlines() if line)
    raw = _run(
        [
            "gh",
            "api",
            f"repos/{_scope().org}/{repo_name}/git/trees/{revision}?recursive=1",
            "--jq",
            '.tree[] | select(.type=="blob") | .path',
        ]
    )
    return tuple(line for line in raw.splitlines() if line)


def _curated_files(repo_name: str, revision: str) -> list[str]:
    return [
        f
        for f in _repo_tree(repo_name, revision)
        if not any(part.startswith(".") for part in f.split("/"))
        and not f.endswith(BINARY_SUFFIXES)
    ]


@lru_cache(maxsize=256)
def _repo_index(prefix: str, repo_name: str, revision: str) -> str:
    scope = _scope()
    repo_dir = _local_dir(repo_name)
    if _has_local_commit(repo_dir, revision):
        raw_commits = _run(["git", "log", revision, "-n", "6", "--oneline"], cwd=repo_dir)
    else:
        raw_commits = _run(
            [
                "gh",
                "api",
                f"repos/{scope.org}/{repo_name}/commits?sha={revision}&per_page=6",
                "--jq",
                r'.[] | "\(.sha[0:12]) \(.commit.message | split("\n")[0])"',
            ]
        )
    commits = "\n".join(line[:95] for line in raw_commits.strip().splitlines()[:6])
    curated = _curated_files(repo_name, revision)
    top_counts: Counter[str] = Counter()
    root_files: list[str] = []
    for f in curated:
        if "/" in f:
            top_counts[f.split("/", 1)[0] + "/"] += 1
        else:
            root_files.append(f"{prefix}:{f}")
    folders = [
        f"- {prefix}:TREE:{folder} ({count} files)" for folder, count in top_counts.most_common(15)
    ]
    authority = (
        "Shared orientation and strategic context; verify current behavior in the owning "
        "service repo."
        if prefix == "context"
        else (
            "Desired environment configuration and configured SHAs; this is not proof of "
            "what is live."
            if prefix == "deployments"
            else "Code behavior and contracts at this main revision; main is not deployment proof."
        )
    )
    lines = [
        f"# {scope.org}/{repo_name}@{revision} ({len(curated)} readable files)",
        f"# Authority: {authority}",
        f"# Queries: {prefix}:TREE:<dir> | {prefix}:SEARCH:<term> | {prefix}:<filepath>",
        "",
        "## Recent commits on main",
        commits,
        "",
        "## Root files",
        *(root_files[:12] or ["(none)"]),
        "",
        "## Directories (use TREE:<dir> to list files)",
        *(folders or ["(none)"]),
    ]
    return "\n".join(lines)


def _repo_tree_query(prefix: str, repo_name: str, revision: str, sub: str) -> str:
    curated = _curated_files(repo_name, revision)
    norm = sub.strip("/")
    matched = [f for f in curated if norm.lower() in f.lower()]
    subdirs: Counter[str] = Counter()
    direct: list[str] = []
    prefix_slash = norm + "/"
    for f in matched:
        if f.lower().startswith(prefix_slash.lower()):
            rem = f[len(prefix_slash) :]
            if "/" in rem:
                subdirs[prefix_slash + rem.split("/", 1)[0] + "/"] += 1
            else:
                direct.append(f)
        else:
            direct.append(f)
    lines = [f"# {prefix}:TREE:{sub} ({len(matched)} total files)"]
    if subdirs:
        lines.append("## Subdirectories (drill down with TREE:<subdir>)")
        for sd, cnt in subdirs.most_common(15):
            lines.append(f"- {prefix}:TREE:{sd} ({cnt} files)")
    shown = direct[:35] if subdirs else matched[:45]
    if shown:
        lines.append("## Files")
        lines.extend(f"{prefix}:{f}" for f in shown)
    return "\n".join(lines)


def _repo_prs(repo_name: str) -> str:
    org = _scope().org
    raw = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            f"{org}/{repo_name}",
            "--state",
            "all",
            "--limit",
            "15",
            "--json",
            "number,title,state,mergedAt,updatedAt,author",
        ]
    )
    items = json.loads(raw)
    lines = [f"# Pull Requests in {org}/{repo_name} (details: repo:{repo_name}:PR:<number>)"]
    for pr in items:
        author = (pr.get("author") or {}).get("login", "unknown")
        stamp = (pr.get("mergedAt") or pr.get("updatedAt") or "")[:10]
        lines.append(
            f"PR #{pr['number']} [{pr['state']}] ({stamp} by {author}): {pr['title'][:85]}"
        )
    return "\n".join(lines)


# The bucket only keys the cache, so PR state (open or merged) is refetched each interval.
@lru_cache(maxsize=256)
def _repo_pr_detail(repo_name: str, number: int, bucket: int) -> tuple[str, str]:
    raw = _run(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            f"{_scope().org}/{repo_name}",
            "--json",
            "number,title,state,body,author,headRefOid,mergedAt,files,comments",
        ]
    )
    pr = json.loads(raw)
    rev = (pr.get("headRefOid") or "pr")[:12]
    files = [
        f"- {f['path']} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
        for f in pr.get("files", [])[:30]
    ]
    comments = [
        f"- {(c.get('author') or {}).get('login', 'user')}: {c.get('body', '')[:300]}"
        for c in pr.get("comments", [])[:10]
    ]
    text = "\n".join(
        [
            f"# PR #{pr['number']}: {pr['title']} [{pr['state']}]",
            f"Author: {(pr.get('author') or {}).get('login', 'unknown')} | Head: {rev}",
            "",
            (pr.get("body") or "(no description)")[:1500],
            "",
            "## Files changed",
            *files,
            *(["", "## Comments", *comments] if comments else []),
        ]
    )
    return rev, text


@lru_cache(maxsize=512)
def _repo_blob(repo_name: str, revision: str, rel_path: str) -> str:
    if rel_path not in set(_repo_tree(repo_name, revision)):
        raise ValueError(DENIED)
    repo_dir = _local_dir(repo_name)
    if _has_local_commit(repo_dir, revision):
        return _run(["git", "show", f"{revision}:{rel_path}"], cwd=repo_dir)
    return _run(
        [
            "gh",
            "api",
            f"repos/{_scope().org}/{repo_name}/contents/{rel_path}?ref={revision}",
            "-H",
            "Accept: application/vnd.github.raw",
        ]
    )


def _repo_search(prefix: str, repo_name: str, revision: str, term: str) -> tuple[str, str]:
    if len(term) < 2:
        raise ValueError("Search term must be at least 2 characters")
    repo_dir = _local_dir(repo_name)
    if _has_local_commit(repo_dir, revision):
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "grep", "-n", "-I", "-i", "-F", term, revision],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        all_lines = proc.stdout.splitlines()
        hits = [f"{prefix}:{line.removeprefix(revision + ':')[:140]}" for line in all_lines[:30]]
        if not hits:
            return revision, f"No matches for '{term}' in {repo_name}@{revision}"
        header = (
            f"# Search '{term}' in {repo_name}@{revision} "
            f"(showing {len(hits)} of {len(all_lines)} matches)"
        )
        return revision, "\n".join([header, *hits])
    # GitHub code search covers only the default branch, so its result is not pinned to revision.
    search_revision = "github-index:" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        raw = _run(
            [
                "gh",
                "search",
                "code",
                term,
                "--repo",
                f"{_scope().org}/{repo_name}",
                "--limit",
                "25",
                "--json",
                "path,textMatches",
            ]
        )
    except (ValueError, subprocess.TimeoutExpired):
        return search_revision, (
            f"Search unavailable for '{term}' in {repo_name}: GitHub code search failed. "
            "Nothing was searched."
        )
    items = json.loads(raw)
    hits = []
    for item in items[:25]:
        frag = ((item.get("textMatches") or [{}])[0].get("fragment") or "").replace("\n", " ")[:120]
        hits.append(f"{prefix}:{item['path']} :: {frag}")
    scope_note = (
        f"GitHub code search on the default branch of {repo_name}; not pinned to {revision}"
    )
    if not hits:
        return search_revision, f"No matches for '{term}' ({scope_note})"
    return search_revision, "\n".join([f"# Search '{term}' ({scope_note})", *hits])


def _repo_commit(repo_name: str, sha: str) -> tuple[str, str]:
    if not sha.isalnum():
        raise ValueError("Invalid commit SHA")
    repo_dir = _local_dir(repo_name)
    if _has_local_commit(repo_dir, sha):
        return sha[:12], _run(["git", "show", "--stat", "-p", sha], cwd=repo_dir)[:12000]
    raw = _run(
        [
            "gh",
            "api",
            f"repos/{_scope().org}/{repo_name}/commits/{sha}",
            "-H",
            "Accept: application/vnd.github.v3.diff",
        ]
    )
    return sha[:12], raw[:12000]


def _org_search(term: str) -> str:
    if len(term) < 2:
        raise ValueError("Search term must be at least 2 characters")
    scope = _scope()
    hits: list[str] = []
    searched = 0
    failed = 0
    if scope.local_root and scope.local_root.is_dir():
        for repo_dir in sorted(scope.local_root.iterdir()):
            if not (repo_dir.is_dir() and (repo_dir / ".git").exists()):
                continue
            is_context = scope.context_enabled and repo_dir.name == scope.context_repo
            if not (is_context or scope.is_canonical(repo_dir.name)):
                continue
            try:
                proc = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo_dir),
                        "grep",
                        "-n",
                        "-I",
                        "-i",
                        "-F",
                        "-m",
                        "3",
                        term,
                        "HEAD",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=4,
                )
            except subprocess.TimeoutExpired:
                failed += 1
                continue
            # git grep exits 0 for hits, 1 for no hits, and above 1 for errors.
            if proc.returncode > 1:
                failed += 1
                continue
            searched += 1
            prefix = "context" if is_context else f"repo:{repo_dir.name}"
            for line in proc.stdout.splitlines()[:3]:
                hits.append(f"{prefix}:{line.removeprefix('HEAD:')[:130]}")
            if len(hits) >= 35:
                break
    if not searched:
        return (
            f"Search unavailable for '{term}' in {scope.name_prefix}* repos: no local clone "
            "could be searched. Nothing was searched, so this is not a no-match result."
        )
    coverage = f"{searched} local clone(s) searched"
    if failed:
        coverage += f", {failed} skipped after timeout or error"
    if not hits:
        return f"No matches for '{term}' in local clones ({coverage}). Remote repos not searched."
    header = (
        f"# Org search '{term}' ({coverage}; showing {min(30, len(hits))} matches, "
        "capped at 3 per repo)"
    )
    return "\n".join([header, *hits[:30]])


def _org_pulse_text() -> str:
    scope = _scope()
    repos_raw = _run(
        [
            "gh",
            "search",
            "repos",
            f"{scope.name_prefix} in:name",
            "--owner",
            scope.org,
            "--archived=false",
            "--sort",
            "updated",
            "--limit",
            "25",
            "--json",
            "name,pushedAt",
        ]
    )
    prs_raw = _run(
        [
            "gh",
            "search",
            "prs",
            scope.name_prefix,
            "--owner",
            scope.org,
            "--merged",
            "--sort",
            "updated",
            "--limit",
            "35",
            "--json",
            "repository,title,updatedAt",
        ]
    )
    repos = [r for r in json.loads(repos_raw) if scope.is_canonical(r.get("name", ""))]
    repos.sort(key=lambda r: r.get("pushedAt") or "", reverse=True)
    themes = []
    for p in json.loads(prs_raw):
        rname = (p.get("repository") or {}).get("name", "")
        if not scope.is_canonical(rname):
            continue
        if len(themes) < 10:
            date = (p.get("updatedAt") or "")[:10]
            themes.append(f"- ({date}) [{rname}] {p['title'][:85]}")
    top_repos = [
        f"- {'context' if r['name'] == scope.context_repo else 'repo:' + r['name']}:INDEX "
        f"(last push {(r.get('pushedAt') or '')[:16].replace('T', ' ')})"
        for r in repos[:12]
    ]
    source_roles = []
    if scope.context_enabled:
        source_roles.append("- context:INDEX — shared product/strategy/architecture orientation")
    source_roles.append("- repo:<service>:INDEX — owning code behavior/contracts on main")
    if scope.deployments_enabled:
        source_roles.append("- deployments:INDEX — desired environment config and commit SHAs")
    return "\n".join(
        [
            "# Ecosystem Pulse & High-Level Entrypoints (github:PULSE)",
            "# NOTE: Do NOT do micro PR reviews (automated reviewers already cover that). Focus on",
            "# high-level architecture, product strategy, cross-service workflows & innovations.",
            "",
            "## Source Roles (triangulate; no single source tells the whole story)",
            *source_roles,
            "",
            "## Active Owning Services by Latest Main Push",
            *top_repos,
            "",
            "## Recent High-Level Themes Shipped Across the Stack",
            *themes,
        ]
    )


@lru_cache(maxsize=4)
def _org_pulse_snapshot(bucket: int) -> tuple[str, str]:
    # The bucket only keys the cache: one fetch serves one interval, then content is refetched.
    captured_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return captured_at, _org_pulse_text()


def _org_pulse() -> tuple[str, str]:
    return _org_pulse_snapshot(_ttl_bucket())


def list_source_entrypoints() -> list[str]:
    scope = _scope()
    entries: list[str] = []
    if scope.repos_enabled:
        entries += ["github:PULSE", "github:SEARCH:<term>"]
    if scope.context_enabled:
        entries.append("context:INDEX")
    if scope.deployments_enabled:
        entries.append("deployments:INDEX")
    for repo in _discover_github_repos():
        if not (scope.context_enabled and repo == scope.context_repo):
            entries.append(f"repo:{repo}:INDEX")
    return entries


def _dispatch_repo(prefix: str, repo_name: str, rel_path: str) -> tuple[str, str]:
    if rel_path.startswith("PR:"):
        num = rel_path.removeprefix("PR:").strip()
        if not num.isdigit():
            raise ValueError("PR number must be numeric")
        return _repo_pr_detail(repo_name, int(num), _ttl_bucket())
    if rel_path.startswith("COMMIT:"):
        return _repo_commit(repo_name, rel_path.removeprefix("COMMIT:").strip())
    revision = _resolve_repo_head(repo_name, _local_dir(repo_name))
    if rel_path == "INDEX":
        return revision, _repo_index(prefix, repo_name, revision)
    if rel_path.startswith("TREE:"):
        return revision, _repo_tree_query(
            prefix, repo_name, revision, rel_path.removeprefix("TREE:").strip()
        )
    if rel_path == "PRS":
        return revision, _repo_prs(repo_name)
    if rel_path.startswith("SEARCH:"):
        return _repo_search(prefix, repo_name, revision, rel_path.removeprefix("SEARCH:").strip())
    return revision, _repo_blob(repo_name, revision, rel_path)


def _read_git_source(source_id: str) -> tuple[str, str]:
    scope = _scope()
    if source_id.startswith("github:SEARCH:"):
        if not scope.repos_enabled:
            raise ValueError(DENIED)
        term = source_id.removeprefix("github:SEARCH:").strip()
        return "org-search", _org_search(term)

    if source_id.startswith("context:"):
        rel_path = source_id.removeprefix("context:")
        if not scope.context_enabled or not rel_path or rel_path.startswith("."):
            raise ValueError(DENIED)
        return _dispatch_repo("context", scope.context_repo, rel_path)

    if source_id.startswith("deployments:"):
        rel_path = source_id.removeprefix("deployments:")
        if not scope.deployments_enabled or not rel_path or rel_path.startswith("."):
            raise ValueError(DENIED)
        return _dispatch_repo("deployments", scope.deployments_repo, rel_path)

    if source_id.startswith("repo:"):
        parts = source_id.split(":", 2)
        if len(parts) != 3:
            raise ValueError(DENIED)
        _, repo_name, rel_path = parts
        if not scope.is_canonical(repo_name) or not rel_path or rel_path.startswith("."):
            raise ValueError(DENIED)
        return _dispatch_repo(f"repo:{repo_name}", repo_name, rel_path)

    raise ValueError(DENIED)


def _page(
    query: SourceRead, revision: str, content: str, captured_at: str, *, synthetic: bool
) -> SourcePage:
    end = min(len(content), query.offset + query.limit)
    return SourcePage(
        source_id=query.source_id,
        revision=revision,
        captured_at=captured_at,
        text=content[query.offset : end],
        offset=query.offset,
        next_offset=end if end < len(content) else None,
        synthetic=synthetic,
    )


def read_source(query: SourceRead) -> SourcePage:
    if query.source_id in SOURCES:
        revision, content = SOURCES[query.source_id]
        return _page(query, revision, content, "2026-01-01T00:00:00Z", synthetic=True)
    if query.source_id == "github:PULSE":
        if not _scope().repos_enabled:
            raise ValueError(DENIED)
        captured_at, content = _org_pulse()
        revision = captured_at.replace("-", "").replace(":", "")
        return _page(query, revision, content, captured_at, synthetic=False)
    revision, content = _read_git_source(query.source_id)
    captured_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _page(query, revision, content, captured_at, synthetic=False)
