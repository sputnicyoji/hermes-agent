---
name: ai-radar
description: "Daily/weekly digest of fresh AI news, new open-source repos, models, papers, and Twitter/X chatter — pulled from 6 sources, deduped against state, scored by an LLM, and pushed to DingTalk with follow-candidate suggestions. Use when the user asks for an AI-news rundown, when running the scheduled cron job for it, or when they want to review what just shipped in AI/LLM/open-source/research today or this week."
version: 0.1.0
author: Hermes Agent (Yoji)
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  commands: [twitter, curl]
  env: [TWITTER_AUTH_TOKEN, TWITTER_CT0]
  deps: [twitter-cli]
metadata:
  hermes:
    tags: [ai-news, radar, cron, twitter, github-trending, huggingface, arxiv, hackernews, digest]
    state_file: ~/.hermes/data/ai_radar_state.json
    delivery: dingtalk
---

# ai-radar — Multi-source AI digest for Hermes cron

Pulls fresh signal from 6 public sources, dedupes against persistent state, scores with an LLM, and ships a compact digest to DingTalk. Designed to run as a cron job (`5 9 * * 1-6` for daily, `10 9 * * 0` for weekly), but can be invoked manually too.

The digest answers two questions:
1. **What shipped in AI since last run?** — top 6-8 items across news, repos, models, papers
2. **Who should the user follow on X to keep up?** — 0-3 candidates with reasons; user confirms via DingTalk reply, not auto-followed

The skill never executes write actions (`twitter follow`, `twitter post`, etc.) on its own. See **Write authorization** below.

---

## When to use this skill

- The cron job triggers it automatically (daily 9:05, weekly Sunday 9:10)
- The user says: "跑一下 ai-radar", "今天 AI 圈有什么新东西", "本周 AI 周报", "看看新发的开源项目"
- The user wants to review what they missed: "我两天没看 X，summarize 一下"
- The user is deciding whether to follow someone: "@xxx 值得关注吗" (skill can pull recent posts to inform the answer)

The skill should NOT trigger for:
- Single-source queries ("最新 arxiv 论文" — use web_extract directly)
- Generic "AI 新闻" without a digest framing — Hermes' web_search handles ad-hoc questions cheaper

---

## Operational modes

| Mode | Triggered by | Time window | Output |
|------|--------------|-------------|--------|
| `daily` (default) | cron `5 9 * * 1-6`, or manual ask | last 24h since `state.last_run_iso` (or 36h if missed) | 6-8 items + ≤3 follow candidates |
| `weekly` | cron `10 9 * * 0`, or manual "周报" | last 7 days | 12-15 items + 5-sentence trend summary + ≤5 follow candidates |
| `catchup` | "我 N 天没看了" | last N days, custom | proportional |

Pass mode in the cron prompt or infer from user phrasing. When unsure, default to `daily`.

---

## Pipeline (high level)

```
1. fetch     — call all 6 sources in parallel where possible
2. dedupe    — drop items whose ID is in state.seen_*
3. score     — LLM rates each surviving item 0-10 on relevance + novelty + signal/noise
4. select    — keep top N by score, mode-dependent
5. derive    — build follow-candidate list from authors of high-score X items not yet followed
6. render    — produce DingTalk-friendly markdown
7. persist   — append new IDs to state.seen_*, FIFO-trim to 1000 each
8. deliver   — single message to ~/.hermes/cron/jobs.json's deliver target (handled by Hermes runtime)
```

If a source fails, log it inline in the digest footer ("📡 Sources: X✓ GitHub✓ HF✓ arxiv✗(timeout) HN✓") and continue. **Never block the whole run on one source.**

---

## Sources (with verified field shapes)

### 1. X home timeline (following feed)

```bash
twitter -c feed -t following -n 30 --json
```
**Note:** `-c` / `--compact` is a **global flag** on `twitter` and must precede the subcommand. Writing it after (`twitter feed --compact`) errors with `No such option: --compact`. Compact mode keeps `id`, `user`, `text`, `created_at`, basic metrics. Filter to items whose `created_at` is within the time window. Authors here are signal — they're already curated by the user.

### 2. X keyword search (broader signal)

