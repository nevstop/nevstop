#!/usr/bin/env python3
"""Update README.md with dynamic content: ASCII cat status and language stats."""

import json
import math
import os
import random
import re
import urllib.error
import urllib.request
import zlib
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

# ── Bot / AI Account Filter ─────────────────────────────────────────────────

# Known bot/AI logins (case-insensitive exact match after lower())
_KNOWN_BOTS = frozenset({
    "github-copilot", "copilot",
    "dependabot", "dependabot-preview",
    "renovate", "renovate-bot",
    "snyk-bot", "whitesource-bolt-for-github",
    "imgbot", "allcontributors-bot",
    "pre-commit-ci", "deepsource-autofix",
})


def _is_bot(login: str) -> bool:
    """Return True if *login* belongs to a bot or AI account.

    Matches:
    - logins that contain ``[bot]`` (e.g. ``github-actions[bot]``)
    - logins that end with ``-bot`` or ``_bot``
    - logins in the known-bots blocklist
    """
    if not login:
        return True
    lower = login.lower()
    return (
        "[bot]" in lower
        or lower.endswith("-bot")
        or lower.endswith("_bot")
        or lower in _KNOWN_BOTS
    )


_PRE_STYLE = (
    "display:inline-block;"
    "margin:0;"
    "text-align:left;"
    "font-family:'Cascadia Mono','Consolas','Menlo','Monaco',monospace;"
    "line-height:1.2;"
)


def _pick_cat(cats, commit_count, today):
    """Pick a daily cat phrase with deterministic day-to-day variety."""
    seed = today.toordinal() + (commit_count * _CAT_VARIANT_SEED_MULTIPLIER)
    prev_seed = (
        (today - timedelta(days=1)).toordinal()
        + (commit_count * _CAT_VARIANT_SEED_MULTIPLIER)
    )
    msg_tpl = _pick_daily_variant(cats, seed, prev_seed=prev_seed)
    msg = msg_tpl.format(n=commit_count)
    return msg


def _pick_daily_variant(options, seed, prev_seed=None):
    """Pick a deterministic daily variant and avoid adjacent-day repeats."""
    if not options:
        raise ValueError("options must not be empty")
    rng = random.Random(seed)
    idx = rng.randrange(len(options))
    if len(options) > 1:
        if prev_seed is None:
            prev_seed = seed - 1
        prev_idx = random.Random(prev_seed).randrange(len(options))
        if idx == prev_idx:
            if len(options) == 2:
                idx = 1 - idx
            else:
                offset = 1 + rng.randrange(len(options) - 1)
                idx = (idx + offset) % len(options)
    return options[idx]


_CAT_ACTIONS = {
    "sleepy": [" / >~", " \\ <~", " / >zz"],
    "happy":  [" / >~", " \\ <~", " / >♪"],
    "focused":[" / >~", " \\ <~", " / >!!"],
    "intense":[" / >!!", " / >~!", " \\ <!"],
}

_EXTRA_CAT_ROLES = [
    # (role_key, label, item, desc, face)
    ("review_cat",   "Review猫", "🔍", "你在帮别人看代码", "( *.* )"),
    ("merge_cat",    "Merge猫",  "🚩", "你是合代码的主力", "( ^.^ )"),
    ("star_cat",     "Star猫",   "⭐", "你的项目被人喜欢", "( ★.★)"),
    ("fork_cat",     "Fork猫",   "🌿", "代码被二次开发",   "(o.o )"),
    ("discussion_cat","讨论猫",  "📢", "社区活跃分子",     "( >.< )"),
    ("wiki_cat",     "Wiki猫",   "📘", "你在写文档",       "( -.- )"),
]

_ANIMAL_ROLES = [
    ("mouse", "🐭", "Fix that!"),
    ("penguin", "🐧", "Linux vibes"),
    ("octopus", "🐙", "Multi-branch"),
    ("fox", "🦊", "Reviewed your PR"),
    ("bee", "🐝", "Rapid commits"),
]

_SPECIAL_DAY_OUTFITS = {
    "01-01": "🎊",  # 新年
    "04-01": "🤡",  # 愚人节
    "12-25": "🎅",  # 圣诞节
}

_GHOST_CAT_SEED_OFFSET = 404
_GHOST_CAT_PROBABILITY = 0.01
_CAT_VARIANT_SEED_MULTIPLIER = 131
_MAX_EXTRA_ROLE_CATS = 5
_BUGFIX_KEYWORDS = ("fix", "bug", "修复")
_LINUX_KEYWORDS = ("docker", "linux", "k8s", "container")
_LATE_NIGHT_HOURS = tuple(range(2, 6))
_DAYTIME_HOURS = tuple(range(8, 19))
_DEFAULT_WEEKLY_COMMIT_GOAL = 100
_WEEKLY_PROGRESS_WIDTH = 12
_STREAK_PAW_MAX_DOTS = 14


