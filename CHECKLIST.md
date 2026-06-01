# 功能清单 — 逐项核对

生成时间：2026-06-01

## 一、用户明确要求的功能（除图形界面外）

### 1.1 核心协议
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| @@@@ JSON 包裹符协议 | 必须使用 @@@@ 包裹 JSON | protocol.py | ⏳ | 发纯文本测试拦截 |
| 自动修复反斜杠/驱动器号 | JSON 错误自动修复 | protocol.py _try_fix | ⏳ | 发送带 C:Users 的 JSON |
| 自动修复尾部逗号 | JSON 错误自动修复 | protocol.py _try_fix | ⏳ | 发送带尾部逗号的 JSON |
| RAW 命令协议 | <<<RAW>>> 包裹 shell 命令 | protocol.py | ⏳ | 发送 RAW 命令 |
| 多指令拦截 | 一次只执行一个指令 | commander.py | ⏳ | 发送多个 @@@@ |

### 1.2 工具系统
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| file_write | 写文件 | commander.py | ⏳ | 写测试文件 |
| file_read | 读文件 | commander.py | ⏳ | 读取上一步文件 |
| file_append | 追加内容 | commander.py | ⏳ | 追加内容到文件 |
| file_delete | 删除文件 | commander.py | ⏳ | 删除测试文件 |
| file_exists | 检查文件存在 | commander.py | ⏳ | 检查存在/不存在文件 |
| dir_create | 创建目录 | commander.py | ⏳ | 创建测试目录 |
| dir_list | 列出目录 | commander.py | ⏳ | 列出测试目录 |
| shell_exec | 执行 Shell 命令 | commander.py | ⏳ | 执行 echo 测试 |
| done | 结束任务（需双验证） | commander.py | ⏳ | 提交无文件的结果 |
| ask | 向用户提问 | commander.py | ⏳ | 发送 ask 指令 |
| docx_create | 生成 Word 文档 | commander.py | ⏳ | 创建 .docx 文件 |
| pptx_create | 生成 PPT | commander.py | ⏳ | 创建 .pptx 文件 |
| remember | 保存记忆 | commander.py | ⏳ | 调用 remember |
| recall | 检索记忆 | commander.py | ⏳ | 调用 recall |
| summarize | 摘要保存 | commander.py | ⏳ | 调用 summarize |
| list_summaries | 列出摘要 | commander.py | ⏳ | 调用 list_summaries |

### 1.3 浏览器自动化
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| browser_search | 网页搜索 | commander.py | ⏳ | 搜索测试 |
| browser_visit | 访问 URL | commander.py | ⏳ | 访问页面 |
| browser_screenshot | 截图 | commander.py | ⏳ | 截取当前页面 |
| browser_fill | 填写表单 | commander.py | ⏳ | 填写输入框 |
| browser_click | 点击元素 | commander.py | ⏳ | 点击按钮 |

### 1.4 子代理系统
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| browser_research | 后台研究任务 | subagent_manager.py | ⏳ | 派发研究任务 |
| check_task | 检查任务状态 | subagent_manager.py | ⏳ | 查询任务 ID |
| wait_task | 等待任务完成 | subagent_manager.py | ⏳ | 等待任务结果 |
| list_tasks | 列出所有任务 | subagent_manager.py | ⏳ | 列出活跃任务 |
| 独立 Playwright 实例 | 子代理用独立浏览器 | subagent.py | ⏳ | 观察子代理日志 |
| cookie 凭据复用 | 子代理复用登录状态 | subagent_main.py | ⏳ | 子代理是否仍需登录 |
| 日志重定向 | 子代理输出到 .log 文件 | subagent_manager.py | ⏳ | 查看 log 文件 |

### 1.5 安全与拦截
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| 纯文本拦截 | 非 @@@@ 输出自动纠正 | commander.py | ⏳ | 发送纯文本 |
| 放弃句式拦截 | 检测"由于...无法"等 13 种 | commander.py | ⏳ | AI 说放弃时的反应 |
| done 双验证 | 无文件/有错误时不放行 | commander.py | ⏳ | 提交不完整结果 |
| Ctrl+C 安全处理 | 不杀子代理 | terminal.py | ⏳ | Ctrl+C 测试 |
| Ctrl+C graceful shutdown | 优雅关闭 | terminal.py | ⏳ | 关闭时是否清理 |

