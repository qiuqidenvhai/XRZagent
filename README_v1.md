# XRZagent v1 - 完整重构版本

## 核心特性

### 1. 结构化协议系统
- 自动识别并修复反斜杠
- 自动转义驱动器号
- JSON 格式智能纠正

### 2. 凭据管理
- 主凭据目录：`~/.xianrenzhang_agent/credentials/`
- 临时副本机制：子代理使用副本避免锁定
- 自动备份：登录时自动保存

### 3. 多模态文档
- Word（支持增量写入）
- PPT（支持增量添加幻灯片）
- PDF

### 4. 工作空间管理
- 固定工作目录：`D:/软件/XianRenZhang_workspace/`
- 任务隔离：每个任务一个文��夹
- 子代理工作区：独立管理

## 文件结构

```
v1_system/
├── core/
│   ├── protocol.py       # 协议系统
│   ├── credentials.py    # 凭据管理
│   ├── session.py        # 会话管理
│   └── browser.py        # 浏览器（待完成）
├── tools/
│   ├── document.py       # 文档生成
│   └── file_ops.py       # 文件操作（待完成）
└── agents/
    ├── mother_agent.py   # 母代理（待完成）
    └── sub_agent.py      # 子代理（待完成）
```

## 使用指南

### 协议格式

```python
@@@@
{
  "tool": "file_write",
  "params": {
    "path": "D:\\Desktop\\test.txt",
    "content": "Hello World"
  },
  "id": "cmd_001"
}
@@@@
```

### 自动纠错

- 单反斜杠 → 双反斜杠
- 驱动器 `C:\` → `C:\\`
- JSON 格式错误自动修复

## 测试状态

- [x] 协议系统
- [x] 凭据管理
- [ ] 会话管理
- [ ] 多模态文档
- [ ] 子代理系统
- [ ] 终端程序

## 下一步

1. 完成浏览器管理模块
2. 实现母/子代理逻辑
3. 终端交互程序
4. 自动化测试
