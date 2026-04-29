# build-quality-agent

[English](README.md) | **中文**

> 给独立开发者的 git pre-push 代码审查工具,Claude 驱动。在烂 commit 烧掉你 Vercel 构建分钟之前先拦下来。

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)
[![Model](https://img.shields.io/badge/Claude-Haiku_4.5-D97706?logoColor=white)](https://anthropic.com)
[![Tests](https://github.com/alex-jb/build-quality-agent/actions/workflows/test.yml/badge.svg)](https://github.com/alex-jb/build-quality-agent/actions/workflows/test.yml)

作者 [Alex Ji](https://github.com/alex-jb) — 单人独立开发者,在做 [VibeXForge](https://github.com/alex-jb/vibex) 和 [Orallexa](https://github.com/alex-jb/orallexa-ai-trading-agent)。这工具的诞生是因为这一句话:

> *这个月我在 Vercel 构建分钟上烧了 $131.92,就因为我老是 push 带着类型错误和缺失 import 的 commit。*

## 它干什么

每次 `git push` 之前,Claude 会过一遍这次的 diff,然后给出判定:

- **PASS** —— push 继续
- **BLOCK** —— push 被拦下,你本地修完再 push

就这么简单。不走 CI loop。不会让远端跑 6 分钟才 fail。明显的问题(类型错误、删了 import、硬编码 secret、把 auth check 误删)在你笔记本风扇还没转起来之前就抓到了。

### `--build` 参数(v0.3+)—— 还能真跑一次本地 build

`--build` 在 review 之前先跑一次本地 build(自动识别:JS 用 `npm`/`pnpm`/`bun`/`yarn run build`,Python 用 `python -m build`,Rust `cargo check`,Go `go build`)。build 失败时,build log 会一起塞进 Claude 的 prompt 里给统一解释,而且 push **一定 BLOCK**。

```bash
build-quality-agent --build              # 单次跑
BUILD_AGENT_BUILD=1 git push              # 这次 push 默认开启
```

4 分钟的 build 超时上限够用;大部分独立项目本地 build 30-90 秒。`--build` + diff review 加起来的成本:~$0.0006 + 笔记本 30-60 秒,而远端跑挂一次 = $0.12/min × 6min = **每挡下一次失败的远端 build 省 $0.72**。

## 安装

```bash
# 1. 克隆
git clone https://github.com/alex-jb/build-quality-agent.git
cd build-quality-agent
pip install -e .

# 2. 设置 Anthropic key(没设也不会报错,会优雅降级)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. 接到目标 repo
cd ~/path/to/your/repo
bash ~/Desktop/build-quality-agent/scripts/install-hook.sh
```

完事。下次 `git push` 就会自动触发 review。

## 跳过

如果 agent 判错了(确实会 —— Claude 看的是 *diff*,不是整个 repo,所以脱离上下文的改动偶尔会让它误判):

```bash
BUILD_AGENT_SKIP=1 git push
```

这是显式、明显的跳过。`--no-verify` 也能用但太安静。我们更喜欢明显的方式。

## 使用示例

```bash
# 手动跑一下最近一个 commit
python3 -m build_quality_agent --diff-range HEAD~1..HEAD

# 只 review 不拦截(advisory 模式)
python3 -m build_quality_agent --no-block

# 静默模式 —— 只在出问题时才输出
python3 -m build_quality_agent --quiet

# 强制用某个模型
BUILD_AGENT_MODEL=claude-sonnet-4-6 python3 -m build_quality_agent

# Token 用量 + 成本报告(汇总 ~/.build-quality-agent/usage.jsonl)
python3 -m build_quality_agent --usage
```

## 设计取舍

- **默认 Haiku 4.5,不是 Sonnet。** Diff review 是个又快又便宜的任务 —— Haiku 大概 10 秒出结果,每次 push 也就几分钱。要更高质量的话设 `BUILD_AGENT_MODEL` 切到 Sonnet。
- **任何内部错误都默认 PASS。** 网络挂了、key 没设、Claude 抽风 —— agent 会打个警告然后让 push 继续。让没验证过的 push 过去,好过把正常工作拦下。
- **50kB diff 上限,垃圾路径自动过滤。** Lockfile(`package-lock.json`、`bun.lock` 等)、生成的类型文件(`next-env.d.ts`)、构建产物(`.next/`、`dist/`)、二进制资源(图片、字体、MP4)在送进 review 之前就被剥掉。这样 50kB 预算全花在真正的源码上。
- **Vercel-aware prompt。** Agent 专门盯着会让 Next.js / Vercel 构建挂掉的几种模式:`page.tsx` / `layout.tsx` 缺 `default export`、用了 client hook 但没写 `"use client"`、server-only 的 import 漏到 client 组件里、未定义符号、硬编码 secret。
- **读取 git 的 pre-push stdin。** 当作为 hook 调用时,agent 会解析 git 传进来的 `<local_ref> <local_oid> <remote_ref> <remote_oid>`。这样 review 范围就精确等于这次 push 的范围 —— 包括没有 upstream 跟踪的新 branch。
- **Hook 里不跑 build。** 在 pre-push 里跑 `npm run build` 会让每次 push 多 5-6 分钟,不在本工具范围内。这个 agent 只看意图 + 明显 bug;真正的 build 还是 CI 来兜底。

## 成本追踪

每次 review 都会写一行到 `~/.build-quality-agent/usage.jsonl`。跑 `python3 -m build_quality_agent --usage` 能看到总运行次数、pass/block 分布、token 数,以及估算的美元成本(Haiku 4.5:输入 $1/MTok,输出 $5/MTok)。

## Roadmap

- [x] **v0.1** —— Pre-push hook · Claude diff review · 优雅降级
- [x] **v0.2** —— `pip install -e .` 跨机器可用 · 解析 git stdin · 垃圾路径过滤 · Vercel-aware prompt · pytest 测试套件 · `--usage` 成本报告
- [ ] **v0.3** —— 项目级规则文件(`.build-quality-agent.toml`)
- [ ] **v0.4** —— `--build` 选项给那些*确实想*跑 build 的项目
- [ ] **v0.5** —— 自动建议补丁(Claude 提出最小补丁让 BLOCK 变 PASS)

## 协议

MIT。
