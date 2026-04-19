#!/usr/bin/env python3
"""Update README.md with dynamic content: cat status and language stats."""

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
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

MAX_EVENT_PAGES = 3       # pages of GitHub Events API to scan for commits
MAX_LANGS_DISPLAY = 8
LANG_BAR_WIDTH = 18
MAX_REPOS_FOR_ACTIVITY_SCAN = 60
MAX_REPOS_FOR_LANGUAGE_SCAN = 120

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


def _cat_svg(expression, width=180, mini=False, with_phone=False, aria_label="cat icon"):
    """Return an inline SVG cat.

    expression: one of "sleepy", "happy", "focused", "intense".
    width: rendered SVG width in px.
    mini: when True, uses thinner lines for companion cats.
    with_phone: when True, draws a small phone accessory.
    aria_label: accessibility label read by screen readers.
    Unknown expressions fall back to the "happy" style.
    """
    stroke_w = 3 if mini else 4
    happy_eyes = (
        '<circle cx="64" cy="44" r="3" fill="currentColor"/>'
        '<circle cx="96" cy="44" r="3" fill="currentColor"/>'
    )
    happy_mouth = '<path d="M72 58 Q80 66 88 58"/>'
    eye = {
        "sleepy": ('<line x1="60" y1="44" x2="68" y2="44"/>'
                   '<line x1="92" y1="44" x2="100" y2="44"/>'),
        "happy": happy_eyes,
        "focused": (
            happy_eyes
            + '<line x1="58" y1="36" x2="70" y2="34"/>'
            + '<line x1="90" y1="34" x2="102" y2="36"/>'
        ),
        "intense": ('<line x1="58" y1="42" x2="70" y2="46"/>'
                    '<line x1="90" y1="46" x2="102" y2="42"/>'),
    }.get(expression, happy_eyes)
    mouth = {
        "sleepy": '<path d="M74 58 Q80 62 86 58"/>',
        "happy": happy_mouth,
        "focused": '<line x1="76" y1="58" x2="84" y2="58"/>',
        "intense": '<path d="M72 60 Q80 54 88 60"/>',
    }.get(expression, happy_mouth)
    phone = (
        '<rect x="112" y="74" width="16" height="24" rx="2"/>'
        '<circle cx="120" cy="93" r="1.5" fill="currentColor"/>'
    ) if with_phone else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 120" width="{width}" '
        f'fill="none" stroke="currentColor" stroke-width="{stroke_w}" '
        f'stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="{aria_label}">\n'
        '<path d="M52 26 L66 12 L72 30"/>\n'
        '<path d="M88 30 L94 12 L108 26"/>\n'
        '<circle cx="80" cy="48" r="26"/>\n'
        f"{eye}\n{mouth}\n"
        '<path d="M80 70 L80 100"/>\n'
        '<path d="M60 84 Q80 96 100 84"/>\n'
        '<path d="M52 102 Q44 112 34 104 Q28 98 34 92"/>\n'
        '<path d="M68 104 L62 112"/>\n'
        '<path d="M92 104 L98 112"/>\n'
        f"{phone}\n</svg>"
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


def get_yesterday_commits():
    """Count the user's push-event commits from yesterday (Beijing time)."""
    day_start, day_end = _get_yesterday_range()

    commit_count = 0
    for page in range(1, MAX_EVENT_PAGES + 1):
        events = github_api(
            f"https://api.github.com/users/{GITHUB_USER}/events"
            f"?per_page=100&page={page}"
        )
        if not events:
            break
        for event in events:
            if event["type"] != "PushEvent":
                continue
            event_time = _to_bjt(event["created_at"])
            if day_start <= event_time <= day_end:
                commit_count += event.get("payload", {}).get("size", 0)
            elif event_time < day_start:
                return commit_count
    return commit_count


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
    """Return repo-wide (commit_or_pr_activity, issue_activity) flags for yesterday in BJT."""
    day_start, day_end = _get_yesterday_range()
    has_repo_commit_or_pr_activity = False
    has_repo_issue_activity = False

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

            if event_type in ("PushEvent", "PullRequestEvent"):
                has_repo_commit_or_pr_activity = True
            elif event_type == "IssuesEvent":
                has_repo_issue_activity = True

            if has_repo_commit_or_pr_activity and has_repo_issue_activity:
                return has_repo_commit_or_pr_activity, has_repo_issue_activity

    return has_repo_commit_or_pr_activity, has_repo_issue_activity


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


def generate_cat_section(commit_count, has_commit_or_pr=False, has_issue=False, today=None):
    """Build the cat SVG block + status line for the given commit count."""
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
    blocks = [
        f'<div>{_cat_svg(expression=expression, width=190, aria_label=f"main cat {expression} mood")}</div>'
    ]

    if has_commit_or_pr:
        blocks.append(
            '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;">'
            f'{_cat_svg(expression="happy", width=88, mini=True, aria_label="mini cat for repo pull request or commit activity")}'
            "<sub>mini cat: repo pull request/commit</sub></div>"
        )
    if has_issue:
        blocks.append(
            '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;">'
            f'{_cat_svg(expression="focused", width=88, mini=True, with_phone=True, aria_label="mini cat for repo issue activity")}'
            "<sub>mini cat: repo issue</sub></div>"
        )

    cat_html = (
        '<div style="display:flex;justify-content:center;align-items:flex-end;'
        'gap:12px;flex-wrap:wrap;">'
        + "".join(blocks)
        + "</div>"
    )
    return f"{cat_html}\n\n{msg}"


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
    commit_count = get_yesterday_commits()
    repos = get_owned_repos()
    has_commit_or_pr, has_issue = get_yesterday_repo_activity_flags(repos)
    language_totals = get_language_totals(repos)
    today = datetime.now(BJT).date()

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Update ASCII cat
    content = replace_section(
        content,
        "CAT",
        generate_cat_section(commit_count, has_commit_or_pr, has_issue, today),
    )

    # Update Most Used Language stats
    content = replace_section(content, "LANG_STATS", generate_language_stats_section(language_totals))

    # Update timestamp
    now_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M (北京时间)")
    content = replace_section(content, "UPDATE_TIME", f"🕐 最近更新: {now_str}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(
        f"✅ README updated — {commit_count} commits yesterday, "
        f"{len(repos)} owned repos scanned"
    )


if __name__ == "__main__":
    main()
