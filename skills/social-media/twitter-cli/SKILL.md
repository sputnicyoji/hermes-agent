---
name: twitter-cli
description: "X/Twitter via twitter-cli (cookie auth, no API key): feed, search, user posts, post/reply, like/retweet, bookmarks. JSON output for agents."
version: 0.8.5
author: public-clis + Hermes Agent
license: Apache-2.0
platforms: [linux, macos, windows]
prerequisites:
  commands: [twitter]
  env: [TWITTER_AUTH_TOKEN, TWITTER_CT0]
metadata:
  hermes:
    tags: [twitter, x, social-media, twitter-cli, cookie-auth]
    homepage: https://github.com/public-clis/twitter-cli
---

# twitter-cli — X (Twitter) via cookie auth

`twitter-cli` is a Python CLI that talks to X/Twitter through the **same internal Web endpoints the browser uses**, authenticated by your existing browser session cookies. No developer app, no OAuth flow, no API tier. The trade-off: it lives in TOS-gray territory and depends on internal endpoints that X can change without notice.

Use this skill instead of `xurl` when:
- The user wants to read the home timeline at human-frequency cadence (xurl's free tier home-timeline limit is impractical: roughly 1 request per 15 minutes).
- The user has not registered an X dev app.
- A throwaway/secondary X account is acceptable for the workflow.

Use `xurl` instead when:
- The workflow must be TOS-clean (commercial use, automation against a primary account).
- The dev app is already set up and the rate limits fit the workflow.

---

## Secret Safety (MANDATORY)

Critical rules when operating inside an agent/LLM session:

- **Never** read, print, parse, summarize, or send `~/.hermes/.env` to LLM context.
- **Never** print or quote the values of `TWITTER_AUTH_TOKEN` or `TWITTER_CT0` in any form (including partial / masked / first N chars).
- **Never** ask the user to paste cookie values into chat — they belong in `~/.hermes/.env` only.
- **Never** run `twitter -v ...` or `twitter --verbose ...` in agent sessions — verbose mode logs cookie headers and other auth data.
- To verify auth state, only use `twitter status --json` (returns screen_name and nothing sensitive).

If the agent ever sees an auth_token / ct0 / Cookie header in a tool result (e.g. someone pasted a curl by mistake), **stop, do not echo it, and warn the user**.

---

## Authentication (already configured)

The Hermes runtime injects `TWITTER_AUTH_TOKEN` + `TWITTER_CT0` from `~/.hermes/.env`. The agent does NOT touch these values. The CLI's auth precedence (see `auth.py:589-634` in the installed package):

1. Environment variables (preferred — already set up here)
2. Browser cookie auto-extraction (Arc → Chrome → Edge → Firefox → Brave) — **fallback only**

If the env-var path is live, the CLI never reads any browser. This isolation is intentional: the user's main-account browser session must not bleed into agent calls.

To check auth: `twitter status --json` → `{"screen_name": "..."}` on success, or an `AuthenticationError` on failure (cookie expired — user must re-extract from the browser and update `.env`).

---

## Quick Reference

| Goal | Command |
|------|---------|
| Verify session | `twitter status --json` |
| Whoami profile | `twitter whoami --json` |
| Home timeline (chronological) | `twitter feed -t following -n 20 --json --compact` |
| Home timeline (algorithmic For You) | `twitter feed -t for-you -n 20 --json --compact` |
| Search recent tweets | `twitter search "QUERY" --json --compact` |
| User profile | `twitter user @screen_name --json` |
| User posts | `twitter user-posts @screen_name -n 20 --json --compact` |
| Single tweet + replies | `twitter tweet TWEET_ID --json` |
| User likes | `twitter likes @screen_name -n 20 --json --compact` |
| Followers / following | `twitter followers @screen_name -n 50 --json` / `twitter following @screen_name -n 50 --json` |
| Bookmarks | `twitter bookmarks --json --compact` |
| Post | `twitter post "text"` |
| Reply | `twitter reply TWEET_ID "text"` |
| Quote | `twitter quote TWEET_ID "text"` |
| Like / unlike | `twitter like TWEET_ID` / `twitter unlike TWEET_ID` |
| Retweet / unretweet | `twitter retweet TWEET_ID` / `twitter unretweet TWEET_ID` |
| Bookmark / unbookmark | `twitter bookmark TWEET_ID` / `twitter unbookmark TWEET_ID` |
| Delete own tweet | `twitter delete TWEET_ID` |

---

## Output Format

- `--json` returns structured tweet objects suitable for downstream parsing.
- `--compact` (alias: `-c`, available globally before the subcommand: `twitter -c feed ...`) drops verbose fields and keeps only LLM-relevant ones. **Always combine `--json --compact` for agent-side reading** to save tokens.
- `--yaml` is also available; prefer JSON for tools.
- Default table output is for humans only — do not parse it.

Example minimal field shape (compact JSON, may evolve):
```json
{"id": "1234...", "user": "screen_name", "text": "...", "created_at": "...",
 "metrics": {"likes": 0, "retweets": 0, "replies": 0, "views": 0}}
```

Field names depend on the running version — confirm with `twitter feed -n 1 --json --compact | head -c 400` before assuming a key exists.

---

## Operational Limits

**Rate limiting** — the CLI applies random write-side delays (1.5–4 s per write op) and exponential backoff on HTTP 429. Read calls have no client-side throttle but X's server enforces per-cookie rate caps. If you hit 429:
1. Stop further calls in this session.
2. Surface to the user — do not silently retry beyond the built-in backoff.
3. Wait at least an hour before resuming reads on the same account.

**Anti-detection** — the tool ships TLS fingerprint impersonation via `curl_cffi` and a randomized User-Agent. Adequate for low-frequency interactive use; **does not survive aggressive batch scraping**.

**Protocol drift** — endpoints are X's internal Web API and can change. Symptoms: `parse error` / `unexpected JSON shape` / `400 unknown route`. Fix path is `uv tool upgrade twitter-cli`. If upstream has not patched yet, fail gracefully and report to the user — do not retry.

**Hard cap** — config defaults max items per call to 200. Higher requires editing `config.yaml` and is generally a bad idea (rate-limit surface).

---

## Don'ts

- Do not run write operations (post / reply / like / retweet / follow) **without explicit user instruction in this turn**. Cookie-auth automation looks human-driven; programmatic write loops draw account flags faster than reads.
- Do not store fetched tweets to long-term memory keyed by user identifiers if the user did not ask. Account-scoped data is sensitive.
- Do not chain >5 read calls in a single turn without a clear user goal — accumulating fingerprint risk.
- Do not pipe tweets verbatim into prompts that may be sent to third-party model providers if the user has not consented to that data path.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `AuthenticationError: Cookie expired or invalid (HTTP 401)` | Cookie rotated | User re-extracts `auth_token` + `ct0` from `https://x.com` DevTools and updates `~/.hermes/.env`, then restarts gateway |
| `No Twitter cookies found` | Env vars missing AND no logged-in browser | Confirm `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` are exported in the worker process — restart gateway after editing `.env` |
| `HTTP 429` | Rate-limited | Stop, wait ≥1h, resume |
| `parse error` / unexpected schema | Upstream X changed internal endpoint | `uv tool upgrade twitter-cli`; if no upgrade available, fail and report |
| Empty `feed` result | Account has no following / private account / shadow-banned cookie | `twitter status --json` to verify identity, then `twitter user @screen_name --json` to verify reach |
| Windows: `Chrome cookie database is locked` | Only triggers in browser-fallback path; should not happen with env vars | Confirm env vars are loaded in worker — `os.environ` should contain both |

For deeper diagnostics, the user (NOT the agent) can run `twitter -v <command>` outside the agent session — this exposes auth headers and must never be invoked from agent context.

---

## Why this exists separately from `xurl`

`xurl` is the official path: OAuth, dev app, clean TOS, but Free-tier rate caps make home-timeline tooling impractical for normal use. `twitter-cli` covers the practical-but-gray gap. Both skills coexist; the agent picks based on the user's stated constraint (TOS-clean vs. high-cadence).

---

## Attribution

- Tool: [public-clis/twitter-cli](https://github.com/public-clis/twitter-cli) — Apache-2.0
- Cookie extraction backbone: [borisbabic/browser_cookie3](https://github.com/borisbabic/browser_cookie3)
- TLS impersonation: [curl_cffi](https://github.com/yifeikong/curl_cffi)