def _get_positive_int_env(name, default):
    """Read a positive integer from env; fallback to *default* on invalid input."""
    fallback_msg = (
        f"⚠️  Invalid {name}={{raw!r}}; "
        f"must be a positive integer, falling back to {default}"
    )
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        print(fallback_msg.format(raw=raw))
        return default
    if value <= 0:
        print(fallback_msg.format(raw=raw))
        return default
    return value


_WEEKLY_COMMIT_GOAL = _get_positive_int_env(
    "WEEKLY_COMMIT_GOAL", _DEFAULT_WEEKLY_COMMIT_GOAL
)


def _cat_ascii(
    expression,
    today=None,
    eye_override=None,
    hat=None,
    hand_item="",
    outfit=None,
    aura=None,
):
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
    eyes = eye_override or eye_map.get(expression, "( ^.^ )")
    actions = _CAT_ACTIONS.get(expression, [" / >~"])
    if today is not None:
        expression_seed = zlib.adler32(expression.encode())
        seed = today.toordinal() + expression_seed
        prev_seed = (
            (today - timedelta(days=1)).toordinal()
            + expression_seed
        )
        action = _pick_daily_variant(actions, seed, prev_seed=prev_seed)
    else:
        action = actions[0]
    # Hat sits in the middle of the ears: /\🧢/\; outfit and aura trail after.
    if hat:
        ear_line = f" /\\{hat}/\\"
    else:
        ear_line = " /\\_/\\"
    if outfit:
        ear_line = f"{ear_line} {outfit}"
    if aura:
        ear_line = f"{ear_line} {aura}"
    paw_line = action if not hand_item else f"{action} {hand_item}"
    return "\n".join([ear_line, eyes, paw_line])


