# Upstream PR Log — `NousResearch/hermes-agent`

个人开源贡献记录。按 PR 编号倒序，最新在前。

状态图例：
- 🟢 MERGED — 上游合并
- 🔵 SUPERSEDED — 被其他 PR 替代合并
- 🟡 OPEN — 审核中
- ⚪ CLOSED — 关闭未合并（非替代）
- 🔴 REJECTED — 维护者明确拒绝

---

## 活跃 PR

### #12964 — fix(gateway): don't claim text document content is inlined when it isn't
- **分支**: `fix/gateway-text-document-prompt`
- **创建**: 2026-04-20
- **状态**: 🟡 OPEN
- **主题**: 修正文档附件提示——"Its content has been included below" 其实没内联，误导 LLM 产生"file not found"幻觉
- **规模**: +2 −2 (gateway/run.py)
- **链接**: https://github.com/NousResearch/hermes-agent/pull/12964

### #12963 — fix(file-ops): map Windows absolute paths for POSIX shells on Windows
- **分支**: `fix/windows-terminal-path-mapping`
- **创建**: 2026-04-20
- **状态**: 🟡 OPEN
- **主题**: Windows 下 `bash -c` 接到 `C:/...` 路径无法识别；按 cwd 前缀自动映射到 `/mnt/c/...`（WSL）或 `/c/...`（Git Bash）
- **规模**: +87 −2（含 5 个单元测试）
- **链接**: https://github.com/NousResearch/hermes-agent/pull/12963

### #12962 — fix(terminal): capture stdout on Windows local backend
- **分支**: `fix/windows-terminal-stdout-drain`
- **创建**: 2026-04-20
- **状态**: 🟡 OPEN
- **主题**: Windows `select.select()` 只支持 socket，在 pipe FD 上直接抛 `OSError (WinError 10093)`，drain 静默 break 导致所有 shell 命令返回空 stdout。Windows 走阻塞 `os.read` 分支
- **规模**: +37 −1
- **链接**: https://github.com/NousResearch/hermes-agent/pull/12962

### #8988 — feat(gateway/dingtalk): download inbound pictures for vision models
- **分支**: `feat/dingtalk-picture-download`
- **创建**: 2026-04-13
- **状态**: 🟡 OPEN（待决）
- **主题**: 钉钉图片下载到本地缓存供视觉模型使用
- **现实**: 上游 main 实现了 URL 路径版本（经 rich_text URL），但该 URL 访问不稳定（bucket 策略）。本 PR 的字节缓存方案更稳，但依赖 `messageFiles/download` API——对个别企业内部应用返回 500
- **链接**: https://github.com/NousResearch/hermes-agent/pull/8988

---

## 已关闭 PR

### #10245 — feat(gateway/dingtalk): receive file attachments via Stream callback
- **分支**: `feat/dingtalk-file-download`
- **创建**: 2026-04-15
- **关闭**: 2026-04-20（自行关闭）
- **状态**: ⚪ CLOSED
- **主题**: 钉钉文件消息下载
- **关闭原因**: 依赖的前置 PR（#8988、#8960、#8957）全部关闭，底座消失；且依赖的 `messageFiles/download` API 对测试 bot 永久返回 500

### #8960 — feat(gateway/dingtalk): env-based config and richer msgtype handling
- **分支**: `feat/dingtalk-env-config-msgtypes`
- **创建**: 2026-04-13
- **关闭**: 2026-04-20（自行关闭）
- **状态**: 🔵 SUPERSEDED
- **主题**: 钉钉 env 变量配置 + msgtype 分发
- **关闭原因**: 上游 main 已独立实现等效 env 变量读取逻辑

### #8957 — fix(gateway/dingtalk): allow oapi.dingtalk.com webhook + correctness fixes
- **分支**: `fix/dingtalk-oapi-webhook`
- **创建**: 2026-04-13
- **关闭**: 2026-04-17（teknium1 关闭）
- **状态**: 🔵 SUPERSEDED by #11471
- **主题**: 支持 oapi.dingtalk.com webhook 域名
- **维护者评论**: "Closing — the oapi.dingtalk.com webhook domain is now accepted on main as of #11471. Thanks for catching and reporting this."

### #8954 — fix(gateway/dingtalk): support dingtalk-stream >= 0.24
- **分支**: `fix/dingtalk-sdk-024-compat`
- **创建**: 2026-04-13
- **关闭**: 2026-04-17（teknium1 关闭）
- **状态**: 🔵 SUPERSEDED by #11471
- **主题**: dingtalk-stream SDK 0.24+ 的 `async process` 和 `CallbackMessage` 改造适配
- **维护者评论**: "Closing as superseded by #11471 which salvaged @kevinskysunny's minimal fix (#11257) and added a follow-up for the broken `_extract_text()` path..."

### #6487 — fix(cli): add explicit UTF-8 encoding when reading config YAML on Windows
- **分支**: `fix/cli-config-utf8-encoding`
- **创建**: 2026-04-09
- **关闭**: 2026-04-13
- **状态**: ⚪ CLOSED
- **主题**: Windows CN locale 下 YAML 读取 encoding 未指定导致 GBK 解码失败

---

## 统计

| 指标 | 数量 |
|------|------|
| 总 PR | 9 |
| 🟢 MERGED | 0 |
| 🔵 SUPERSEDED | 3（贡献通过替代 PR 落地） |
| ⚪ CLOSED | 2 |
| 🟡 OPEN | 4 |
| 🔴 REJECTED | 0 |

## 经验沉淀

- **链式 PR 是陷阱**：#10245 依赖 #8988/#8960/#8957，前置全凉连带死。后续单条 PR 基于 main HEAD。
- **先 issue 探路**：重大改动先开 issue 拿维护者态度，避免 PR 被极简替代实现（如 #11471）抢先。
- **PR 格式纪律**：commit message = PR body；单一主题；独立可审；无 in-flight 依赖。
- **维护者偏好"小而准"**：teknium1 倾向接受范围窄、实现极简的修复；大而全的 feature PR 被替代概率高。
- **"superseded" 不等于白写**：上游维护者在评论里明确感谢问题发现，最终修复仍来自你触发的关注。算半个贡献。
- **用时间戳绝对日期**：git log 里时间戳不会骗人，避免"上周"、"几天前"这种相对表述。

## 下次更新时机

- 维护者回复 / CI 结果变化
- PR 被关闭 / 合并
- 被新 PR 替代（记下替代 PR 号）
