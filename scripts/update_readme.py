#!/usr/bin/env python3
"""Update README.md with dynamic content: ASCII cat status and language stats."""

import json
import os
import random
import re
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

GITHUB_USER = "nevstop"
GITHUB_ORGS = ["NEVSTOP-LAB"]
VIPM_PUBLISHER = "nevstop"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_ROOT, "README.md")

MAX_EVENT_PAGES = 3       # pages of GitHub Events API to scan for commits
MAX_LANGS_DISPLAY = 8
LANG_BAR_WIDTH = 18
MAX_REPOS_FOR_ACTIVITY_SCAN = 60
MAX_REPOS_FOR_LANGUAGE_SCAN = 120
VIPM_FETCH_TIMEOUT = 15   # seconds to wait for vipm.io response
_VIPM_JSON_MAX_DEPTH = 6  # maximum recursion depth when walking VIPM JSON
VIPM_URL = f"https://www.vipm.io/publisher/nevstop/"

# Beijing Time (UTC+8)
BJT = timezone(timedelta(hours=8))

# ── Cat Status Templates ────────────────────────────────────────────────────
# {n} in status will be replaced with the commit count.

_CATS_IDLE = [
    "💤 摸鱼模式 | 昨天没有提交代码哦~",
    "💤 摸鱼模式 | 进入低功耗模式~",
    "😴 摸鱼模式 | 悄悄打了个盹~",
    "💤 摸鱼模式 | 半梦半醒中~",
    "🌙 摸鱼模式 | 与星星作伴中~",
    "😢 摸鱼模式 | 今天没有产出...",
]

_CATS_LIGHT = [
    "🌱 轻松模式 | 昨天提交了 {n} 个 commit",
    "🤔 好奇模式 | 昨天提交了 {n} 个 commit",
    "😌 稳健模式 | 昨天提交了 {n} 个 commit",
    "✨ 活力模式 | 昨天提交了 {n} 个 commit",
    "😊 开心模式 | 昨天提交了 {n} 个 commit",
    "👀 认真模式 | 昨天提交了 {n} 个 commit",
]

_CATS_FOCUS = [
    "💻 专注模式 | 昨天提交了 {n} 个 commit",
    "🎯 冲刺模式 | 昨天提交了 {n} 个 commit",
    "🌟 高效模式 | 昨天提交了 {n} 个 commit",
    "👊 干劲模式 | 昨天提交了 {n} 个 commit",
    "🔍 钻研模式 | 昨天提交了 {n} 个 commit",
    "😎 自信模式 | 昨天提交了 {n} 个 commit",
]

_CATS_HEAVY = [
    "🔥 疯狂加班 | 昨天提交了 {n} 个 commit！",
    "😱 震撼模式 | 昨天提交了 {n} 个 commit！",
    "💥 超载模式 | 昨天提交了 {n} 个 commit！",
    "😤 爆发模式 | 昨天提交了 {n} 个 commit！",
    "🚀 飞速模式 | 昨天提交了 {n} 个 commit！",
    "💰 黄金模式 | 昨天提交了 {n} 个 commit！",
]

_CATS_ULTRA = [
    "🌋 传说级加班 | 昨天提交了 {n} 个 commit！！",
    "🏆 超神模式 | 昨天提交了 {n} 个 commit！！",
    "🎆 疯狂模式 | 昨天提交了 {n} 个 commit！！",
    "💀 极限模式 | 昨天提交了 {n} 个 commit！！",
    "⚡ 闪电模式 | 昨天提交了 {n} 个 commit！！",
    "🎯 传说级  | 昨天提交了 {n} 个 commit！！",
]


_PRE_STYLE = (
    "display:inline-block;"
    "margin:0;"
    "text-align:left;"
    "font-family:'Cascadia Mono','Consolas','Menlo','Monaco',monospace;"
    "line-height:1.2;"
)


def _pick_cat(cats, commit_count, today):
    """Pick a cat deterministically for the given day."""
    rng = random.Random(today.toordinal())
    msg_tpl = rng.choice(cats)
    msg = msg_tpl.format(n=commit_count)
    return msg


_CAT_ACTIONS = {
    "sleepy": [" / >~", " \\ <~", " / >zz"],
    "happy":  [" / >~", " \\ <~", " / >♪"],
    "focused":[" / >~", " \\ <~", " / >!!"],
    "intense":[" / >!!", " / >~!", " \\ <!"],
}