Run a few searches, merge (note `-c` placement):
```bash
twitter -c search "open source LLM" --json -n 20
twitter -c search "model weights released" --json -n 20
twitter -c search "new agent framework" --json -n 20
```
Add or rotate queries based on what's hot. Searches return ranked by X's relevance (not strictly chronological). Filter by `created_at` to the time window.

**Rate-limit caution:** `twitter` enforces randomized client-side delays (1.5-4 s per write op; reads are not throttled client-side but X's server caps per cookie). Three search calls + one feed call per run is fine.

### 3. GitHub repositories (recently created, AI/ML topics)

**Important:** GitHub Search API does NOT accept `OR` between qualifiers (`topic:llm OR topic:agents` returns HTTP 422 "Validation Failed: Logical operators only apply to text, not to qualifiers"). Multiple topics must be queried separately and merged client-side.

```bash
# 7-day window catches genuinely new repos; tighter windows often return total:0
SINCE=$(date -u -d '7 days ago' +%Y-%m-%d)
for topic in llm agents agentic ai-agent; do
  curl -sS --ssl-revoke-best-effort \
    "https://api.github.com/search/repositories?q=topic:${topic}+created:>${SINCE}&sort=stars&order=desc&per_page=15"
done
# Smoke-test counts (7-day window): topic=llm:1383, topic=agents:269, topic=agentic:38
# Merge by html_url, keep highest stargazer_count when duplicated
```
**Why `created:` not `pushed:`:** `pushed:` matches any repo with a recent commit including 5-year-old projects; we want **new** projects. **Why 7-day window not 24h:** smoke testing showed 24h often returns `total: 0` because new repos take a day or two to gather topic tags. The dedupe state filters out repos already shown in past digests, so a wider window is safe.

Returns JSON with `items[]` containing `full_name`, `description`, `stargazers_count`, `pushed_at`, `created_at`, `topics`, `html_url`. Dedupe key: `html_url`.

Without auth: **60 req/h** — 4 topic calls × 1 cron run/day = 4 req/day, well under. If the user has `GITHUB_TOKEN` in `.env`, send `Authorization: Bearer $GITHUB_TOKEN` to lift to 5000/h.

Filter ideas:
- Drop items with no `description` (low-effort repos)
- Drop items where `stargazers_count` < 30 in `daily` mode (noise floor)
- Drop items whose `created_at` is older than the time window even if `pushed_at` is recent

### 4. HuggingFace newest models

**Reality check:** HF likes accumulate slowly — smoke testing showed `lastModified` past 200 entries had **0 models** with `likes>=10` in the AI tag set, even though 33 had AI tags. Newly published models almost never have likes within 24h. Filtering by likes for "today's new models" returns empty most days. Treat HF as a **secondary source** that mostly contributes named-org releases.

```bash
curl -sS --ssl-revoke-best-effort \
  "https://huggingface.co/api/models?sort=lastModified&direction=-1&limit=200&full=false"
```
Returns array of dicts: `id, author, downloads, likes, tags, library_name, lastModified, gated, private`. Dedupe key: `id`.

**Note:** `sort=trending` is **not** a valid API value (returns `Invalid sort parameter`); valid values are `lastModified`, `createdAt`, `downloads`, `likes`. Trending is a Web-UI concept only.

Filter strategy (two paths, take whichever produces hits):

**Path A — per-author watchlist (recommended, reliable):**

The single `lastModified` global feed is too noisy — known orgs publish too rarely to surface in 200 entries. Query each org separately:

```python
import json, subprocess, time
KNOWN_ORGS = [
    'meta-llama', 'google', 'mistralai', 'Qwen', 'deepseek-ai',
    'openai', 'anthropic', 'microsoft', 'nvidia', 'stabilityai',
    'black-forest-labs', 'unsloth', 'NousResearch', 'allenai',
    'apple', 'tencent', 'baidu', 'zai-org', 'moonshotai',
]
WANTED_TAGS = {'text-generation', 'image-text-to-text', 'text-to-image',
               'text-to-video', 'audio-to-text'}
hits = []
for org in KNOWN_ORGS:
    url = f'https://huggingface.co/api/models?author={org}&sort=lastModified&direction=-1&limit=5&full=false'
    r = subprocess.run(['curl', '-sS', '--ssl-revoke-best-effort', url],
                       capture_output=True, text=True)
    models = json.loads(r.stdout)
    hits.extend(m for m in models
                if any(t in WANTED_TAGS for t in m.get('tags', [])))
    time.sleep(0.2)  # gentle pacing — 18 orgs × 0.2s = ~4s total
hits.sort(key=lambda m: m['lastModified'], reverse=True)
# Now filter by time window for daily/weekly
```

Smoke testing confirms Path A reliably surfaces real releases (DeepSeek-V4-Pro, Gemma-4, Nemotron, FLUX.2 — all on the same day they shipped).

**Path B — likes threshold (catches indie hits, often empty):**
- Pull `?sort=lastModified&direction=-1&limit=200&full=false` once
- Filter: `likes >= 3` for `daily`, `>= 20` for `weekly`, plus tag filter
- Often empty for any single day; not load-bearing

Use both: Path A as the spine, Path B as bonus discovery. Combine results, dedupe by `id`.

### 5. arxiv newest cs.AI / cs.LG papers

**Important: returns Atom XML, not JSON.** Parse with stdlib.

```bash
# Pipe directly to Python — avoids the Windows /tmp path-split trap (Git Bash sees
# C:\Program Files\Git\tmp; Python sees C:\tmp), which breaks any "curl -o /tmp/x.xml"
# + "open('/tmp/x.xml')" pattern.
curl -sS --ssl-revoke-best-effort \
  "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&start=0&max_results=20&sortBy=submittedDate&sortOrder=descending" \
  | python -c "
import sys, xml.etree.ElementTree as ET
ns = {'atom': 'http://www.w3.org/2005/Atom'}
root = ET.fromstring(sys.stdin.read())
for entry in root.iterfind('atom:entry', ns):
    arxiv_id = entry.findtext('atom:id', namespaces=ns).rsplit('/', 1)[-1]  # '2605.04039v1'
    arxiv_id = arxiv_id.rsplit('v', 1)[0]  # strip version → '2605.04039'
    title = entry.findtext('atom:title', namespaces=ns).strip()
    summary = entry.findtext('atom:summary', namespaces=ns).strip()
    authors = [a.findtext('atom:name', namespaces=ns) for a in entry.iterfind('atom:author', namespaces=ns)]
    published = entry.findtext('atom:published', namespaces=ns)
    print(f'{arxiv_id}|{published}|{title}')
"
```

If you must persist the XML to disk (e.g., for retry logic), use a Windows-visible path that both Git Bash and Python agree on:
```bash
ARXIV_TMP="${HERMES_HOME:-$HOME/.hermes}/cache/arxiv_$(date +%s).xml"
mkdir -p "$(dirname "$ARXIV_TMP")"
curl ... -o "$ARXIV_TMP"
python -c "import xml.etree.ElementTree as ET; tree = ET.parse('$ARXIV_TMP'); ..."
```

Dedupe key: `arxiv_id` with version stripped (`2605.04039`). The arxiv API has a soft "1 request every 3 seconds" rule — single call per cron run is well within.

### 6. Hacker News (Algolia search backend)

```bash
# Past 24h, story tag, AI-related, points >= 50 (noise floor)
TS_24H=$(date -u -d '24 hours ago' +%s)
curl -sS --ssl-revoke-best-effort \
  "https://hn.algolia.com/api/v1/search?tags=story&query=AI&numericFilters=points>50,created_at_i>${TS_24H}&hitsPerPage=20"
```

Returns JSON: `hits[]` with `objectID`, `title`, `url`, `points`, `num_comments`, `author`, `created_at`. Dedupe key: `objectID`.

The Algolia endpoint is a Hacker News partner — public, no key, no rate-limit issues for our volume.

For `weekly`, raise threshold (`points>200`) to compensate for the wider window.

---

## State file

Path: `~/.hermes/data/ai_radar_state.json`. Create if missing on first run.

```json
{
  "schema_version": 1,
  "last_run_iso": "2026-05-06T09:05:00+08:00",
  "last_mode": "daily",
  "seen_tweet_ids": ["1234567890123456789", "..."],
  "seen_repo_urls": ["https://github.com/foo/bar", "..."],
  "seen_hf_model_ids": ["meta-llama/Llama-4-70B", "..."],
  "seen_arxiv_ids": ["2605.04039", "..."],
  "seen_hn_ids": ["48034650", "..."],
  "follow_candidates_history": [
    {"screen_name": "...", "first_suggested_at": "...", "times_suggested": 1, "user_action": null}
  ],
  "followed_log": [
    {"screen_name": "...", "at": "...", "reason": "..."}
  ],
  "seed_cache": {
    "NousResearch": {
      "fetched_at": "2026-05-06T09:05:00+08:00",
      "tweets": [{"id": "...", "created_at": "...", "text": "..."}]
    }
  }
}
```

**Why each field is here:**
- `last_run_iso` — used to compute the time window if cron missed a tick (gateway down, etc.)
- `seen_*` — FIFO lists, capped at **1000 entries** each, trim by removing the oldest. Prevents the file from growing unbounded.
- `follow_candidates_history` — so we don't re-suggest the same person every day. If `times_suggested >= 3` and `user_action == null`, drop them silently — user obviously didn't want to follow.
- `followed_log` — audit trail of writes the user authorized. Useful for "did I already follow @x" checks.
- `seed_cache` — TTL-based cache for X seed-account `user-posts` fetches (see "When X feed comes back too thin"). 18h TTL daily / 3d weekly. Cap each account's `tweets` list at 20 entries.

Read-modify-write atomically: read into memory → produce digest → append new IDs → trim → write to a `.tmp` file → rename. Don't lose state on partial failure.

---

## Scoring

Build a single LLM call to score all surviving candidates in one shot. Prompt skeleton:

```
You are scoring AI-related items for a daily/weekly digest. Rate each on:
- relevance (is this AI/LLM/ML/agents/open-source related?) 0-3
- novelty (is this materially new vs. boilerplate/incremental?) 0-3
- signal_to_noise (is the source/author known good? are metrics non-trivial?) 0-3
Return one JSON object per line: {"id": "<dedupe_key>", "total": <0-9>, "one_line": "<≤80 chars why this matters>"}.

Items:
[id=...][source=hn] points=120 comments=45 title="..."
[id=...][source=hf] likes=87 downloads=2400 model="..." tags=[...]
...
```

Use `deepseek-v4-pro` (the configured main model). One call ≈ 800 input + 400 output tokens for a 30-item batch ≈ $0.0003. Cheap.

Selection rules:
- `daily`: top 6-8 by score, **diversity constraint**: max 3 from any single source, max 2 from any single author
- `weekly`: top 12-15, same diversity constraint relaxed (max 5 / 3)

---

## Follow-candidate derivation

After scoring, look at the X items that scored ≥6. Their authors are candidates if:
1. Author is not already followed (check via `twitter following @${current_user} -n 200 --json --compact` cached for the day, or quietly skip this check and let the user catch dupes — calling the API every run is rate-limit waste)
2. Author isn't in `state.followed_log`
3. Author isn't in `state.follow_candidates_history` with `times_suggested >= 3`

Cap candidates: 3 for `daily`, 5 for `weekly`. Reason should be one-line concrete: "shipped Llama-4 inference benchmark today", not "tweets about AI a lot".

---

## Output format (DingTalk-friendly)

### Language

The digest body is written in **简体中文** by default (the user's primary language for Hermes/DingTalk).

Translation policy:
- **Titles**: paraphrase into 简体中文 if the original is English and a clean Chinese rendering exists (e.g. `Three Inverse Laws of AI` → `AI 三反定律`). Preserve专有名词原文 — model IDs (`Llama-4-70B`), repo names (`foo/bar`), framework names (`HyperFrames`, `agent harness`), benchmark names (`GDPval-AA`).
- **Keep as-is, never translate**: URLs, author handles (`@xxx`), numeric metrics (`▲6.3k`, `❤3.6k`, `★1.2k`).
- **Tweet quotes**: short direct quotes (≤20 words) keep original; longer text gets paraphrased.

Switch to English only if the cron prompt explicitly says `language=en` or the user asks for it in this turn.

### Layout rules (load-bearing for readability)

DingTalk renders raw text with newlines preserved. Each visible field is its own line. Compressing title + URL + comment into one line — as some chat models default to — destroys scannability. Follow the structure exactly:

- One blank line between numbered items
- Title on its own line
- URL on its own line (DingTalk auto-detects URLs and renders them clickable)
- Comment block (`↳ ...`) — see **Comment depth** below
- Section headers separated by **two** blank lines

### Comment depth (the `↳` block)

Each item's comment block is **2-4 lines, total ≤200 中文字符**. A single short line is too thin — readers can't tell why an item earned the slot. The block should answer:

1. **What** is this concretely? (one line; the headline rephrased with a key fact)
2. **Why does it matter?** (one line; impact / what it changes / who cares)
3. *Optional* **Numbers / specifics** that didn't fit in the title (one line; benchmarks, downloads, comparisons)
4. *Optional* **What to read first** (one line; if there's a specific section worth jumping to)

Format the block as continuation lines under `↳`:

```
3. [HN ▲456] AI 三反定律
   https://susam.net/inverse-laws-of-robotics.html
   ↳ 把阿西莫夫三定律反转套用到 AI：不伤害 → 不被使用、服从 → 不被关注、自保 → 不被替代
   ↳ 换框架重新审视当下 AI 安全讨论的盲点，前 50 条评论质量极高
   ↳ 适合作为团队周会引子，单读结尾几段也能 get 到核心
```

Don't pad — if an item only has 2 lines of real content, stop at 2. Filler ("值得一读"、"很有意思") is worse than a shorter block.

### Template

```
📡 AI Radar — 2026-05-07 daily


🔥 Top 6

1. [HN ▲187] Programming Is Real Engineering, and AI Proves It
   https://news.ycombinator.com/item?id=...
   ↳ 工程师圈对"AI=玩票"叙事的硬核反驳，论点扎实

2. [HF ❤87] meta-llama/Llama-4-70B-Instruct
   https://huggingface.co/meta-llama/Llama-4-70B-Instruct
   ↳ 4 系首个官方 instruct 模型，社区微调底座大概率围着它转

3. [GitHub ★1.2k] foo/bar
   https://github.com/foo/bar
   ↳ 用 X 思路做 agent 框架，一周内涨星势头猛

4. [X @kaiokendev ▲3.2k]
   https://x.com/kaiokendev/status/...
   ↳ 引用推文一句话核心观点

... (6-8 total)


🧠 本周趋势 (weekly only)

- 趋势 1
- 趋势 2
- 趋势 3
- 趋势 4
- 趋势 5


👤 关注候选 (回复 "follow @xxx" 确认)

- @screen_name1 — 今天发了 Llama-4 推理 benchmark，12k 粉，3 个你关注的人提及
- @screen_name2 — ...


📡 Sources: X✓ GitHub✓ HF✓ arxiv✓ HN✓
```

### Length

Target **≤ 3000 chars total** (DingTalk text messages support up to ~5000 — keep headroom). With 2-4 lines per `↳` block:

- 8 items × ~250 chars/item ≈ 2000 chars body
- + sources / candidates / header ≈ 500 chars
- comfortable fit at ~2500 chars

If you're hitting the cap, cut **items**, not field depth. Six well-explained items beat ten cramped ones. Drop bottom-ranked first; never compress the `↳` to a single line just to fit more items.

### When X feed comes back too thin

Smoke-test reality: a young X account with few AI follows yields a near-empty `following` feed. If after time-window filtering the X feed has <3 items, pull a fallback round from seed accounts before giving up.

**Seed-account list** (curated; expand via state file as user follows new ones):

```
NousResearch Teknium _akhaliq omarsar0 ArtificialAnlys HuggingPapers
xai OpenAI AnthropicAI GoogleDeepMind karpathy ylecun
```

**Caching to manage rate cost** — calling 12 accounts × 5 tweets every cron run is wasteful when most of the recent posts repeat across runs. Cache seed-account fetches in the state file:

```json
{
  "seed_cache": {
    "NousResearch": {
      "fetched_at": "2026-05-06T09:05:00+08:00",
      "tweets": [{"id": "...", "created_at": "...", "text": "..."}]
    }
  }
}
```

Cache TTL = **18 hours** for `daily` mode (one cron run uses yesterday's cache for accounts whose last fetch is fresh enough), **3 days** for `weekly`. On TTL expiry, refetch only that account; don't bulk-refresh all 12 at once.

Merge cached + freshly-fetched tweets into the X candidate pool before scoring. Mark these in the digest with `[X seed]` instead of `[X]` so the user knows it came from the fallback path. The `Suggested follows` block highlights seed accounts the user hasn't followed yet — that's the long-term fix; once user's organic following list grows, seed-account fallback fires less, and rate budget shrinks naturally.

**Concrete benefit:** with caching, daily seed-account API calls drop from ~12 (every cron) to ~2-3 (only the TTL-expired ones). Solves the "long-term seed quota will get tight" concern.

---

## Write authorization (the "follow" exception)

The default rule for the `twitter-cli` skill is **never write without explicit user instruction in this turn**. ai-radar inherits that rule with one specific exception:

> When the user replies to an ai-radar digest with `follow @screen_name`, an agent handling that reply MAY call `twitter follow @screen_name` once, then append to `state.followed_log`.

This authorization does NOT extend to:
- Multiple follows per reply (the user must list them explicitly: "follow @a follow @b")
- Posts, retweets, likes — those need their own explicit instruction
- The cron-running agent — it never auto-follows; only the agent handling the user's reply does

Why: cron is unattended; following is a public, hard-to-reverse action that affects how X profiles the account. Keeping the human in the loop avoids quietly building a follow list the user wouldn't have chosen.

---

## Error handling

| Symptom | Action |
|---------|--------|
| `twitter` cookie expired (HTTP 401 from `twitter status`) | Skip both X sources for this run, log in digest footer, surface "X cookies expired — extract from browser and update `~/.hermes/.env`" as a one-liner at the top of the digest |
| GitHub API 403 (rate limit) | Skip GitHub for this run, log in footer; if `GITHUB_TOKEN` is unset, suggest setting it once |
| HF / arxiv / HN HTTP non-200 | Skip that source, log in footer |
| Scoring LLM call fails | Fall back to ranking by source-native metric (HN points, HF likes, GitHub stars, X likes); skip the trend-summary in weekly mode |
| State file corrupt JSON | Backup to `ai_radar_state.json.broken-<timestamp>`, start fresh; log in footer |

**Never** retry a failed source within the same run — cron is daily, the cost of skipping one day's source is negligible compared to the risk of compounding failures or rate-limit lockouts.

---

## Limits and safety

- **Hard cap** on items per source per run: 30. More than that is noise.
- **Hard cap** on follow candidates suggested per run: 5 (weekly), 3 (daily).
- **Hard cap** on total digest length: 3000 chars (matches the `Length` section above; DingTalk text messages support ~5000 so this leaves headroom).
- Don't dump raw tweet text into the digest — summarize. Raw text in cron-pushed messages risks re-broadcasting copyright-shaped content.
- Don't include the user's own tweet IDs from `seen_tweet_ids` in any output (privacy hygiene).
- Don't call any source more than once per run except for the targeted X searches (max 3 search queries).

---

## Manual invocation

```
跑一次 ai-radar 日报模式，不要发 DingTalk，只输出在这里
```
Use `--dry-run` semantics: still read state but don't append; print digest to chat instead of pushing.

```
跑一次 ai-radar 周报模式
```

```
ai-radar catchup 3天
```
Maps to `mode=catchup, days=3`.

---

## Why this design

Six sources are deliberate: each covers a layer the others miss. X surfaces hot takes, GitHub finds working code, HF finds released artifacts, arxiv finds pre-publication research, HN finds the engineering discourse. Removing any one creates blind spots that the user has noticed in past one-source attempts.

Centralized scoring (one LLM call for all candidates) was chosen over per-source thresholds because per-source thresholds drift — what counts as a "good" arxiv abstract changes faster than a hardcoded score floor. Letting the LLM rank cross-source means the digest stays roughly the same density even when one source has a quiet day.

State persistence is a flat JSON file rather than a database: under 100 KB, single writer (cron is serial), trivial to inspect by hand. SQLite would be over-engineered for the read pattern.

The "follow" gate exists because automation that touches public social graphs ages badly. A digest is replayable; a follow is not.
