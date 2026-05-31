"""
tools/__init__.py — 工具注册表（内置工具）
所有工具由 Commander 在初始化时注册，此文件仅作参考备份
"""
# 工具定义参考（实际注册在 commander.py 的 _register_builtin_tools 中）
TOOL_MANIFEST = [
    # 文件操作
    ("file_write", "写入文件", ["path", "content"]),
    ("file_read", "读取文件", ["path"]),
    ("file_list", "列出目录", ["path"]),
    ("dir_create", "创建目录", ["path"]),
    ("file_delete", "删除文件", ["path"]),
    # Shell
    ("shell_exec", "执行Shell命令", ["command"]),
    # 浏览器,
    ("browser_click", "点击元素", ["selector"]),
    ("browser_fill", "填写表单", ["selector", "text"]),
    ("browser_screenshot", "截图", ["path"]),
    ("browser_search", "搜索", ["query", "engine"]),
    # 特殊指令
    ("continue", "继续思考", []),
    ("remember", "整理记忆", []),
    ("recall", "检索记忆", ["task_name"]),
    ("summarize", "保存摘要", ["summary", "decisions", "tasks"]),
    ("list_summaries", "列出摘要", []),
    ("list_tasks", "列出任务", []),
    ("done", "完成", ["message"]),
    ("ask", "提问", ["question"]),
    ("tool_list", "工具列表", []),
]