def _cat_ascii(expression, today=None):
    """Return a main ASCII cat based on mood expression.

    *today* (a ``date``) is used as a deterministic seed so the action
    variant changes day-by-day without being truly random.
    """
    eye_map = {
        "sleepy":  "( -.- ) zZ",
        "happy":   "( ^.^ )",
        "focused": "( o.o )",
        "intense": "( >.< )",
    }
    eyes = eye_map.get(expression, "( ^.^ )")
    actions = _CAT_ACTIONS.get(expression, [" / >~"])
    if today is not None:
        action = random.Random(today.toordinal() + hash(expression) % 997).choice(actions)
        # 997 is a small prime used to offset the per-expression seed so that
        # different moods do not always land on the same action on the same day.
    else:
        action = actions[0]
    return "\n".join([" /\\_/\\", eyes, action])


def _mini_ascii_cat(item=None):
    """Return a companion mini ASCII cat.

    *item* controls what the cat is holding:
    - ``None``  → nothing (tail ``~~``)
    - ``'pr'``  → holding a PR sign (``[P]``)
    - ``'bug'`` → holding a bug/issue card (``[!]``)
    """
    paw_map = {
        "pr":  "[P]",
        "bug": "[!]",
    }
    paw = paw_map.get(item, "~~")
    return "\n".join(
        [
            " /\\_/\\",
            "(o.o )",
            f" / {paw}",
        ]
    )


# ── GitHub API Helper ───────────────────────────────────────────────────────


def github_api(url):
    """Make an authenticated GitHub API request."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"⚠️  GitHub API error {exc.code} for {url}: {exc.reason}")
        if exc.code == 403:
            print("   Hint: this may be a rate-limit issue — check GITHUB_TOKEN")
        return [] if "repos" in url or "events" in url else {}
    except urllib.error.URLError as exc:
        print(f"⚠️  Network error for {url}: {exc.reason}")
        return [] if "repos" in url or "events" in url else {}


# ── Commit Counting ────────────────────────────────────────────────────────


def _get_yesterday_range(now_bjt=None):
    """Return a tuple of yesterday's (start, end) datetimes in Beijing time."""
    if now_bjt is None:
        now_bjt = datetime.now(BJT)
    yesterday = now_bjt - timedelta(days=1)
    day_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    return day_start, day_end


def _to_bjt(dt_str):
    """Convert an ISO 8601 UTC timestamp (e.g. ...Z) to Beijing time."""
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(BJT)


def _count_push_commits_from_url(events_url, day_start, day_end, seen_ids):
    """Count push-event commits in the yesterday window from one events endpoint.

    *seen_ids* (a ``set``) is updated in-place so callers can deduplicate across
    multiple endpoints (e.g. user events + org events).
    """
    count = 0
    for page in range(1, MAX_EVENT_PAGES + 1):
        events = github_api(f"{events_url}?per_page=100&page={page}")
        if not events:
            break
        past_window = False
        for event in events:
            event_time = _to_bjt(event["created_at"])
            if event_time < day_start:
                past_window = True
                break
            if event["type"] != "PushEvent":
                continue
            if day_start <= event_time <= day_end:
                event_id = event.get("id")
                if event_id and event_id in seen_ids:
                    continue
                if event_id:
                    seen_ids.add(event_id)
                count += event.get("payload", {}).get("size", 0)
        if past_window:
            break
    return count


def get_yesterday_commits(orgs=None):
    """Count the user's push-event commits from yesterday (Beijing time).

    Tries the GitHub GraphQL ``contributionsCollection`` API first so that
    **both public and private commits** are counted correctly.  Falls back to
    scanning the REST Events API (which may miss some private events) when the
    GraphQL call is unavailable or returns zero.

    Scans the user's own event stream *and* each org's event stream so that
    commits to private organisation repositories are also captured when the
    workflow token has the necessary ``read:org`` permission.  Events are
    deduplicated by event-ID to avoid double-counting.
    """
    day_start, day_end = _get_yesterday_range()

    # ── Primary: GraphQL contributionsCollection (includes private commits) ──
    graphql_count = _get_commits_via_graphql(day_start, day_end)
    if graphql_count > 0:
        print(f"ℹ️  Commit count via GraphQL: {graphql_count} (includes private)")
        return graphql_count

    # ── Fallback: REST Events API ─────────────────────────────────────────────
    seen_ids: set = set()

    commit_count = _count_push_commits_from_url(
        f"https://api.github.com/users/{GITHUB_USER}/events",
        day_start, day_end, seen_ids,
    )

    # Org-scoped events (requires auth; fails silently if not permitted)
    for org in (orgs or []):
        org_url = f"https://api.github.com/users/{GITHUB_USER}/events/orgs/{org}"
        commit_count += _count_push_commits_from_url(
            org_url, day_start, day_end, seen_ids
        )

    return commit_count


