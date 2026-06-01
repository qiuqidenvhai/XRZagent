# XRZagent — 仙人掌 Agent

基于 DeepSeek + Playwright 的本地桌面 Agent 系统。

## 功能清单

| 功能 | 状态 | 说明 |
|------|------|------|
| DeepSeek 驱动 | ✅ | 通过浏览器自动化与 DeepSeek 对话 |
| 工具注册系统 | ✅ | 20+ 内置工具（文件/浏览器/子代理/记忆/文档） |
| JSON 协议解析 | ✅ | @@@@ 包裹符，自动修复反斜杠/驱动器号 |
| 纯文本检测拦截 | ✅ | 自动纠正未使用协议的 AI 输出 |
| 放弃句式拦截 | ✅ | 13种黑名单模式，防止 AI 找借口放弃 |
| 任务完成验证 | ✅ | done() 前验证文件是否生成 |
| 深度思考模式 | ✅ | deep/think 命令切换 |
| 暂停/恢复 | ✅ | p 命令暂停 Agent |
| 记忆系统 | ✅ | remember/recall/summarize/list_summaries |
| 子代理系统 | ⚠️ | 独立进程，有独立浏览器，需登录1次 |
| 多模态文档 | ⚠️ | docx/pptx 生成，中文编码待验证 |
| GitHub 同步 | ✅ | 每次修复后推送 |

## 已发现/未解决问题

- [ ] `python-docx` 中文编码问题（生成 .docx 时报错）
- [ ] 子代理需要独立登录（cookie 复用有时失效）
- [ ] 深度思考内容抓取（选择器待适配新版 DeepSeek）
- [ ] Ctrl+C 处理（目前可能传播到子进程）
- [ ] `make.bat` 乱码（编码问题未修复）

## 快速启动

```bash
cd D:\软件\XianRenZhangAgent
python terminal.py
```

## 项目结构

```
XianRenZhangAgent/
├── terminal.py          # 主入口
├── subagent_main.py      # 子代理进程入口
├── web_searcher.py       # 网页搜索工具
├── SPEC.md               # 协议规范
├── agent_core/
│   ├── commander.py      # 主控制器
│   ├── session.py        # DeepSeek 会话
│   ├── browser.py        # 浏览器管理
│   ├── protocol.py       # 协议解析
│   ├── subagent_manager.py  # 子代理管理
│   ├── subagent.py       # 子代理基类
│   └── memory_manager.py # 记忆管理
```

## 协议格式

```
@@@@
{"tool": "工具名", "params": {}, "id": "1"}
@@@@
```

## 更新日志

### v0.2 (2026-06-01)
- 修复：语法修复系统（路径反斜杠、驱动器号）
- 修复：终端显示思考内容和命令执行过程
- 修复：放弃句式拦截（13种黑名单）
- 修复：任务完成验证（done 拦截）
- 修复：commander.py 错误 import
- 修复：subagent.py 重复类定义
- 修复：subagent_manager.py 进程无人监控问题
