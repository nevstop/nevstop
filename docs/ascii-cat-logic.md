# ASCII 小猫逻辑说明

本文描述 `scripts/update_readme.py` 中 CAT 区块的判定与渲染规则。

## 1. 主小猫（按 commit 数）

- `0`：sleepy（摸鱼）
- `1~8`：happy（轻松）
- `9~20`：focused（专注）
- `21~40`：intense（高压）
- `41+`：intense（超载）

并叠加以下动态效果：

- **帽子（streak）**
  - 连续 3 天：`🧢`
  - 连续 7 天：`🎩`
  - 连续 30 天：`👑`
- **眼睛（提交时段 / 特殊状态）**
  - 凌晨 02:00~05:00 有提交：`( 👀 )`
  - 白天为主：`( 😎 )`
  - 其他脚本判定的特殊状态：`( 👽 )`（提交数为质数）
- **手持物（当日提交仓库主语言）**
  - Python: `🐍`
  - LabVIEW: `🔌`
  - Go: `🐹`
  - Rust: `🦀`
- **背景天气（小时波动）**
  - 0 commit：`☁️`
  - 单小时 >= 10：`⛈️`
  - 其他：`☀️`
- **长期趋势**
  - 日历爪印：连续提交天数映射为 `•` 点阵（超长显示 `+N`）
  - 本周提交进度：固定宽度进度条 + `本周提交/目标值`

## 2. 多小猫角色（最多额外显示 5 只）

触发即加入同排显示，超过上限按添加顺序截断：

1. **Review猫** `🔍`：当天存在 `PullRequestReviewCommentEvent`/`PullRequestReviewEvent`
2. **Merge猫** `🚩`：当天有 merged PR
3. **Star猫** `⭐`：当天收到 `WatchEvent(started)`
4. **Fork猫** `🌿`：当天收到 `ForkEvent`
5. **讨论猫** `📢`：当天有 Discussion 事件
6. **Wiki猫** `📘`：当天有 `GollumEvent`

## 3. 非猫角色

- `🐭`：commit message 包含 `fix/bug/修复`
- `🐧`：仓库名或提交信息包含 `docker/linux/k8s/container`
- `🐙`：当天 push 到 >=2 个分支
- `🦊`：他人 review 了你的 PR
- `🐝`：提交 >=10 且平均间隔 <30 分钟

## 4. 彩蛋

- **生日蛋糕猫**：GitHub 账号创建周年（同月同日）
- **整数里程碑猫** `[★]`：总提交贡献数满足 `>=100` 且整百
- **午夜猫**：凌晨提交（主猫眼睛 `👀`）
- **忍者猫**：DeleteEvent 或 force push
- **派对猫**：当天 merged PR >=2（`🎉`）
- **幽灵猫**：按日期种子固定 1% 概率（`👻`）
- **外星猫**：当天 commit 数为质数（眼睛 `👽`）

## 5. 特殊日（节日服装）

可配置日期（`MM-DD`）：

- `01-01` 新年：`🎊`
- `04-01` 愚人节：`🤡`
- `12-25` 圣诞节：`🎅`

## 6. 隐藏判定数据（HTML 注释）

生成结果在 CAT 段落追加 `<!-- ... -->`，包含：

- commit / close PR / close issue
- PR/Issue 作者
- hourly 分布
- streak / hat / hand / weather
- roleFlags / animalFlags / easter

这些信息只存在于 Markdown 源码，不在页面渲染。

## 7. 样式总览

所有可能出现的小猫/角色样式展示见：

- `docs/ascii-cat-style-showcase.md`
