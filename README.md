# XRZagent — 仙人掌 Agent

基于 DeepSeek + Playwright 的本地桌面 Agent 系统。

## 快速启动


## 功能状态表 (v0.3.1)

### 核心引擎
| 功能 | 状态 | 说明 |
|------|------|------|
| DeepSeek 驱动 | ✅ 正常 | 通过 Playwright 浏览器自动化与 DeepSeek 对话 |
| 工具注册系统 | ✅ 正常 | 20+ 内置工具（文件/浏览器/子代理/记忆/文档） |
| JSON 协议解析 | ✅ 正常 | @@@@ 包裹符，自动修复反斜杠/驱动器号/尾部逗号 |
| 纯文本检测拦截 | ✅ 正常 | 自动纠正未使用 @@@@ 协议的 AI 输出 |
| 放弃句式拦截 | ✅ 正常 | 13种黑名单模式，防止 AI 找借口放弃 |
| 任务完成验证 | ✅ 正常 | done() 前验证文件是否生成 |
| 深度思考模式 | ✅ 正常 | deep/think 命令切换 DeepSeek 深度思考 |
| 暂停/恢复 | ✅ 正常 | p 命令暂停/恢复 Agent |
| Ctrl+C 安全处理 | ⚠️ 待验证 | 不传播到子代理，需实际测试 |
| 终端显示增强 | ✅ 正常 | _on_event 显示工具执行/完成/错误 |

### 工具系统
| 功能 | 状态 | 说明 |
|------|------|------|
| 文件操作 | ✅ 正常 | file_write, file_read, file_append, file_delete, file_exists |
| Shell 执行 | ✅ 正常 | shell_exec (RAW 模式) |
| 浏览器操作 | ✅ 正常 | browser_search, browser_visit, browser_screenshot |
| 浏览器填充 | ✅ 正常 | browser_fill, browser_click |
| 子代理管理 | ✅ 正常 | browser_research, check_task, wait_task |
| 记忆系统 | ✅ 正常 | remember, recall, summarize, list_summaries |
| 多模态文档 | ⚠️ 部分 | docx_create (中文编码问题待验证) |
| 目录操作 | ✅ 正常 | dir_create, dir_list |

### 子代理系统
| 功能 | 状态 | 说明 |
|------|------|------|
| 独立进程 | ✅ 正常 | subprocess.Popen，不开独立控制台窗口 |
| 日志重定向 | ✅ 正常 | 输出到 subagent_{task_id}.log |
| 凭据复制 | ✅ 正常 | 从主凭据目录复制到临时目录 |
| 任务状态监控 | ✅ 正常 | _monitor_subagent + _monitor_script |
| 进程通知母代理 | ✅ 正常 | 通知队列 + 回调机制 |

### 待解决问题
| 问题 | 优先级 | 说明 |
|------|--------|------|
| python-docx 中文编码 | 中 | 生成 .docx 时报错，待验证 |
| 深度思考内容抓取 | 中 | 选择器可能需适配新版 DeepSeek 界面 |
| make.bat 乱码 | 低 | 批处理编码问题，不影响核心功能 |
| 浏览器 UI 选择器 | 中 | DeepSeek 界面更新后可能需更新选择器 |

### 未实现功能
| 功能 | 说明 |
|------|------|
| 图形界面 | 用户明确要求不实现 |
| 上传到网页表单 | 需 browser.py 实现 upload_file |

## 项目结构

```
XianRenZhangAgent/
├── terminal.py              # 主入口
├── subagent_main.py          # 子代理进程入口
├── web_searcher.py           # 网页搜索工具（urllib 直连）
├── agent_core/
│   ├── commander.py          # 主控制器（总工程师）
│   ├── session.py            # DeepSeek 会话管理
│   ├── browser.py            # Playwright 浏览器管理
│   ├── protocol.py           # JSON 指令协议解析
│   ├── subagent_manager.py   # 子代理管理（非阻塞架构）
│   ├── subagent.py           # 子代理基类
│   └── memory_manager.py     # 记忆系统
```

## 协议格式

```
@@@@
{"tool": "工具名", "params": {}, "id": "1"}
@@@@
```

## 更新日志

### v0.3.1 (2026-06-01)
- 修复：`任务已完成` 放弃句式误报（正则更精确）
- 新增：子代理日志重定向到 `subagent_{task_id}.log`（subagent_manager.py）
- 修复：GIVE_UP_PATTERNS 数量充足（13种）
- 所有 10 个 .py 文件语法通过

### v0.3 (2026-06-01)
- 修复：protocol.py `_try_fix` 重写（驱动器号始终检测、路径反斜杠修复）
- 修复：terminal.py `_on_event` 打印所有事件类型
- 修复：commander.py 放弃句式拦截（13种黑名单）
- 修复：commander.py 任务完成验证（done 拦截）
- 修复：subagent_manager.py 进程无人监控问题（添加 `_monitor_script`）
- 修复：subagent_manager.py CREATE_NEW_CONSOLE 已移除
- 修复：subagent.py 重复类定义（SubAgentManager 冲突）
- 修复：commander.py 错误 import（BrowserSubAgent 误导入）
- 清理：200+ 垃圾 md 文件
- 创建：README.md + .gitignore

### v0.2 (2026-05-31)
- 初始修复：terminal.py 损坏恢复、commander.py 纯文本检测
