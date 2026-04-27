# Hermes Agent — 本地 Fork 工作流

## 仓库拓扑

- `origin` → `NousResearch/hermes-agent`（上游真源，只读）
- `fork` → `sputnicyoji/hermes-agent`（个人仓库）

## 分支角色

| 分支 | 角色 | 同步策略 | 是否允许脏提交 |
|------|------|---------|--------------|
| `origin/main` | 上游真源 | 只读 | 否 |
| 本地 `main` | 上游镜像 | 只 fast-forward（`git fetch origin main:main`） | 否 |
| `fork/main` | 个人仓库镜像 | 只 fast-forward（`git push fork main:main`） | 否 |
| `feat/*` / `fix/*` | 单一主题 PR 分支 | rebase 到最新 main | 否，必须语义干净 |
| `local-runtime` | 日常运行聚合分支 | 周期性 merge main + 各 feat 分支 | **是** |

## 核心原则

- 本地 `main` 和 `fork/main` 永远与 `origin/main` 一致，不在上面提交任何东西。
- `feat/*` / `fix/*` 保持单一主题，准备 PR 上游。
- `local-runtime` = "自己的发行版"，上游不接收也不需要。
- 三者解耦，任一崩了不影响另外两个。

## 日常操作

### 同步上游

```bash
rtk git fetch origin
rtk git fetch origin main:main                    # 本地 main 快进
rtk git push fork main:main                        # fork/main 快进
```

### 更新 local-runtime

```bash
rtk git checkout local-runtime
rtk git merge main                                 # 拉入上游更新
# 解决冲突
rtk git push fork local-runtime
```

### 发现 bug 的决策流程

本地跑 `local-runtime` 发现问题时：

1. **对上游也有价值的修复** → 先在独立 `fix/xxx` 分支写，提 PR 到上游，再 merge 回 `local-runtime`
2. **只对自己有意义的修改**（本地配置、个人 hack）→ 直接在 `local-runtime` 提交

纪律点：不要把通用修复只堆在 `local-runtime` 上，否则会变成无法回流上游的死水。

## 初始化 local-runtime

当前 `feat/dingtalk-file-download` 已包含所有 5 个 DingTalk 修复的重新实现，基于它建立：

```bash
rtk git checkout -b local-runtime feat/dingtalk-file-download
rtk git merge main
# 解决 gateway/platforms/dingtalk.py 和 gateway/config.py 可能的冲突
rtk git push -u fork local-runtime
```

## 环境约束

- Windows bash，shell 使用 Unix 语法（`/dev/null` 而非 `NUL`）
- `PYTHONUTF8=1` 避免 GBK 编码问题（见 `memory/project_hermes_utf8_gbk_trap.md`）
- 所有 git/gh 命令前缀 `rtk`（见全局 CLAUDE.md RTK 规则）
