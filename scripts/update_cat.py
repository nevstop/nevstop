#!/usr/bin/env python3
"""Update only the CAT section of README.md.

This script is intentionally separate from ``update_readme.py`` so that the
ASCII cat status can be refreshed on its own schedule (or manually) without
touching the language/VIPM stats.

Manual-trigger awareness
------------------------
The CAT HTML comment written to README.md includes a ``date=YYYY-MM-DD``
field that records which "yesterday" (Beijing time) the commit data
represents.  On each run this stored date is compared with the current
"yesterday in BJT":

* **Same date** → this is a same-day re-run (e.g. manual workflow_dispatch
  while the daily job already completed).  The commit count for a past day
  is immutable, so the update is idempotent and we simply re-render with
  fresh API data.  A log message is printed to make the re-run visible.

* **Different date** → a new day has started; fresh data is fetched and
  the section is updated normally.
"""

import re
import sys
import os
from datetime import datetime, timedelta

# When invoked as ``python scripts/update_cat.py`` Python automatically adds
# the ``scripts/`` directory to sys.path, so sibling modules are importable.
# The explicit insert below is a safety-net for edge-case invocations.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import update_readme as _base  # noqa: E402  (import after sys.path manipulation)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_cat_last_date(readme_content):
    """Extract the effective date stored in the CAT section HTML comment.

    Returns a ``YYYY-MM-DD`` string (the "yesterday" for which the current
    CAT block was generated) or ``None`` when not found (e.g. first run).
    """
    m = re.search(
        r"<!-- Yesterday Stats[^>]*?\bdate=(\d{4}-\d{2}-\d{2})\b",
        readme_content,
    )
    return m.group(1) if m else None


# ── Entry point ──────────────────────────────────────────────────────────────


def main():
    """Fetch yesterday's commit data and update the CAT section of README.md.

    Uses the date stored in the existing CAT HTML comment to detect same-day
    re-runs and log an informational message.  The update itself is always
    performed (the data is immutable for a past day) so the operation is
    idempotent.
    """
    now_bjt = datetime.now(_base.BJT)
    today = now_bjt.date()
    yesterday = (today - timedelta(days=1)).isoformat()

    with open(_base.README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    stored_date = _parse_cat_last_date(content)
    is_rerun = stored_date == yesterday
    if is_rerun:
        print(
            f"ℹ️  CAT section already covers {yesterday} — "
            "re-run detected, re-rendering with fresh API data"
        )
    else:
        if stored_date:
            print(f"ℹ️  CAT section was last updated for {stored_date}; new period: {yesterday}")
        else:
            print(f"ℹ️  No stored CAT date found — first run for {yesterday}")

    orgs = _base.get_target_orgs()
    commit_count = _base.get_yesterday_commits(orgs=orgs)
    repos = _base.get_owned_repos()
    activity = _base.get_yesterday_repo_activity_flags(repos)

    new_cat = _base.generate_cat_section(
        commit_count,
        activity=activity,
        repos=repos,
        today=today,
    )
    content = _base.replace_section(content, "CAT", new_cat)

    with open(_base.README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    status = "re-run" if is_rerun else "fresh"
    print(
        f"✅ CAT section updated ({status}) — "
        f"{commit_count} commits for {yesterday}"
    )


if __name__ == "__main__":
    main()