def _mini_ascii_cat(item=None, face="(o.o )", hint=None):
    """Return a companion mini ASCII cat.

    *item* controls what the cat is holding:
    - ``None``  → nothing (tail ``~~``)
    - ``'pr'``  → holding a PR sign (``[P]``)
    - ``'bug'`` → holding a bug/issue card (``[!]``)

    *face* customises the eyes / expression row.
    *hint* is an optional short label appended as a 4th line (e.g. easter hints).
    """
    paw_map = {
        "pr":  "[P]",
        "bug": "[!]",
    }
    paw = paw_map.get(item) if item in paw_map else (item if item is not None else "~~")
    lines = [
        " /\\_/\\",
        face,
        f" / {paw}",
    ]
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def _mini_ascii_animal(symbol, bubble):
    """Return a compact non-cat companion as a single display line.

    Format: ``🐭："Fix that!"``  (shown at the bottom of the pre block)
    """
    return f'{symbol}："{bubble}"'


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
    scanning the REST Events API (which may miss some private events) only
    when the GraphQL call fails (returns ``None``); a GraphQL result of 0 is
    treated as a valid count and returned directly without falling back.

    Scans the user's own event stream *and* each org's event stream so that
    commits to private organisation repositories are also captured when the
    workflow token has the necessary ``read:org`` permission.  Events are
    deduplicated by event-ID to avoid double-counting.
    """
    day_start, day_end = _get_yesterday_range()

    # ── Primary: GraphQL contributionsCollection (includes private commits) ──
    graphql_count = _get_commits_via_graphql(day_start, day_end)
    if graphql_count is not None:
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

    Returns the commit count on success, or ``None`` on any failure (e.g.
    no token / no ``repo`` scope) so that callers can distinguish a genuine
    zero from an error.  Private contributions are included when the token
    has the ``repo`` scope.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None

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
        return None


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


def get_target_orgs():
    """Public wrapper for :func:`_get_target_orgs` used by sibling scripts."""
    return _get_target_orgs()


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

    Returns a dict with base + enhanced activity dimensions.

    *pr_actors* and *issue_actors* are sets of **human** GitHub login names
    (bots/AI accounts are filtered out) that opened pull requests / issues in
    any of the scanned repos yesterday.

    *closed_pr_count* and *closed_issue_count* are the total numbers of PRs /
    Issues that were closed in any scanned repo yesterday.
    """
    day_start, day_end = _get_yesterday_range()
    has_repo_commit_or_pr_activity = False
    has_repo_issue_activity = False
    pr_actors: set = set()
    issue_actors: set = set()
    closed_pr_count = 0
    closed_issue_count = 0
    review_comment_count = 0
    merged_pr_count = 0
    star_count = 0
    fork_count = 0
    has_discussion = False
    has_wiki_edit = False
    branch_names: set = set()
    commit_repo_names: set = set()
    hourly_commits = defaultdict(int)
    commit_times = []
    has_bugfix_commit = False
    has_linux_related_commit = False
    has_external_review_on_user_pr = False
    has_ninja_event = False

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
            payload_action = event.get("payload", {}).get("action")
            if event_type in ("PushEvent", "PullRequestEvent"):
                has_repo_commit_or_pr_activity = True
                if event_type == "PushEvent":
                    payload = event.get("payload", {}) or {}
                    size = payload.get("size") or 0
                    if isinstance(size, int) and size > 0:
                        hourly_commits[event_time.hour] += size
                        # Record one timestamp per push event so gap calculations
                        # are based on push timing rather than duplicated zero-length gaps.
                        commit_times.append(event_time)
                    full_name_lower = (full_name or "").lower()
                    if any(k in full_name_lower for k in _LINUX_KEYWORDS):
                        has_linux_related_commit = True
                    commit_repo_names.add(full_name)
                    ref = payload.get("ref") or ""
                    if ref.startswith("refs/heads/"):
                        branch_names.add(ref.removeprefix("refs/heads/"))
                    if payload.get("forced"):
                        has_ninja_event = True
                    commits = payload.get("commits") or []
                    for c in commits:
                        if not isinstance(c, dict):
                            continue
                        msg = str(c.get("message") or "")
                        lowered = msg.lower()
                        if any(k in lowered for k in _BUGFIX_KEYWORDS):
                            has_bugfix_commit = True
                        if (
                            any(k in lowered for k in _LINUX_KEYWORDS)
                            or any(k in str(c.get("url") or "").lower() for k in _LINUX_KEYWORDS)
                        ):
                            has_linux_related_commit = True
                if event_type == "PullRequestEvent":
                    if payload_action == "opened" and actor_login and not _is_bot(actor_login):
                        pr_actors.add(actor_login)
                    elif payload_action == "closed":
                        closed_pr_count += 1
                        if event.get("payload", {}).get("pull_request", {}).get("merged"):
                            merged_pr_count += 1
            elif event_type == "IssuesEvent":
                has_repo_issue_activity = True
                if payload_action == "opened" and actor_login and not _is_bot(actor_login):
                    issue_actors.add(actor_login)
                elif payload_action == "closed":
                    closed_issue_count += 1
            elif event_type in ("PullRequestReviewCommentEvent", "PullRequestReviewEvent"):
                review_comment_count += 1
                pr_author = (
                    event.get("payload", {})
                    .get("pull_request", {})
                    .get("user", {})
                    .get("login", "")
                )
                if (
                    pr_author.lower() == GITHUB_USER.lower()
                    and actor_login
                    and actor_login.lower() != GITHUB_USER.lower()
                    and not _is_bot(actor_login)
                ):
                    has_external_review_on_user_pr = True
            elif event_type == "WatchEvent" and payload_action == "started":
                star_count += 1
            elif event_type == "ForkEvent":
                fork_count += 1
            elif event_type in ("DiscussionEvent", "DiscussionCommentEvent"):
                has_discussion = True
            elif event_type == "GollumEvent":
                has_wiki_edit = True
            elif event_type == "DeleteEvent":
                has_ninja_event = True

    total_commits = sum(hourly_commits.values())
    sorted_times = sorted(commit_times)
    avg_gap_minutes = None
    if len(sorted_times) >= 2:
        gaps = [
            (sorted_times[i] - sorted_times[i - 1]).total_seconds()
            for i in range(1, len(sorted_times))
        ]
        if gaps:
            avg_gap_minutes = (sum(gaps) / len(gaps)) / 60
    burst_hourly = max(hourly_commits.values()) if hourly_commits else 0

    return {
        "has_commit_or_pr": has_repo_commit_or_pr_activity,
        "has_issue": has_repo_issue_activity,
        "pr_actors": pr_actors,
        "issue_actors": issue_actors,
        "closed_pr_count": closed_pr_count,
        "closed_issue_count": closed_issue_count,
        "review_comment_count": review_comment_count,
        "merged_pr_count": merged_pr_count,
        "star_count": star_count,
        "fork_count": fork_count,
        "has_discussion": has_discussion,
        "has_wiki_edit": has_wiki_edit,
        "branch_count": len(branch_names),
        "commit_repo_names": commit_repo_names,
        "hourly_commits": dict(hourly_commits),
        "has_bugfix_commit": has_bugfix_commit,
        "has_linux_related_commit": has_linux_related_commit,
        "has_external_review_on_user_pr": has_external_review_on_user_pr,
        "avg_gap_minutes": avg_gap_minutes,
        "total_commits_from_events": total_commits,
        "burst_hourly": burst_hourly,
        "has_ninja_event": has_ninja_event,
    }


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
    """Resolve cat expression and status message.

    Thresholds are intentionally wide so that every state is reachable even
    when commit velocity is high (e.g. with AI-assisted development):

    * 0          → sleepy / idle
    * 1 – 8      → happy / light
    * 9 – 20     → focused
    * 21 – 40    → heavy
    * 41+        → ultra
    """
    if today is None:
        today = datetime.now(BJT).date()

    if commit_count == 0:
        cats = _CATS_IDLE
        expression = "sleepy"
    elif commit_count <= 8:
        cats = _CATS_LIGHT
        expression = "happy"
    elif commit_count <= 20:
        cats = _CATS_FOCUS
        expression = "focused"
    elif commit_count <= 40:
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


