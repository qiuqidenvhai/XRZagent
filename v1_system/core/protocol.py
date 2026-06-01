"""
protocol.py - 结构化协议系统（核心）
- 协议格式：@@@@ ... @@@@
- 自动纠错：反斜杠、驱动器、JSON 格式
- 语法检测：智能识别错误类型
"""
import json
import re
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum


class ProtocolError(Enum):
    """协议错误类型"""
    SINGLE_BACKSLASH = "单反斜杠"
    INVALID_JSON = "JSON格式错误"
    MISSING_PARAMS = "缺少参数"
    MULTIPLE_COMMANDS = "多行命令"
    UNESCAPED_DRIVE = "驱动器未转义"


@dataclass
class Command:
    """解析后的命令"""
    tool: str
    params: Dict
    cmd_id: str
    raw: str
    error: Optional[ProtocolError] = None


class ProtocolParser:
    """协议解析器"""
    
    DELIMITER = "@@@@"
    PATTERN = r'@@@@\s*\n?(.*?)\n?@@@@'
    
    @staticmethod
    def extract_commands(text: str) -> List[str]:
        """从文本中提取所有命令块"""
        matches = re.findall(ProtocolParser.PATTERN, text, re.DOTALL)
        return matches
    
    @staticmethod
    def parse_command(cmd_text: str) -> Tuple[bool, Optional[Command], Optional[str]]:
        """
        解析单个命令
        返回: (成功, 命令对象, 错误信息/修复说明)
        """
        cmd_text = cmd_text.strip()
        
        # 检测多行命令（一次只能一个）
        if cmd_text.count('\n') > 2:
            return False, None, f"检测到多行命令，请一次只输出一个操作"
        
        # 自动修复常见错误
        fixed_text, corrections = ProtocolParser._auto_correct(cmd_text)
        
        # 尝试解析 JSON
        try:
            data = json.loads(fixed_text)
        except json.JSONDecodeError as e:
            return False, None, f"JSON解析失败: {str(e)}\n原文本:\n{fixed_text}"
        
        # 验证必要字段
        if "tool" not in data:
            return False, None, "缺少 'tool' 字段"
        
        if "params" not in data:
            data["params"] = {}
        
        cmd = Command(
            tool=data["tool"],
            params=data.get("params", {}),
            cmd_id=data.get("id", ""),
            raw=cmd_text,
            error=None
        )
        
        return True, cmd, corrections
    
    @staticmethod
    def _auto_correct(text: str) -> Tuple[str, str]:
        """
        自动修复常见错误
        返回: (修复后的文本, 修复说明)
        """
        corrections = []
        original = text
        
        # 修复 1: 单反斜杠 -> 双反斜杠
        # 匹配 C:\ 或 D:\ 这种模式但只有一个反斜杠的情况
        if '\\' in text:
            # 先计算需要修复的反斜杠
            single_slash_pattern = r'(?<!\\)\\(?!\\)(?=[A-Za-z0-9_\-"'\'])'
            if re.search(single_slash_pattern, text):
                text = re.sub(single_slash_pattern, r'\\\\', text)
                corrections.append("修复单反斜杠")
        
        # 修复 2: 修复驱动器号（C:\ 应该是 C:\\）
        text = re.sub(r'([A-Z]:)\\(?!\\)', r'\1\\\\', text)
        if text != original:
            corrections.append("修复驱动器路径")
        
        # 修复 3: 修复常见的 JSON 错误 - 尾部多余逗号
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # 修复 4: 修复引号问题 - 中文引号 -> 英文引号
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        
        return text, " | ".join(corrections) if corrections else ""
    
    @staticmethod
    def format_command(tool: str, params: Dict, cmd_id: str = "") -> str:
        """格式化输出命令"""
        cmd = {
            "tool": tool,
            "params": params,
            "id": cmd_id or "auto"
        }
        json_str = json.dumps(cmd, ensure_ascii=False, indent=2)
        return f"@@@@\n{json_str}\n@@@@"


class ProtocolValidator:
    """协议验证器"""
    
    # 工具白名单
    VALID_TOOLS = [
        "file_write", "file_read", "file_delete", "dir_create",
        "file_list", "shell_exec", "browser_navigate", "browser_click",
        "browser_fill", "browser_screenshot", "browser_get_text",
        "doc_create_word", "doc_add_content_word", "doc_save",
        "doc_create_ppt", "doc_add_slide_ppt", "doc_save_ppt",
        "doc_create_pdf", "doc_add_content_pdf", "doc_save_pdf",
        "continue", "remember", "recall", "summarize",
        "spawn_subagent", "ask", "done", "list_tasks"
    ]
    
    @staticmethod
    def validate(cmd: Command) -> Tuple[bool, Optional[str]]:
        """验证命令有效性"""
        
        if cmd.tool not in ProtocolValidator.VALID_TOOLS:
            return False, f"未知工具: {cmd.tool}"
        
        # 工具特定验证
        if cmd.tool == "file_write":
            if "path" not in cmd.params:
                return False, "file_write 缺少 path 参数"
            if "content" not in cmd.params:
                return False, "file_write 缺少 content 参数"
        
        elif cmd.tool == "file_read":
            if "path" not in cmd.params:
                return False, "file_read 缺少 path 参数"
        
        elif cmd.tool == "shell_exec":
            if "command" not in cmd.params:
                return False, "shell_exec 缺少 command 参数"
        
        elif cmd.tool == "browser_click":
            if "selector" not in cmd.params:
                return False, "browser_click 缺少 selector 参数"
        
        elif cmd.tool == "spawn_subagent":
            if "query" not in cmd.params:
                return False, "spawn_subagent 缺少 query 参数"
        
        return True, None
