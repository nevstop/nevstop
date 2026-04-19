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

# Beijing Time (UTC+8)
BJT = timezone(timedelta(hours=8))

# ── ASCII Cat Art ───────────────────────────────────────────────────────────
# Each entry: (face_line, status_message_template)
# {n} in status will be replaced with the commit count.
# The face_line goes into the <pre> block (ASCII-only, no emoji / CJK).
# The status message is rendered outside the <pre> block as normal text.

_CATS_IDLE = [
    ("( -.- )  zzzZ", "💤 摸鱼模式 | 昨天没有提交代码哦~"),
    ("( =.= )  ....", "💤 摸鱼模式 | 进入低功耗模式~"),
    ("( u.u )  ~~~",  "😴 摸鱼模式 | 悄悄打了个盹~"),
    ("( -.o )  Zzz",  "💤 摸鱼模式 | 半梦半醒中~"),
    ("( ~.~ )  zZ",   "🌙 摸鱼模式 | 与星星作伴中~"),
    ("( T_T )  ...",  "😢 摸鱼模式 | 今天没有产出..."),
]

_CATS_LIGHT = [
    ("( ^.^ )  ~  ",  "🌱 轻松模式 | 昨天提交了 {n} 个 commit"),
    ("( o.o )  ?  ",  "🤔 好奇模式 | 昨天提交了 {n} 个 commit"),
    ("( >.o )     ",  "😌 稳健模式 | 昨天提交了 {n} 个 commit"),
    ("( *_* )  !  ",  "✨ 活力模式 | 昨天提交了 {n} 个 commit"),
    ("( ^_^ )  :) ",  "😊 开心模式 | 昨天提交了 {n} 个 commit"),
    ("( o_o )  >> ",  "👀 认真模式 | 昨天提交了 {n} 个 commit"),
]

_CATS_FOCUS = [
    ("( o_o )  ** ",  "💻 专注模式 | 昨天提交了 {n} 个 commit"),
    ("( >_< )  !! ",  "🎯 冲刺模式 | 昨天提交了 {n} 个 commit"),
    ("( *_* )  ** ",  "🌟 高效模式 | 昨天提交了 {n} 个 commit"),
    ("( >_> )     ",  "👊 干劲模式 | 昨天提交了 {n} 个 commit"),
    ("( 0_0 )  >> ",  "🔍 钻研模式 | 昨天提交了 {n} 个 commit"),
    ("( ^_^ )  !  ",  "😎 自信模式 | 昨天提交了 {n} 个 commit"),
]

_CATS_HEAVY = [
    ("( @_@ )  !!!",  "🔥 疯狂加班 | 昨天提交了 {n} 个 commit！"),
    ("( O_O )  !! ",  "😱 震撼模式 | 昨天提交了 {n} 个 commit！"),
    ("( x_x )  +  ",  "💥 超载模式 | 昨天提交了 {n} 个 commit！"),
    ("( >_< )     ",  "😤 爆发模式 | 昨天提交了 {n} 个 commit！"),
    ("( #_# )  ~~ ",  "🚀 飞速模式 | 昨天提交了 {n} 个 commit！"),
    ("( $_$ )  !! ",  "💰 黄金模式 | 昨天提交了 {n} 个 commit！"),
]

_CATS_ULTRA = [
    ("( @_@ ) !!!",   "🌋 传说级加班 | 昨天提交了 {n} 个 commit！！"),
    ("( ~_~ ) ...",   "🏆 超神模式 | 昨天提交了 {n} 个 commit！！"),
    ("( ^o^ ) !!!",   "🎆 疯狂模式 | 昨天提交了 {n} 个 commit！！"),
    ("( X_X )  ##",   "💀 极限模式 | 昨天提交了 {n} 个 commit！！"),
    ("( *_* ) ***",   "⚡ 闪电模式 | 昨天提交了 {n} 个 commit！！"),
    ("( 0_0 )  !!",   "🎯 传说级  | 昨天提交了 {n} 个 commit！！"),
]


_CAT_PRE_STYLE = (
    "display:inline-block;"
    "margin:0;"
    "text-align:left;"
    "font-family:'Cascadia Mono','Consolas','Menlo','Monaco',monospace;"
    "line-height:1.2;"
)


