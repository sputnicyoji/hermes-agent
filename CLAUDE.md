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

## Windows 运行时陷阱（高优先级）

每条都至少踩过一次。debug Hermes 报错前先核对这张表。

### 1. WSL bash 抢 Git Bash

- **现象**：所有 terminal/search_files 命令报 `NotADirectoryError: [WinError 267]`，traceback 终点 `subprocess.Popen` 的 `_winapi.CreateProcess`。
- **根因**：`shutil.which("bash")` 在 PATH 上命中 `C:\Windows\System32\bash.EXE`（WSL launcher）。WSL 的 `pwd -P` 输出 `/mnt/c/...`，Popen 用作 cwd 时 Windows 抛 267。
- **避雷**：`tools/environments/local.py:_find_bash` 必须**先**扫 Git Bash 候选，最后才 PATH lookup，且过滤 `system32`。可用 `HERMES_GIT_BASH_PATH` 强制指定。
- **诊断口子**：terminal_tool retry 全失败时 `logger.exception` 会打 traceback；看 `errors.log` 的 traceback 内 `cwd=` 实际值就能秒判。

### 2. MSYS / WSL cwd 路径必须经 setter normalize

- **现象**：第一条命令 OK，第二条起 WinError 267。
- **根因**：`pwd -P` 输出 `/d/...`（MSYS）或 `/mnt/d/...`（WSL），写入 `self.cwd`，下次 `Popen(cwd=)` 不认。
- **避雷**：`LocalEnvironment.cwd` 是 property，setter 调 `_msys_to_windows_path` 单点 normalize。所有 `self.cwd = X` 都过 setter，**禁止**直接写 `self._cwd`。

### 3. `select.select()` 在 Windows pipe FD 上抛错

- **现象**：所有命令 returncode 0 但 output 空字符串，工具看着"成功"实际无内容。
- **根因**：Windows 的 `select` 只能用于 socket，pipe FD 抛 `OSError WinError 10093`，`_drain` 立刻 break。
- **避雷**：`tools/environments/base.py:_wait_for_process` 必须 dispatch 到 `_drain_windows`（blocking `os.read` 直到 EOF）。这是本地必备 patch（`cf4bbe0af`），上游没修。

### 4. `terminal.cwd: '.'` 被 Gateway 改写为 `Path.home()`

- **现象**：以为命令在项目目录跑，实际 cwd 是 `C:\Users\<user>`。
- **根因**：`gateway/run.py:422-425` —— TERMINAL_CWD 为空/`./auto/cwd` 时 fallback 到 `str(Path.home())`。
- **避雷**：要绑定项目目录，`config.yaml` 写绝对路径：`terminal.cwd: D:\Hermes_Agent`。

### 5. `.pyc` 缓存污染（重启不生效）

- **现象**：重启 Gateway 后仍跑旧代码。
- **根因**：Python lazy import，模块在第一次被引用时才编译 `.pyc`。如果 Gateway 启动后、首次 import 那一刻你正好 `git checkout` 切到旧分支，磁盘上的旧 `.py` 被编译进 `.pyc`，进程加载后即使 `.py` 改回也不重读。
- **避雷**：Gateway 跑着的时候不切分支。重启后用下面的命令验证 `.pyc` 跟 `.py` 同源：
  ```bash
  PYTHONUTF8=1 .venv/Scripts/python.exe -c "
  import struct, time
  with open('tools/environments/__pycache__/local.cpython-311.pyc','rb') as f: h=f.read(16)
  print('pyc says src mtime:', time.ctime(struct.unpack('<I',h[8:12])[0]),
        'size:', struct.unpack('<I',h[12:16])[0])
  import os; print('actual:', time.ctime(os.path.getmtime('tools/environments/local.py')),
                   'size:', os.path.getsize('tools/environments/local.py'))
  "
  ```

### 6. Gateway 三层进程结构

- launcher (`hermes.exe` / cmd.exe wrapper) → wrapper (venv `python.exe`) → worker (uv-managed `cpython-3.11.x`)
- 实际加载 module + 跑 LocalEnvironment 的是 **worker**。
- 看 cwd / env vars 用 `psutil.Process(worker_pid).cwd() / .environ()`。
- kill Gateway 要把 3 个 PID 都 kill，否则 launcher 会重 spawn worker：
  ```powershell
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "hermes.*gateway" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  ```

### 7. `/tmp` 在 Git Bash 与 Python 视角不一致

- bash 视角：`C:\Program Files\Git\tmp`
- Python 视角：`C:\tmp`
- "bash 写 `/tmp/foo` + Python 读 `/tmp/foo`" 模式 silent fail。`_update_cwd` 的文件分支就是这样——marker stdout 才是 self.cwd 真正来源。

### 8. 调试信息口子

- `errors.log` 只记简短 ERROR 行；traceback 看 `gateway.log` 或 `terminal_tool` 的 `logger.exception`（已加，retry 全失败时 fire）。
- `psutil.Process(pid).environ()` 看 worker 实时环境变量（`TERMINAL_CWD`、`HERMES_GIT_BASH_PATH` 等）。
- 解 `.pyc` 头取 `(src_mtime, size)`，对比磁盘 `.py` 的 mtime/size——不一致就是缓存污染。
- `marshal.load(pyc[16:])` 后 walk `co_consts` 列函数名，验证 `.pyc` 是否含某次修复的 helper。
