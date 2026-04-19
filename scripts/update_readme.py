#!/usr/bin/env python3
"""Update README.md with dynamic content: ASCII cat status and top starred repos."""

import json
import os
import random
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape as html_escape

GITHUB_USER = "nevstop"
GITHUB_ORGS = ["NEVSTOP-LAB"]
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

MAX_EVENT_PAGES = 3       # pages of GitHub Events API to scan for commits
MAX_DESC_LENGTH = 65      # max description chars in repo list; longer ones are truncated
_TRUNCATE_SUFFIX_LEN = 3  # length of "..." appended after truncation

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


def get_yesterday_commits():
    """Count the user's push-event commits from yesterday (Beijing time)."""
    now_bjt = datetime.now(BJT)
    yesterday = now_bjt - timedelta(days=1)
    day_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

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
            event_time = datetime.fromisoformat(
                event["created_at"].replace("Z", "+00:00")
            ).astimezone(BJT)
            if day_start <= event_time <= day_end:
                commit_count += event.get("payload", {}).get("size", 0)
            elif event_time < day_start:
                return commit_count
    return commit_count


# ── Top Repos ───────────────────────────────────────────────────────────────


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


def get_top_repos(n=5):
    """Return the top-N starred repos owned by the user or their orgs."""
    repos = _fetch_all_repos(
        f"https://api.github.com/users/{GITHUB_USER}/repos?type=owner"
    )
    for org in GITHUB_ORGS:
        repos.extend(
            _fetch_all_repos(f"https://api.github.com/orgs/{org}/repos")
        )

    # Filter out forks and the profile repo itself
    repos = [
        r
        for r in repos
        if not r.get("fork") and r["name"] != GITHUB_USER
    ]

    repos.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
    return repos[:n]


# ── Section Generators ──────────────────────────────────────────────────────


def generate_cat_section(commit_count, today=None):
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
    return f"<pre>\n{body}\n</pre>\n\n{msg}"


def generate_repos_section(repos):
    """Build a markdown list for the top repos."""
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    lines = []
    for i, r in enumerate(repos):
        full_name = html_escape(r["full_name"])
        url = html_escape(r["html_url"])
        stars = r.get("stargazers_count", 0)
        desc = r.get("description") or ""
        if len(desc) > MAX_DESC_LENGTH:
            desc = desc[:MAX_DESC_LENGTH - _TRUNCATE_SUFFIX_LEN] + "..."
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        line = f"{medal} **[{full_name}]({url})** ⭐ {stars}"
        if desc:
            line += f"  \n   {desc}"
        lines.append(line)
    return "\n\n".join(lines)


# ── README Updater ──────────────────────────────────────────────────────────


def replace_section(content, tag, replacement):
    """Replace content between <!-- TAG_START --> and <!-- TAG_END -->."""
    pattern = rf"(<!-- {tag}_START -->).*?(<!-- {tag}_END -->)"
    return re.sub(pattern, rf"\1\n{replacement}\n\2", content, flags=re.DOTALL)


def main():
    commit_count = get_yesterday_commits()
    today = datetime.now(BJT).date()

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Update ASCII cat
    content = replace_section(content, "CAT", generate_cat_section(commit_count, today))

    # Update timestamp
    now_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M (北京时间)")
    content = replace_section(content, "UPDATE_TIME", f"🕐 最近更新: {now_str}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ README updated — {commit_count} commits yesterday, top {len(top_repos)} repos refreshed")


if __name__ == "__main__":
    main()
