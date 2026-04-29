# build-quality-agent

> Claude-powered git pre-push reviewer for indie OSS projects. Stops the bad commit *before* it costs you a Vercel build minute.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)
[![Model](https://img.shields.io/badge/Claude-Haiku_4.5-D97706?logoColor=white)](https://anthropic.com)
[![Tests](https://github.com/alex-jb/build-quality-agent/actions/workflows/test.yml/badge.svg)](https://github.com/alex-jb/build-quality-agent/actions/workflows/test.yml)

Built by [Alex Ji](https://github.com/alex-jb) — solo founder shipping [VibeXForge](https://github.com/alex-jb/vibex) and [Orallexa](https://github.com/alex-jb/orallexa-ai-trading-agent). Born from this thought:

> *I just spent $131.92 in Vercel build minutes this month because I keep pushing commits with type errors and missing imports.*

## What it does

Before every `git push`, it runs Claude over the diff and decides:

- **PASS** — push proceeds
- **BLOCK** — push is aborted, you fix the issue locally

That's the whole pitch. No CI loop. No remote build that fails 6 minutes in. Catches the obvious stuff (type errors, removed imports, hardcoded secrets, reverted auth checks) before your laptop fan even spins up.

## Install

```bash
# 1. Clone
git clone https://github.com/alex-jb/build-quality-agent.git
cd build-quality-agent
pip install -e .

# 2. Set your Anthropic key (graceful no-op without it)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Wire into a target repo
cd ~/path/to/your/repo
bash ~/Desktop/build-quality-agent/scripts/install-hook.sh
```

That's it. Next `git push` will trigger a review.

## Bypass

If the agent is wrong (it sometimes is — Claude reviews a *diff*, not a full repo, so context-free changes occasionally trip it):

```bash
BUILD_AGENT_SKIP=1 git push
```

This is the explicit, loud bypass. `--no-verify` also works but is silent. We prefer loud.

## Usage examples

```bash
# Manual run on the most recent commit
python3 -m build_quality_agent --diff-range HEAD~1..HEAD

# Review without blocking (advisory mode)
python3 -m build_quality_agent --no-block

# Quiet unless something's wrong
python3 -m build_quality_agent --quiet

# Force a specific model
BUILD_AGENT_MODEL=claude-sonnet-4-6 python3 -m build_quality_agent

# Token + cost report (aggregates ~/.build-quality-agent/usage.jsonl)
python3 -m build_quality_agent --usage
```

## Design choices

- **Default Haiku 4.5, not Sonnet.** Diff review is a fast cheap task — Haiku gets ~10s response and pennies per push. Sonnet only kicks in if you set `BUILD_AGENT_MODEL`.
- **PASS by default on any internal failure.** Network down, key missing, Claude flake — the agent prints a warning and lets the push through. Better unverified push than blocking real work.
- **50kB diff cap, junk paths excluded.** Lockfiles (`package-lock.json`, `bun.lock`, etc.), generated types (`next-env.d.ts`), build output (`.next/`, `dist/`), and binary assets (images, fonts, MP4s) are stripped before review so the budget gets spent on real source.
- **Vercel-aware prompt.** The agent specifically looks for the patterns that crash Next.js / Vercel builds: missing `default export` on `page.tsx` / `layout.tsx`, client hooks without `"use client"`, server-only imports leaking into client components, undefined symbols, hardcoded secrets.
- **Reads git's pre-push stdin.** When invoked as a hook, the agent parses the `<local_ref> <local_oid> <remote_ref> <remote_oid>` lines git passes in. That makes the review range exactly match what's being pushed — including new branches without upstream tracking.
- **No build runner inside the hook.** Running `npm run build` in pre-push would add 5-6 min to every push. Out of scope here. This agent reviews intent + obvious bugs; a separate CI build still catches everything.

## Cost tracking

Every review writes a row to `~/.build-quality-agent/usage.jsonl`. Run `python3 -m build_quality_agent --usage` to see total runs, pass/block split, token counts, and an estimated dollar cost (Haiku 4.5: $1/MTok in, $5/MTok out).

## Roadmap

- [x] **v0.1** — Pre-push hook · Claude diff review · graceful degradation
- [x] **v0.2** — `pip install -e .` portability · git stdin parsing · junk-path filter · Vercel-aware prompt · pytest suite · `--usage` cost report
- [ ] **v0.3** — Project-specific rule files (`.build-quality-agent.toml`)
- [ ] **v0.4** — `--build` flag for projects that *want* the slow runtime build
- [ ] **v0.5** — Auto-suggested fix (Claude proposes the smallest patch that would PASS)

## License

MIT.