def _get_commit_streak_and_week_total(today=None):
    """Estimate streak days (ending yesterday) and this-week commit total."""
    if today is None:
        today = datetime.now(BJT).date()
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            # Use `today` as the upper bound so results are deterministic when
            # called with an explicit date (e.g., backfills or tests).
            today_dt = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=BJT)
            # Fetch up to 366 days so the streak is correct for long streaks.
            from_str = (today_dt - timedelta(days=366)).isoformat()
            to_str = today_dt.isoformat()
            query = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""
            payload = json.dumps({
                "query": query,
                "variables": {"login": GITHUB_USER, "from": from_str, "to": to_str},
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            day_counts = {}
            weeks = (
                data.get("data", {})
                .get("user", {})
                .get("contributionsCollection", {})
                .get("contributionCalendar", {})
                .get("weeks", [])
            )
            for week in weeks:
                for d in week.get("contributionDays", []):
                    day_counts[d.get("date")] = int(d.get("contributionCount", 0) or 0)
            streak = 0
            cursor = today - timedelta(days=1)
            while day_counts.get(cursor.isoformat(), 0) > 0:
                streak += 1
                cursor -= timedelta(days=1)
            week_start = today - timedelta(days=today.weekday())
            week_total = 0
            cursor = week_start
            while cursor <= today:
                week_total += day_counts.get(cursor.isoformat(), 0)
                cursor += timedelta(days=1)
            return streak, week_total
        except Exception as exc:
            print(f"⚠️  Streak query failed: {exc}")
    return 0, 0


def _get_total_commit_contributions():
    """Return all-time commit contributions when token is available."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return 0
    try:
        profile_query = """
query($login: String!) {
  user(login: $login) {
    createdAt
  }
}
"""
        profile_payload = json.dumps({
            "query": profile_query,
            "variables": {"login": GITHUB_USER},
        }).encode()
        profile_req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=profile_payload,
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(profile_req, timeout=15) as resp:
            profile_data = json.loads(resp.read())
        created_at = profile_data["data"]["user"]["createdAt"]
        now_utc = datetime.now(timezone.utc).isoformat()

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
                "from": created_at,
                "to": now_utc,
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        cc = data["data"]["user"]["contributionsCollection"]
        return (cc.get("totalCommitContributions", 0) + cc.get("restrictedContributionsCount", 0))
    except Exception as exc:
        print(f"⚠️  Total commit query failed: {exc}")
        return 0


def _is_prime(n):
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    upper = int(math.sqrt(n)) + 1
    for i in range(3, upper, 2):
        if n % i == 0:
            return False
    return True


def _render_progress_bar(value, goal, width):
    """Render a fixed-width unicode progress bar.

    ``goal`` values <= 0 are coerced to 1, and negative ``value`` is clamped
    to 0 via ratio clamping, to keep rendering safe.
    """
    if goal <= 0:
        goal = 1
    # Clamp into [0.0, 1.0] so the bar never overflows its fixed width.
    ratio = max(0.0, min(1.0, value / goal))
    filled = int(round(ratio * width))
    return f"{'█' * filled}{'░' * (width - filled)}"


def _render_streak_paw_dots(streak):
    """Render day-by-day paw dots with overflow suffix."""
    if streak <= 0:
        return "·"
    displayed_dots = min(streak, _STREAK_PAW_MAX_DOTS)
    suffix = f"+{streak - displayed_dots}" if streak > displayed_dots else ""
    return f"{'•' * displayed_dots}{suffix}"


def _resolve_main_cat_overlays(commit_count, today, activity, repos):
    streak, week_total = _get_commit_streak_and_week_total(today=today)
    hat = ""
    if streak >= 30:
        hat = "👑"
    elif streak >= 7:
        hat = "🎩"
    elif streak >= 3:
        hat = "🧢"

    hourly = activity.get("hourly_commits", {})
    late_night = sum(v for h, v in hourly.items() if int(h) in _LATE_NIGHT_HOURS)
    day_sum = sum(v for h, v in hourly.items() if int(h) in _DAYTIME_HOURS)

    lang_priority = ("Python", "LabVIEW", "Go", "Rust")
    language_to_item = {
        "Python": "🐍",
        "LabVIEW": "🔌",
        "Go": "🐹",
        "Rust": "🦀",
    }
    repo_map = {r.get("full_name"): r for r in repos if r.get("full_name")}
    language_counter = defaultdict(int)
    for name in activity.get("commit_repo_names", set()):
        lang = repo_map.get(name, {}).get("language")
        if lang:
            language_counter[lang] += 1
    hand_item = ""
    for lang in lang_priority:
        if language_counter.get(lang, 0) > 0:
            hand_item = language_to_item[lang]
            break
    # Fallback: if no priority-language matched, use the most-committed language name
    if not hand_item and language_counter:
        hand_item = max(language_counter, key=language_counter.get)

    total = sum(hourly.values())
    avg_hour = total / 24 if total else 0
    max_hour = activity.get("burst_hourly", 0)
    if total == 0:
        weather = "☁️"
    elif max_hour >= 10:
        weather = "⛈️"
    # 2.5 is a "burst factor": max hour within 2.5x of average => stable output.
    elif avg_hour and (max_hour / avg_hour) <= 2.5:
        weather = "☀️"
    else:
        weather = "☀️"

    outfit = _SPECIAL_DAY_OUTFITS.get(today.strftime("%m-%d"))
    total_commits = _get_total_commit_contributions()
    easter = {
        "birthday_cake_cat": False,
        "milestone_cat": False,
        "midnight_cat": bool(late_night > 0),
        "ninja_cat": bool(activity.get("has_ninja_event")),
        "party_cat": bool(activity.get("merged_pr_count", 0) >= 2),
        "ghost_cat": (
            random.Random(today.toordinal() + _GHOST_CAT_SEED_OFFSET).random()
            < _GHOST_CAT_PROBABILITY
        ),
        "alien_cat": _is_prime(commit_count),
    }

    profile = github_api(f"https://api.github.com/users/{GITHUB_USER}")
    created_at = profile.get("created_at", "")
    if created_at:
        created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(BJT).date()
        easter["birthday_cake_cat"] = (created_date.month, created_date.day) == (today.month, today.day)
    if total_commits >= 100 and total_commits % 100 == 0:
        easter["milestone_cat"] = True

    # Eye accessories: explicit priority — alien > sleep-deprived > sunglasses
    if easter["alien_cat"]:
        eye_override = "( 👽 )"
    elif late_night > 0:
        eye_override = "( 👀 )"
    elif day_sum >= max(1, commit_count // 2):
        eye_override = "( 😎 )"
    else:
        eye_override = None

    return {
        "streak": streak,
        "streak_dots": _render_streak_paw_dots(streak),
        "week_total": week_total,
        "week_goal": _WEEKLY_COMMIT_GOAL,
        "week_bar": _render_progress_bar(
            week_total, _WEEKLY_COMMIT_GOAL, _WEEKLY_PROGRESS_WIDTH
        ),
        "hat": hat,
        "eye_override": eye_override,
        "hand_item": hand_item,
        "weather": weather,
        "outfit": outfit,
        "easter": easter,
        "total_commits": total_commits,
        "late_night_commits": late_night,
    }


def generate_cat_section(
    commit_count,
    activity=None,
    repos=None,
    today=None,
):
    """Build the ASCII cat block + status line for the given commit count.

    HTML comments are appended below the status line so the raw source
    carries useful context without affecting the rendered markdown.
    """
    activity = activity or {}
    repos = repos or []
    if today is None:
        today = datetime.now(BJT).date()
    expression, msg = _resolve_cat_state(commit_count, today)
    overlays = _resolve_main_cat_overlays(commit_count, today, activity, repos)
    cats = [
        _cat_ascii(
            expression,
            today=today,
            eye_override=overlays["eye_override"],
            hat=overlays["hat"],
            hand_item=overlays["hand_item"],
            outfit=overlays["outfit"],
            aura="🎂" if overlays["easter"]["birthday_cake_cat"] else None,
        )
    ]
    role_flags = {
        "review_cat": activity.get("review_comment_count", 0) > 0,
        "merge_cat": activity.get("merged_pr_count", 0) > 0,
        "star_cat": activity.get("star_count", 0) > 0,
        "fork_cat": activity.get("fork_count", 0) > 0,
        "discussion_cat": activity.get("has_discussion", False),
        "wiki_cat": activity.get("has_wiki_edit", False),
    }
    for key, _name, item, _desc, face in _EXTRA_CAT_ROLES:
        if role_flags.get(key):
            cats.append(_mini_ascii_cat(item=item, face=face))
    animal_flags = {
        "mouse": activity.get("has_bugfix_commit", False),
        "penguin": activity.get("has_linux_related_commit", False),
        "octopus": activity.get("branch_count", 0) >= 2,
        "fox": activity.get("has_external_review_on_user_pr", False),
        "bee": bool(
            commit_count >= 10
            and activity.get("avg_gap_minutes") is not None
            and activity.get("avg_gap_minutes") < 30
        ),
    }
    # Non-cat animals are collected separately and shown as text lines below cats.
    animal_lines = []
    for key, symbol, bubble in _ANIMAL_ROLES:
        if animal_flags.get(key):
            animal_lines.append(_mini_ascii_animal(symbol, bubble))

    easter = overlays["easter"]
    total_commits = overlays["total_commits"]
    if easter["milestone_cat"]:
        cats.append(_mini_ascii_cat(
            item="[★]", face="(★.★)",
            hint=f"({total_commits} commits)",
        ))
    if easter["party_cat"]:
        cats.append(_mini_ascii_cat(item="🎉", face="( ^.^ )", hint="(已 merge)"))
    if easter["ghost_cat"]:
        cats.append(_mini_ascii_cat(item="👻", face="( ._. )", hint="(罕见彩蛋)"))

    # Keep the main cat and limit companion mini-cats to avoid crowding.
    cats = [cats[0]] + cats[1:_MAX_EXTRA_ROLE_CATS + 1]

    cat_ascii_art = _cats_side_by_side(cats)
    pre_lines = [cat_ascii_art]
    if animal_lines:
        pre_lines.extend(animal_lines)

    # Build the status lines: commit status + optional closed-PR/Issue summary
    status_parts = [msg]
    close_parts = []
    if activity.get("closed_pr_count", 0) > 0:
        close_parts.append(f"{activity.get('closed_pr_count', 0)} 个 PR")
    if activity.get("closed_issue_count", 0) > 0:
        close_parts.append(f"{activity.get('closed_issue_count', 0)} 个 Issue")
    if close_parts:
        status_parts.append(f"📌 关闭了 {'、'.join(close_parts)}")
    status_parts.append(
        f"🧩 连续提交 {overlays['streak']} 天 | 活跃节奏 {overlays['weather']}"
    )
    status_parts.append(f"📅 日历爪印: {overlays['streak_dots']}")
    status_parts.append(
        f"📊 本周提交 [{overlays['week_bar']}] {overlays['week_total']}/{overlays['week_goal']}"
    )
    status_block = "\n".join(status_parts)
    pre_content = "\n".join(pre_lines + ["", status_block])
    cat_html = f'<pre style="{_PRE_STYLE}">\n{pre_content}\n</pre>'

    # Build an HTML comment block with machine-readable context that is
    # invisible in rendered markdown but visible when reading the source.
    pr_actors = activity.get("pr_actors", set())
    issue_actors = activity.get("issue_actors", set())
    pr_names = ", ".join(sorted(pr_actors)) if pr_actors else "无"
    issue_names = ", ".join(sorted(issue_actors)) if issue_actors else "无"
    role_meta = ", ".join([f"{k}={str(v).lower()}" for k, v in sorted(role_flags.items())])
    animal_meta = ", ".join([f"{k}={str(v).lower()}" for k, v in sorted(animal_flags.items())])
    easter_meta = ", ".join([f"{k}={str(v).lower()}" for k, v in sorted(easter.items())])
    yesterday_str = (today - timedelta(days=1)).isoformat()
    comment = (
        f"<!-- Yesterday Stats (昨日数据统计): date={yesterday_str}, commits={commit_count}"
        f", closed PRs={activity.get('closed_pr_count', 0)}"
        f", closed issues={activity.get('closed_issue_count', 0)}"
        f", PR authors (PR提交者)={pr_names}"
        f", issue authors (issue提交者)={issue_names}"
        f", hourly={json.dumps(activity.get('hourly_commits', {}), ensure_ascii=False, sort_keys=True)}"
        f", streak={overlays['streak']}, hat={overlays['hat'] or '无'}"
        f", streakPaw={overlays['streak_dots']}"
        f", week={overlays['week_total']}/{overlays['week_goal']}"
        f", weekBar={overlays['week_bar']}"
        f", hand={overlays['hand_item'] or '空手'}, rhythm={overlays['weather']}"
        f", roleFlags=[{role_meta}]"
        f", animalFlags=[{animal_meta}]"
        f", easter=[{easter_meta}]"
        " -->"
    )

    return f"{cat_html}\n{comment}"


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


# Candidate field names used by vipm.io for publisher aggregate stats (module-level to avoid per-call allocation)
_VIPM_COUNT_KEYS   = ("package_count", "total_packages", "num_packages", "packages_count")
_VIPM_INSTALL_KEYS = ("total_installs", "total_install_count", "install_count", "installs")
_VIPM_STAR_KEYS    = ("total_stars", "total_star_count", "star_count", "stars")


def _extract_publisher_stats_from_json(data, depth=0):
    """Search parsed JSON for publisher-level aggregate stats.

    Returns a dict with keys ``pkg_count``, ``total_installs``, ``total_stars``
    when found, otherwise an empty dict.
    """
    if depth > _VIPM_JSON_MAX_DEPTH:
        return {}
    if not isinstance(data, dict):
        return {}

    pkg_val     = next((data[k] for k in _VIPM_COUNT_KEYS   if k in data and isinstance(data[k], int)), None)
    install_val = next((data[k] for k in _VIPM_INSTALL_KEYS if k in data and isinstance(data[k], int)), None)
    star_val    = next((data[k] for k in _VIPM_STAR_KEYS    if k in data and isinstance(data[k], int)), None)

    if pkg_val and install_val:
        return {
            "pkg_count": pkg_val,
            "total_installs": install_val,
            "total_stars": star_val or 0,
        }

    for val in data.values():
        if isinstance(val, (dict, list)):
            sub = _extract_publisher_stats_from_json(val, depth + 1)
            if sub:
                return sub
    return {}


def _synth_packages(pkg_count, total_installs, total_stars):
    """Return a synthesised package list representing the given totals."""
    per_i, rem_i = divmod(total_installs, pkg_count)
    per_s, rem_s = divmod(total_stars, pkg_count)
    return [
        {
            "name": f"package-{i}",
            "installs": per_i + (1 if i < rem_i else 0),
            "stars": per_s + (1 if i < rem_s else 0),
        }
        for i in range(pkg_count)
    ]


def get_vipm_packages():
    """Fetch package stats from the VIPM publisher page.

    Returns a list of dicts with keys ``name``, ``installs``, ``stars``.
    Returns an empty list on any failure so the caller can skip the section.

    Parse strategies (tried in order):
    1. ``__NEXT_DATA__`` JSON (Next.js) — individual package objects
    2. ``__NEXT_DATA__`` JSON — publisher-level aggregate fields
    3. Any ``<script>`` block containing ``install_count`` / ``installs``
    4. HTML text pattern scan: looks for "N packages", "N installs", "N stars"
       as they appear in the visible page text.
    5. HTML attribute heuristic (legacy fallback).
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

    # Strategy 1 & 2: __NEXT_DATA__ JSON embedded by Next.js
    next_data_match = re.search(
        r'(?i)<script\s+id="__NEXT_DATA__"\s+type="application/json"\s*>([\s\S]*?)</script>',
        html,
    )
    if next_data_match:
        try:
            next_json = json.loads(next_data_match.group(1))
            # Strategy 1: individual package list
            pkgs = _extract_packages_from_json(next_json)
            if pkgs:
                print(f"ℹ️  VIPM: found {len(pkgs)} packages via __NEXT_DATA__ (package list)")
                return pkgs
            # Strategy 2: publisher-level aggregate stats
            agg = _extract_publisher_stats_from_json(next_json)
            if agg and agg["pkg_count"] > 0:
                print(
                    f"ℹ️  VIPM: found aggregate stats via __NEXT_DATA__: "
                    f"{agg['pkg_count']} pkgs, {agg['total_installs']} installs, "
                    f"{agg['total_stars']} stars"
                )
                return _synth_packages(agg["pkg_count"], agg["total_installs"], agg["total_stars"])
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: any <script> block mentioning install_count
    for script_match in re.finditer(r"(?i)<script[^>]*>([\s\S]*?)</script>", html):
        body = script_match.group(1)
        if '"install_count"' not in body and '"installs"' not in body:
            continue
        for json_match in re.finditer(r"(\[{[\s\S]*?}\])", body):
            try:
                pkgs = _extract_packages_from_json(json.loads(json_match.group(1)))
                if pkgs:
                    print(f"ℹ️  VIPM: found {len(pkgs)} packages via script scan")
                    return pkgs
            except (json.JSONDecodeError, ValueError):
                pass

    # Strategy 4: plain-text pattern scan on the visible HTML content.
    # Strip tags to get a rough text rendering and search for patterns like:
    #   "16 packages", "34,571 installs", "69 stars"
    plain_text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace so multi-line patterns match easily
    plain_text = re.sub(r"\s+", " ", plain_text)

    pkg_text_m     = re.search(r"(\d[\d,]*)\s+packages?",  plain_text, re.IGNORECASE)
    install_text_m = re.search(r"(\d[\d,]*)\s+installs?",  plain_text, re.IGNORECASE)
    star_text_m    = re.search(r"(\d[\d,]*)\s+stars?",     plain_text, re.IGNORECASE)

    if pkg_text_m and install_text_m:
        pkg_count_t     = int(pkg_text_m.group(1).replace(",", ""))
        total_installs_t = int(install_text_m.group(1).replace(",", ""))
        total_stars_t    = int(star_text_m.group(1).replace(",", "")) if star_text_m else 0
        if pkg_count_t > 0:
            print(
                f"ℹ️  VIPM: found via text scan — {pkg_count_t} packages, "
                f"{total_installs_t} installs, {total_stars_t} stars"
            )
            return _synth_packages(pkg_count_t, total_installs_t, total_stars_t)

    print("⚠️  VIPM: could not parse package data from page")
    # Strategy 5: HTML attribute / data-* heuristic (legacy last-resort)
    install_match = re.search(
        r'(?:data-install[_-]count|install[_-]count|installs)["\s:=]+([0-9,]+)',
        html, re.IGNORECASE,
    )
    star_match = re.search(
        r'(?:data-star[_-]count|star[_-]count|stars)["\s:=]+([0-9,]+)',
        html, re.IGNORECASE,
    )
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
        return _synth_packages(pkg_count, total_installs, total_stars)

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

    When *packages* is non-empty (fetch succeeded), a hidden HTML comment
    ``<!-- vipm-last-update: YYYY-MM-DD -->`` is appended so that subsequent
    runs (including manual triggers) can detect same-day re-runs and avoid
    showing misleading near-zero deltas.  The date comment is intentionally
    omitted when *packages* is empty so that a later same-day successful run
    is not incorrectly treated as a re-run.

    Example output:
      > 🔧 LabVIEW 开发者：[VIPM](https://www.vipm.io/publisher/nevstop/): \
          16 packages, 34,469 installs, 69 stars，今日新增 installs: +123；Stars: +5
    """
    if not packages:
        return f"> 🔧 LabVIEW 开发者：[VIPM]({VIPM_URL})"

    total_pkgs = len(packages)
    total_installs = sum(p["installs"] for p in packages)
    total_stars = sum(p["stars"] for p in packages)

    body = (
        f"> 🔧 LabVIEW 开发者：[VIPM]({VIPM_URL}): "
        f"{total_pkgs} packages, {total_installs:,} installs, {total_stars:,} stars"
    )

    # Append delta only when we have a previous reading
    if old_installs > 0 or old_stars > 0:
        delta_i = total_installs - old_installs
        delta_s = total_stars - old_stars
        sign_i = "+" if delta_i >= 0 else ""
        sign_s = "+" if delta_s >= 0 else ""
        body += f"，今日新增 installs: {sign_i}{delta_i:,}；Stars: {sign_s}{delta_s}"

    today_str = datetime.now(BJT).strftime("%Y-%m-%d")
    return f"{body}\n<!-- vipm-last-update: {today_str} -->"


def _parse_vipm_last_date(readme_content):
    """Extract the date stored in the hidden vipm-last-update comment.

    Returns a date string (``YYYY-MM-DD``) or ``None`` when not present.
    """
    match = re.search(
        r"<!-- VIPM_INLINE_START -->[\s\S]*?<!-- vipm-last-update: (\d{4}-\d{2}-\d{2}) -->",
        readme_content,
    )
    return match.group(1) if match else None


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
    """Update the stats sections of README.md (LANG_STATS, VIPM_INLINE, UPDATE_TIME).

    The CAT section is now maintained by ``scripts/update_cat.py``.

    When this script is triggered manually on the same calendar day it already
    ran, the VIPM delta ("今日新增") is suppressed to avoid showing a
    misleading near-zero change.  The stored ``vipm-last-update`` date
    (written as a hidden HTML comment by ``generate_vipm_inline_line`` only on
    successful VIPM fetches) is used to detect such same-day re-runs.
    """
    repos = get_owned_repos()
    language_totals = get_language_totals(repos)
    vipm_packages = get_vipm_packages()
    now_bjt = datetime.now(BJT)
    today = now_bjt.date()

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Detect same-day re-runs: if the stored VIPM date is today or later, the
    # delta would reflect only an intra-day change and would be misleading.
    old_vipm_date = _parse_vipm_last_date(content)
    is_vipm_rerun = old_vipm_date is not None and old_vipm_date >= today.isoformat()
    if is_vipm_rerun:
        print(f"ℹ️  VIPM already updated for today ({old_vipm_date}) — skipping delta")

    # Update inline VIPM stats (read old totals first for delta, then overwrite)
    old_installs, old_stars = _parse_vipm_inline_totals(content)
    vipm_line = generate_vipm_inline_line(
        vipm_packages,
        0 if is_vipm_rerun else old_installs,
        0 if is_vipm_rerun else old_stars,
    )
    content = replace_section(content, "VIPM_INLINE", vipm_line)

    # Update Most Used Language stats
    content = replace_section(content, "LANG_STATS", generate_language_stats_section(language_totals))

    # Update timestamp
    now_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M (北京时间)")
    content = replace_section(content, "UPDATE_TIME", f"🕐 最近更新: {now_str}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(
        f"✅ README stats updated — "
        f"{len(repos)} owned repos scanned, "
        f"{len(vipm_packages)} VIPM packages"
    )


if __name__ == "__main__":
    main()