def _get_commits_via_graphql(day_start, day_end):
    """Use the GitHub GraphQL API to count commits in [day_start, day_end].

    Returns the commit count, or 0 on any failure (e.g. no token / no
    ``repo`` scope).  Private contributions are included when the token has
    the ``repo`` scope.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return 0

    # contributionsCollection requires ISO-8601 with timezone
    from_str = day_start.isoformat()
    to_str = day_end.isoformat()

    query = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""
    payload = json.dumps({
        "query": query,
        "variables": {
            "login": GITHUB_USER,
            "from": from_str,
            "to": to_str,
        },
    }).encode()

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        cc = data["data"]["user"]["contributionsCollection"]
        total = cc.get("totalCommitContributions", 0)
        restricted = cc.get("restrictedContributionsCount", 0)
        print(
            f"ℹ️  GraphQL commits: totalCommit={total}, restricted={restricted}"
        )
        return total + restricted
    except Exception as exc:
        print(f"⚠️  GraphQL commit query failed: {exc}")
        return 0


# ── Repo Helpers ────────────────────────────────────────────────────────────


def _append_params(url, params):
    """Append query parameters to a URL."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{params}"


def _fetch_all_repos(url):
    """Paginate through a GitHub list endpoint."""
    repos = []
    page = 1
    while True:
        data = github_api(_append_params(url, f"per_page=100&page={page}"))
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def _get_target_orgs():
    """Collect static + discovered orgs for the user."""
    orgs = list(GITHUB_ORGS)
    discovered_orgs = github_api(f"https://api.github.com/users/{GITHUB_USER}/orgs?per_page=100")
    if isinstance(discovered_orgs, list):
        for org in discovered_orgs:
            login = org.get("login")
            if login and login not in orgs:
                orgs.append(login)
    return orgs


def get_owned_repos():
    """Return all non-fork repos owned by the user or related orgs."""
    repos = _fetch_all_repos(
        f"https://api.github.com/users/{GITHUB_USER}/repos?type=owner"
    )
    for org in _get_target_orgs():
        repos.extend(
            _fetch_all_repos(f"https://api.github.com/orgs/{org}/repos")
        )

    unique_repos = {}
    for repo in repos:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        unique_repos[full_name] = repo

    return [
        repo
        for repo in unique_repos.values()
        if not repo.get("fork") and repo.get("name") != GITHUB_USER
    ]


def get_yesterday_repo_activity_flags(repos):
    """Return repo-wide activity info for yesterday in BJT.

    Returns a tuple:
    ``(has_commit_or_pr, has_issue, pr_actors, issue_actors)``

    *pr_actors* and *issue_actors* are sets of GitHub login names that
    opened pull requests / issues in any of the scanned repos yesterday.
    """
    day_start, day_end = _get_yesterday_range()
    has_repo_commit_or_pr_activity = False
    has_repo_issue_activity = False
    pr_actors: set = set()
    issue_actors: set = set()

    repo_candidates = sorted(
        repos,
        key=lambda repo: repo.get("pushed_at") or "",
        reverse=True,
    )[:MAX_REPOS_FOR_ACTIVITY_SCAN]
    if len(repos) > len(repo_candidates):
        print(
            f"ℹ️  Activity scan capped: {len(repo_candidates)}/{len(repos)} repos "
            "(most recently pushed)"
        )

    for repo in repo_candidates:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        events = github_api(f"https://api.github.com/repos/{full_name}/events?per_page=100")
        if not isinstance(events, list):
            continue

        for event in events:
            created_at = event.get("created_at")
            event_type = event.get("type")
            if not created_at or not event_type:
                continue

            event_time = _to_bjt(created_at)
            if event_time < day_start:
                continue
            if event_time > day_end:
                continue

            actor_login = event.get("actor", {}).get("login", "")
            if event_type in ("PushEvent", "PullRequestEvent"):
                has_repo_commit_or_pr_activity = True
                if event_type == "PullRequestEvent" and actor_login:
                    pr_actors.add(actor_login)
            elif event_type == "IssuesEvent":
                has_repo_issue_activity = True
                if actor_login:
                    issue_actors.add(actor_login)

    return has_repo_commit_or_pr_activity, has_repo_issue_activity, pr_actors, issue_actors


