#!/usr/bin/env python3
"""Update README.md with dynamic content: ASCII cat status and top starred repos."""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape as html_escape

GITHUB_USER = "nevstop"
GITHUB_ORGS = ["NEVSTOP-LAB"]
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

# Beijing Time (UTC+8)
BJT = timezone(timedelta(hours=8))

# ── ASCII Cat Art ───────────────────────────────────────────────────────────

CAT_IDLE = r"""
    /\_/\
   ( -.- )  zzZ
    > ^ <
   /|   |\
  (_|   |_)
"""

CAT_FOCUS = r"""
    /\_/\
   ( •_• )  ✧
    > ^ <
   /|   |\
  (_|   |_)
"""

CAT_CRAZY = r"""
    /\_/\
   ( @_@ )  !!!
    > ^ <
   /|   |\
  (_|   |_)
"""


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
    for page in range(1, 4):  # up to 3 pages
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


def generate_cat_section(commit_count):
    """Build the <pre> block with the appropriate cat and status message."""
    if commit_count == 0:
        cat = CAT_IDLE
        msg = "💤 摸鱼模式 | 昨天没有提交代码哦~"
    elif commit_count <= 5:
        cat = CAT_FOCUS
        msg = f"💻 专注模式 | 昨天提交了 {commit_count} 个 commit"
    else:
        cat = CAT_CRAZY
        msg = f"🔥 疯狂加班 | 昨天提交了 {commit_count} 个 commit！"

    return f"<pre>\n{cat}\n{msg}\n</pre>"


def generate_repos_section(repos):
    """Build pin-card HTML for the top repos (2 per row)."""
    lines = []
    for i in range(0, len(repos), 2):
        row_parts = []
        for j in range(2):
            if i + j < len(repos):
                r = repos[i + j]
                owner = html_escape(r["full_name"].split("/")[0])
                name = html_escape(r["name"])
                url = html_escape(r["html_url"])
                card = (
                    f"https://github-readme-stats.vercel.app/api/pin/"
                    f"?username={owner}&repo={name}"
                    f"&theme=tokyonight&show_owner=true"
                )
                row_parts.append(
                    f'<a href="{url}">'
                    f'<img src="{card}" />'
                    f"</a>"
                )
        lines.append(" ".join(row_parts))
    return "\n".join(lines)


# ── README Updater ──────────────────────────────────────────────────────────


def replace_section(content, tag, replacement):
    """Replace content between <!-- TAG_START --> and <!-- TAG_END -->."""
    pattern = rf"(<!-- {tag}_START -->).*?(<!-- {tag}_END -->)"
    return re.sub(pattern, rf"\1\n{replacement}\n\2", content, flags=re.DOTALL)


def main():
    commit_count = get_yesterday_commits()
    top_repos = get_top_repos(5)

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Update ASCII cat
    content = replace_section(content, "CAT", generate_cat_section(commit_count))

    # Update top repos
    content = replace_section(content, "REPOS", generate_repos_section(top_repos))

    # Update timestamp
    now_str = datetime.now(BJT).strftime("%Y-%m-%d %H:%M (北京时间)")
    content = replace_section(content, "UPDATE_TIME", f"🕐 最近更新: {now_str}")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ README updated — {commit_count} commits yesterday, top {len(top_repos)} repos refreshed")


if __name__ == "__main__":
    main()