def _cat_body(face_line):
    """Return a 5-line ASCII cat body (no emoji, no CJK)."""
    return "\n".join([
        "    /\\_/\\",
        f"   {face_line}",
        "    > ^ <",
        "   /|   |\\",
        "  (_|   |_)",
    ])


def _pick_cat(cats, commit_count, today):
    """Pick a cat deterministically for the given day."""
    rng = random.Random(today.toordinal())
    face_line, msg_tpl = rng.choice(cats)
    body = _cat_body(face_line)
    msg = msg_tpl.format(n=commit_count)
    return body, msg


def _tiny_cat_sit():
    return "\n".join([
        " /\\_/\\",
        "( ^.^ )",
        " /|_|\\",
    ])


def _tiny_cat_phone():
    return "\n".join([
        " /\\_/\\",
        "( o.o )",
        " /|-|\\",
    ])


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
    """Convert GitHub timestamp to Beijing time."""
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
    """Check whether owned repos had commit/PR activity or issues yesterday."""
    day_start, day_end = _get_yesterday_range()
    has_commit_or_pr = False
    has_issue = False

    for repo in repos:
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
                break
            if event_time > day_end:
                continue

            if event_type in ("PushEvent", "PullRequestEvent"):
                has_commit_or_pr = True
            elif event_type == "IssuesEvent":
                has_issue = True

            if has_commit_or_pr and has_issue:
                return has_commit_or_pr, has_issue

    return has_commit_or_pr, has_issue


def get_language_totals(repos):
    """Return a dict mapping language names to aggregated byte counts."""
    totals = defaultdict(int)
    for repo in repos:
        full_name = repo.get("full_name")
        if not full_name:
            continue
        lang_data = github_api(f"https://api.github.com/repos/{full_name}/languages")
        if not isinstance(lang_data, dict):
            continue
        for lang, size in lang_data.items():
            if isinstance(size, int) and size > 0:
                totals[lang] += size
    return dict(totals)


# ── Section Generators ──────────────────────────────────────────────────────


def generate_cat_section(commit_count, has_commit_or_pr=False, has_issue=False, today=None):
    """Build the cat <pre> block + status line for the given commit count."""
    if today is None:
        today = datetime.now(BJT).date()

    if commit_count == 0:
        cats = _CATS_IDLE
    elif commit_count <= 3:
        cats = _CATS_LIGHT
    elif commit_count <= 8:
        cats = _CATS_FOCUS
    elif commit_count <= 15:
        cats = _CATS_HEAVY
    else:
        cats = _CATS_ULTRA

    body, msg = _pick_cat(cats, commit_count, today)
    blocks = [f'<pre style="{_CAT_PRE_STYLE}">\n{body}\n</pre>']

    if has_commit_or_pr:
        blocks.append(
            f'<div><pre style="{_CAT_PRE_STYLE}">\n{_tiny_cat_sit()}\n</pre>'
            "<sub>mini cat: commits/PR</sub></div>"
        )
    if has_issue:
        blocks.append(
            f'<div><pre style="{_CAT_PRE_STYLE}">\n{_tiny_cat_phone()}\n</pre>'
            "<sub>mini cat: issue call</sub></div>"
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
        return "Most Used Language 暂无可用数据（可能受到 API 限流影响）"

    total_bytes = sum(language_totals.values())
    top_langs = sorted(language_totals.items(), key=lambda x: x[1], reverse=True)[:MAX_LANGS_DISPLAY]
    max_name_len = max(len(name) for name, _ in top_langs)

    lines = ["Most Used Language (all owned repos)", ""]
    for lang, size in top_langs:
        ratio = size / total_bytes if total_bytes else 0
        filled = max(0, int(round(ratio * LANG_BAR_WIDTH)))
        bar = ("█" * filled).ljust(LANG_BAR_WIDTH, "░")
        lines.append(f"{lang.ljust(max_name_len)}  {bar}  {ratio * 100:5.1f}%")

    content = "\n".join(lines)
    return (
        '<pre style="display:inline-block;margin:0;text-align:left;'
        "font-family:'Cascadia Mono','Consolas','Menlo','Monaco',monospace;"
        f'line-height:1.2;">\n{content}\n</pre>'
    )


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