### 1.6 记忆系统
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| 每 20 轮提醒 | 自动提醒保存记忆 | commander.py | ⏳ | 运行 20+ 轮 |
| 对话轮次持久化 | 记录到文件 | memory_manager.py | ⏳ | 检查记忆文件 |
| 新建任务 new | 新建任务目录 | terminal.py | ⏳ | new 命令 |

### 1.7 深度思考
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| deep/think 命令 | 切换思考模式 | terminal.py | ⏳ | 发送 deep 命令 |
| 思考内容抓取 | 显示 AI 思考过程 | session.py | ⏳ | 开启后观察 |
| 思考内容显示 | 在终端打印 | terminal.py | ⏳ | 查看终端输出 |

### 1.8 暂停与控制
| 功能 | 要求 | 代码位置 | 状态 | 验证方法 |
|------|------|----------|------|----------|
| p 命令暂停/恢复 | 暂停 Agent 运行 | terminal.py | ⏳ | p 命令 |
| quit/exit/q | 退出终端 | terminal.py | ⏳ | quit 命令 |
| clear | 清屏 | terminal.py | ⏳ | clear 命令 |

---

## 二、系统自身需要的功能

### 2.1 编码与国际化
| 功能 | 代码位置 | 状态 | 验证方法 |
|------|----------|------|----------|
| UTF-8 输出 | terminal.py | ⏳ | emoji 不乱码 |
| GBK → UTF-8 转换 | subprocess 调用 | ⏳ | web_searcher 输出 |
| 中文路径支持 | 各文件操作 | ⏳ | 中文目录/文件名 |

### 2.2 错误处理
| 功能 | 代码位置 | 状态 | 验证方法 |
|------|----------|------|----------|
| 超时处理 | subprocess timeout | ⏳ | 故意超时 |
| 异常不崩溃 | 各模块 try/except | ⏳ | 触发错误 |

### 2.3 日志与调试
| 功能 | 代码位置 | 状态 | 验证方法 |
|------|----------|------|----------|
| 工具执行日志 | _on_event terminal.py | ⏳ | 观察终端 |
| 子代理日志文件 | subagent_{id}.log | ⏳ | 查看文件 |
| 记忆文件 | memory_manager.py | ⏳ | 检查目录 |

---

## 三、逐项验证记录

### 2026-06-01 第一轮核对

#### 发现的问题

| 功能 | 状态 | 原因/修复 |
|------|------|----------|
| `done` 双验证 | 🔴 严重bug | `_validate_task_done(result)` 检查的是 `done` 工具自己的输出（"用户确认结束"），永远不含文件扩展名 → 永远返回 allowed=False。修复：改用 `self._last_tool_result` 记录最后工具输出 |
| 轮次提醒 | 🟡 错误 | `% 10 == 0`（10轮），应为 `% 20 == 0`（20轮）。已修正 |
| `file_append` 工具 | 🔴 缺失 | 用户明确提到过，但未注册。已补充 |
| `file_exists` 工具 | 🔴 缺失 | 未注册。已补充 |
| `list_tasks` 工具 | 🟡 缺失 | 未注册（subagent_manager 有 `check_all_tasks`）。已补充 `list_tasks` 工具调用 `check_all_tasks()` |
| `shell_exec` decode | 🟢 小问题 | `errors='ignore'` 应为 `errors='replace'`，已修正 |
| `done` 注册方式 | ✅ 正常 | `done` 在 `_execute_command` 里特殊处理，不需要 `_tools.register` |
| `ask` 注册方式 | ✅ 正常 | 同上 |
| `纯文本拦截` | ✅ 正常 | 有实现（cmds为空时发 NO @@@@ PROTOCOL 纠正） |
| `放弃句式拦截` | ✅ 正常 | 有实现（14种黑名单） |
| `pause 命令` | ✅ 正常 | terminal.py 用 `cmd == "p"`（双引号） |
| `signal.SIGINT` | ✅ 正常 | 有 `import signal`，PauseManager 处理 |

#### 修复后 commit: f9c8a32

#### 待人工验证（在终端测试）
```
[ ] done 验证现在能正确检查文件生成（发一个写文件任务后 done）
[ ] file_append 能正确追加内容
[ ] file_exists 能检查文件存在/不存在
[ ] list_tasks 能列出子代理任务
[ ] 20轮时才出现记忆提醒（而非10轮）
[ ] AI 说放弃时是否真正拦截（发复杂任务测试）
[ ] Ctrl+C 是否正确处理
```
