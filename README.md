# build-quality-agent

> Claude-powered git pre-push reviewer for indie OSS projects. Stops the bad commit *before* it costs you a Vercel build minute.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)
[![Model](https://img.shields.io/badge/Claude-Haiku_4.5-D97706?logoColor=white)](https://anthropic.com)

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
```

## Design choices

- **Default Haiku 4.5, not Sonnet.** Diff review is a fast cheap task — Haiku gets ~10s response and pennies per push. Sonnet only kicks in if you set `BUILD_AGENT_MODEL`.
- **PASS by default on any internal failure.** Network down, key missing, Claude flake — the agent prints a warning and lets the push through. Better unverified push than blocking real work.
- **50kB diff cap.** Beyond this, review quality drops fast. The agent samples the head of the diff and notes the truncation in the prompt.
- **No build runner inside the hook.** Running `npm run build` in pre-push would add 5-6 min to every push. Out of scope here. This agent reviews intent + obvious bugs; a separate CI build still catches everything.

## Roadmap

- [x] **v0.1** — Pre-push hook · Claude diff review · graceful degradation
- [ ] **v0.2** — `--build` flag for projects that *want* the slow runtime build
- [ ] **v0.3** — Project-specific rule files (`.build-quality-agent.toml`)
- [ ] **v0.4** — Cost tracker · per-push token report · monthly digest
- [ ] **v0.5** — Auto-suggested fix (Claude proposes the smallest patch that would PASS)

## License

MIT.