def get_language_totals(repos):
    """Aggregate repo language bytes from GitHub API; return empty dict on no data."""
    totals = defaultdict(int)
    repo_candidates = sorted(
        repos,
        key=lambda repo: repo.get("stargazers_count", 0),
        reverse=True,
    )[:MAX_REPOS_FOR_LANGUAGE_SCAN]
    if len(repos) > len(repo_candidates):
        print(
            f"ℹ️  Language scan capped: {len(repo_candidates)}/{len(repos)} repos "
            "(highest stars first)"
        )

    for repo in repo_candidates:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        lang_data = github_api(f"https://api.github.com/repos/{full_name}/languages")
        if not isinstance(lang_data, dict):
            print(
                f"⚠️  Skip language stats for {full_name}: expected dict response, "
                f"got {type(lang_data).__name__}"
            )
            continue
        for lang, size in lang_data.items():
            if isinstance(size, int) and size > 0:
                totals[lang] += size
    return dict(totals)


# ── Section Generators ──────────────────────────────────────────────────────


def _resolve_cat_state(commit_count, today):
    """Resolve cat expression and status message."""
    if today is None:
        today = datetime.now(BJT).date()

    if commit_count == 0:
        cats = _CATS_IDLE
        expression = "sleepy"
    elif commit_count <= 3:
        cats = _CATS_LIGHT
        expression = "happy"
    elif commit_count <= 8:
        cats = _CATS_FOCUS
        expression = "focused"
    elif commit_count <= 15:
        cats = _CATS_HEAVY
        expression = "intense"
    else:
        cats = _CATS_ULTRA
        expression = "intense"

    msg = _pick_cat(cats, commit_count, today)
    return expression, msg


def _cats_side_by_side(cat_strings, gap=4):
    """Render multiple ASCII cats horizontally on the same row.

    Each cat_string is a multi-line block; rows are zipped side-by-side
    separated by *gap* spaces.
    """
    split = [c.split("\n") for c in cat_strings]
    height = max(len(rows) for rows in split)
    width = [max(len(r) for r in rows) for rows in split]
    padded = []
    for i, rows in enumerate(split):
        col = [r.ljust(width[i]) for r in rows]
        col += [" " * width[i]] * (height - len(col))
        padded.append(col)
    sep = " " * gap
    return "\n".join(sep.join(col[row] for col in padded) for row in range(height))


def generate_cat_section(
    commit_count,
    has_commit_or_pr=False,
    has_issue=False,
    today=None,
    pr_actors=None,
    issue_actors=None,
):
    """Build the ASCII cat block + status line for the given commit count.

    HTML comments are appended below the status line so the raw source
    carries useful context without affecting the rendered markdown.
    """
    expression, msg = _resolve_cat_state(commit_count, today)
    cats = [_cat_ascii(expression, today=today)]
    if has_commit_or_pr:
        cats.append(_mini_ascii_cat(item="pr"))
    if has_issue:
        cats.append(_mini_ascii_cat(item="bug"))

    cat_ascii_art = _cats_side_by_side(cats)
    cat_html = f'<pre style="{_PRE_STYLE}">\n{cat_ascii_art}\n</pre>'

    # Build an HTML comment block with machine-readable context that is
    # invisible in rendered markdown but visible when reading the source.
    pr_names = ", ".join(sorted(pr_actors)) if pr_actors else "无"
    issue_names = ", ".join(sorted(issue_actors)) if issue_actors else "无"
    comment = (
        f"<!-- Yesterday Stats (昨日数据统计): commits={commit_count}"
        f", PR authors (PR提交者)={pr_names}"
        f", issue authors (issue提交者)={issue_names}"
        " -->"
    )

    return f"{cat_html}\n\n{msg}\n{comment}"


def generate_language_stats_section(language_totals):
    """Build Most Used Language section based on all owned repos."""
    if not language_totals:
        return (
            f'<pre style="{_PRE_STYLE}">\n'
            "Most Used Language (all owned repos)\n\n"
            "暂无可用数据（可能受到 API 限流影响）\n"
            "</pre>"
        )

    total_bytes = sum(language_totals.values())
    top_langs = sorted(language_totals.items(), key=lambda item: item[1], reverse=True)[:MAX_LANGS_DISPLAY]
    max_name_len = max(len(name) for name, _ in top_langs)

    lines = ["Most Used Language (all owned repos)", ""]
    for lang, size in top_langs:
        ratio = size / total_bytes if total_bytes else 0
        filled = int(round(ratio * LANG_BAR_WIDTH))
        bar = ("█" * filled).ljust(LANG_BAR_WIDTH, "░")
        lines.append(f"{lang.ljust(max_name_len)}  {bar}  {ratio * 100:5.1f}%")

    content = "\n".join(lines)
    return f'<pre style="{_PRE_STYLE}">\n{content}\n</pre>'


