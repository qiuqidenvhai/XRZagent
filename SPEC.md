# 仙人掌 Agent — 项目规格书

## 项目概述
**名称**：仙人掌 Agent（XianRenZhang Agent）  
**核心定位**：本地桌面 AI Agent，支持多平台 LLM + 浏览器自动化 + 子代理 + 记忆管理  
**技术栈**：Python 3.13 + Playwright + 多平台 LLM (DeepSeek/通义千问/豆包/元宝/ChatGPT/Gemini/Ollama)

## 核心能力

### 1. 工具系统
| 工具 | 说明 |
|------|------|
| file_write(path, content) | 写入文件 |
| file_read(path) | 读取文件 |
| file_list(path) | 列出目录 |
| dir_create(path) | 创建目录 |
| file_delete(path) | 删除文件 |
| shell_exec(command) | 执行 Shell 命令（用 #"..."# 包裹）|
| browser_navigate(url) | 浏览器导航 |
| browser_click(selector) | 点击元素 |
| browser_fill(selector, text) | 填写表单 |
| browser_screenshot(path) | 截图 |
| browser_search(query, engine) | 网络搜索 |
| continue | 继续上一步思考 |
| remember | 触发记忆摘要 |
| recall(task_name) | 检索历史记忆 |
| summarize(summary, decisions, tasks) | 保存摘要 |
| list_summaries | 列出所有摘要 |
| list_tasks | 列出所有任务 |
| done(message) | 结束对话 |
| ask(question) | 向用户提问 |
| tool_list | 显示工具列表 |

### 2. 子代理系统
- **总工程师**（Commander）：负责任务规划、工具调度、结果整合
- **浏览器子代理**（BrowserSubAgent）：执行具体浏览器操作
- 硬限制：子代理不能调用子代理（depth=1）
- 主 Agent 可调度 browser 子代理完成复杂浏览任务
- 子代理与母代理共享浏览器 context，复用 cookie/登录状态
- 独立进程模式：子代理以独立进程运行，通过文件/通知队列与母代理通信

### 3. 多平台 LLM 支持
- **DeepSeek**：默认平台，支持深度思考、文件上传
- **通义千问**（tongyi.aliyun.com）
- **豆包**（doubao.com）
- **元宝**（yuanbao.tencent.com）
- **ChatGPT**（chat.openai.com）
- **Gemini**（gemini.google.com）
- **Ollama**（本地模型 qwen3.5:0.8b）

多平台通过 `multi_browser.py` 管理，复用母代理浏览器 context，为每个平台创建独立 page。

### 4. 记忆系统
- 使用 key-value 存储系统（JSON 文件持久化）
- 支持 `save()`, `search()`, `summarize()`, `list()`, `recall()` 操作
- 每 10 轮自动触发摘要提醒（可配置）
- 摘要格式：关键决策 + 待办任务 + 最近对话
- 持久化到 `~/XianRenZhang_tasks/{任务N}/memory/`
- `recall 任务名` 检索历史记忆

### 5. 对话文件夹
- 每次新建对话（`new` 命令）创建新文件夹：任务一、任务二、任务三...
- 文件夹结构：
  ```
  ~/XianRenZhang_tasks/
    任务一/
      memory/      # 记忆摘要
      files/       # 生成的文件
    任务二/
      ...
  ```

### 6. GUI 图形界面
- 内置 Web GUI（`gui` 命令启动）
- 深色主题，支持消息实时显示
- 侧边栏：平台切换、快捷命令、会话历史
- 通过 HTTP 服务器（端口 8090）提供 Web 界面

### 7. 会话历史追溯
- 每次对话会生成唯一的 DeepSeek URL，可通过该 URL 追溯历史
- 使用 `save_conversation()` 保存当前对话上下文
- 使用 `load_conversation(url=...)` 加载历史对话

## 协议格式
```
@@@@
{"type":"tool_call","tool":"工具名","params":{...},"id":"UUID"}
@@@@
```

## 启动方式
1. 双击 `启动仙人掌.bat`
2. 等待浏览器弹出，扫码登录 DeepSeek
3. 在终端输入指令即可

## 目录结构
```
D:\软件\XianRenZhangAgent\
  terminal.py              # 主入口
  启动仙人掌.bat            # 启动批处理
  agent_core/
    __init__.py
    protocol.py            # 协议解析器
    browser.py             # 浏览器管理（多平台深度思考支持）
    session.py             # 会话管理（历史持久化、追溯）
    commander.py           # 主控制器（多平台 LLM 适配）
    subagent.py            # 子代理系统
    subagent_manager.py    # 子代理管理器（凭据共享）
    memory_manager.py      # 记忆管理（key-value 存储）
    multi_browser.py       # 多平台浏览器管理器
    tools/__init__.py      # 工具清单
```

## 当前状态
- ✅ 核心架构完成
- ✅ 浏览器启动 + DeepSeek 登录
- ✅ 工具注册 + 协议解析
- ✅ continue / remember / recall / summarize 指令
- ✅ 子代理浏览器系统
- ✅ 任务文件夹自动创建
- ✅ 记忆摘要持久化（key-value 存储）
- ✅ 深度思考功能修复（多平台支持）
- ✅ 多平台 LLM 支持（multi_browser.py）
- ✅ GUI 图形界面（gui 命令启动）
- ✅ 更新 system prompt 适配新架构
- ✅ 更新 SPEC.md
- ⚠️ 完整端到端测试待验证（需要人工配合登录）
- ⚠️ 部分平台（元宝/Gemini）的登录检测尚未充分测试