# ── VIPM Package Stats ──────────────────────────────────────────────────────


def _extract_packages_from_json(data, depth=0):
    """Recursively search parsed JSON for a list of VIPM package objects."""
    if depth > _VIPM_JSON_MAX_DEPTH:
        return []
    if isinstance(data, list) and data:
        packages = []
        for item in data:
            if not isinstance(item, dict):
                break
            name = (
                item.get("display_name")
                or item.get("name")
                or item.get("title")
                or item.get("package_name")
                or ""
            )
            installs = item.get("install_count") or item.get("installs") or 0
            stars = item.get("star_count") or item.get("stars") or 0
            if name and isinstance(installs, (int, float)):
                packages.append({
                    "name": str(name),
                    "installs": int(installs),
                    "stars": int(stars),
                })
        if packages:
            return packages
    if isinstance(data, dict):
        for key in ("packages", "results", "items", "data", "products"):
            val = data.get(key)
            if val:
                result = _extract_packages_from_json(val, depth + 1)
                if result:
                    return result
        for val in data.values():
            if isinstance(val, (dict, list)):
                result = _extract_packages_from_json(val, depth + 1)
                if result:
                    return result
    return []


def get_vipm_packages():
    """Fetch package stats from the VIPM publisher page.

    Returns a list of dicts with keys ``name``, ``installs``, ``stars``.
    Returns an empty list on any failure so the caller can skip the section.
    """
    url = f"https://www.vipm.io/publisher/{VIPM_PUBLISHER}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=VIPM_FETCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"⚠️  VIPM fetch error: {exc}")
        return []

    # Strategy 1: __NEXT_DATA__ JSON embedded by Next.js
    match = re.search(
        r'(?i)<script\s+id="__NEXT_DATA__"\s+type="application/json"\s*>([\s\S]*?)</script>',
        html,
    )
    if match:
        try:
            pkgs = _extract_packages_from_json(json.loads(match.group(1)))
            if pkgs:
                print(f"ℹ️  VIPM: found {len(pkgs)} packages via __NEXT_DATA__")
                return pkgs
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 2: any <script> block mentioning install_count
    for script_match in re.finditer(r"(?i)<script[^>]*>([\s\S]*?)</script>", html):
        body = script_match.group(1)
        if '"install_count"' not in body and '"installs"' not in body:
            continue
        # Try to parse embedded JSON arrays
        for json_match in re.finditer(r"(\[{[\s\S]*?}\])", body):
            try:
                pkgs = _extract_packages_from_json(json.loads(json_match.group(1)))
                if pkgs:
                    print(f"ℹ️  VIPM: found {len(pkgs)} packages via script scan")
                    return pkgs
            except (json.JSONDecodeError, ValueError):
                pass

    print("⚠️  VIPM: could not parse package data from page")
    # Strategy 3: HTML attribute / text pattern scan
    # Look for numeric totals embedded directly in the HTML, e.g.:
    #   data-install-count="1234"  or  installs: 1234
    #   as a coarse last-resort so we surface *something*.
    install_match = re.search(
        r'(?:data-install[_-]count|install[_-]count|installs)["\s:=]+([0-9,]+)',
        html, re.IGNORECASE,
    )
    star_match = re.search(
        r'(?:data-star[_-]count|star[_-]count|stars)["\s:=]+([0-9,]+)',
        html, re.IGNORECASE,
    )
    # Count package entries via a simple heuristic.
    # These CSS class fragments target typical VIPM publisher-page markup.
    # If vipm.io redesigns its HTML, add new class names here.
    pkg_count = len(re.findall(
        r'(?:package-card|pkg-title|package__title|vipm-package)',
        html, re.IGNORECASE,
    ))
    if install_match and pkg_count > 0:
        total_installs = int(install_match.group(1).replace(",", ""))
        total_stars = int(star_match.group(1).replace(",", "")) if star_match else 0
        print(
            f"ℹ️  VIPM: HTML heuristic — {pkg_count} packages, "
            f"{total_installs} installs, {total_stars} stars"
        )
        # Return a synthesised package list so callers see the right totals.
        # Each entry uses a placeholder name because the HTML heuristic only
        # extracts aggregate numbers, not individual package metadata.
        per_pkg_installs = total_installs // max(pkg_count, 1)
        per_pkg_stars = total_stars // max(pkg_count, 1)
        return [
            {"name": f"package-{i}", "installs": per_pkg_installs, "stars": per_pkg_stars}
            for i in range(pkg_count)
        ]

    print("⚠️  VIPM: all parse strategies exhausted — no data available")
    return []


def _parse_vipm_inline_totals(readme_content):
    """Extract (installs, stars) from the existing VIPM_INLINE section.

    Returns (0, 0) when no previous data is found so the delta is omitted
    on the first run.
    """
    match = re.search(
        r"<!-- VIPM_INLINE_START -->([\s\S]*?)<!-- VIPM_INLINE_END -->",
        readme_content,
    )
    if not match:
        return 0, 0
    block = match.group(1)
    installs_m = re.search(r"([\d,]+)\s+installs", block)
    stars_m = re.search(r"([\d,]+)\s+stars", block)
    installs = int(installs_m.group(1).replace(",", "")) if installs_m else 0
    stars = int(stars_m.group(1).replace(",", "")) if stars_m else 0
    return installs, stars


def generate_vipm_inline_line(packages, old_installs=0, old_stars=0):
    """Build a single inline text line for the LabVIEW developer description.

    Example output:
      > 🔧 LabVIEW 开发者：[VIPM](https://www.vipm.io/publisher/nevstop/): \
          16 packages, 34,469 installs, 69 stars，今日新增 installs: +123；Stars: +5
    """
    if not packages:
        return f"> 🔧 LabVIEW 开发者：[VIPM]({VIPM_URL})"

    total_pkgs = len(packages)
    total_installs = sum(p["installs"] for p in packages)
    total_stars = sum(p["stars"] for p in packages)

    base = (
        f"> 🔧 LabVIEW 开发者：[VIPM]({VIPM_URL}): "
        f"{total_pkgs} packages, {total_installs:,} installs, {total_stars:,} stars"
    )

    # Append delta only when we have a previous reading
    if old_installs > 0 or old_stars > 0:
        delta_i = total_installs - old_installs
        delta_s = total_stars - old_stars
        sign_i = "+" if delta_i >= 0 else ""
        sign_s = "+" if delta_s >= 0 else ""
        base += f"，今日新增 installs: {sign_i}{delta_i:,}；Stars: {sign_s}{delta_s}"

    return base


# ── README Updater ──────────────────────────────────────────────────────────


def replace_section(content, tag, replacement):
    """Replace content between <!-- TAG_START --> and <!-- TAG_END -->."""
    pattern = rf"(<!-- {tag}_START -->).*?(<!-- {tag}_END -->)"
    return re.sub(
        pattern,
        lambda m: f"{m.group(1)}\n{replacement}\n{m.group(2)}",
        content,
        flags=re.DOTALL,
    )


def main():
    orgs = _get_target_orgs()
    commit_count = get_yesterday_commits(orgs=orgs)
    repos = get_owned_repos()
    has_commit_or_pr, has_issue, pr_actors, issue_actors = get_yesterday_repo_activity_flags(repos)
    language_totals = get_language_totals(repos)
    vipm_packages = get_vipm_packages()
    now_bjt = datetime.now(BJT)
    today = now_bjt.date()

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Update ASCII cat
    content = replace_section(
        content,
        "CAT",
        generate_cat_section(
            commit_count,
            has_commit_or_pr,
            has_issue,
            today=today,
            pr_actors=pr_actors,
            issue_actors=issue_actors,
        ),
    )

    # Update inline VIPM stats (read old totals first for delta, then overwrite)
    old_installs, old_stars = _parse_vipm_inline_totals(content)
    vipm_line = generate_vipm_inline_line(vipm_packages, old_installs, old_stars)
    content = replace_section(content, "VIPM_INLINE", vipm_line)

    # Update Most Used Language stats
    content = replace_section(content, "LANG_STATS", generate_language_stats_section(language_totals))

    # Update timestamp
    now_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M (北京时间)")
    content = replace_section(content, "UPDATE_TIME", f"🕐 最近更新: {now_str}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(
        f"✅ README updated — {commit_count} commits yesterday, "
        f"{len(repos)} owned repos scanned, "
        f"{len(vipm_packages)} VIPM packages"
    )


if __name__ == "__main__":
    main()
