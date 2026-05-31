"""
protocol.py — 仙人掌 Agent JSON 指令协议解析器
"""
import re
import json
from typing import Optional, List, Tuple
from dataclasses import dataclass
from types import SimpleNamespace

CMD_BEGIN = "@@@@"
CMD_END = "@@@@"
RAW_BEGIN = "<<<RAW>>>"
RAW_END = "<<<RAW>>>"


@dataclass
class ParsedCommand:
    raw: str
    command: SimpleNamespace
    id: str = ""
    fixed: bool = False
    fix_note: str = ""


@dataclass
class ExecutionResult:
    id: str
    status: str
    tool: str
    output: str = ""
    error: str = ""


class Protocol:
    def __init__(self):
        self._tools: dict = {}

    def register_tool(self, name: str, spec: dict):
        self._tools[name] = spec

    # ---- 核心解析 ----
    def extract(self, text: str) -> Optional[ParsedCommand]:
        raw_cmd = self._extract_raw(text)
        if raw_cmd:
            return raw_cmd
        return self._extract_json(text)

    def _extract_raw(self, text: str) -> Optional[ParsedCommand]:
        positions = [m.start() for m in re.finditer(re.escape(RAW_BEGIN), text)]
        if len(positions) < 2:
            return None
        start = positions[0] + len(RAW_BEGIN)
        end = positions[1]
        command = text[start:end].strip()
        if not command:
            return None
        return ParsedCommand(
            raw=RAW_BEGIN + command + RAW_END,
            command=SimpleNamespace(tool="raw_shell", params={"command": command}, id=""),
        )

    def _extract_json(self, text: str) -> Optional[ParsedCommand]:
        positions = [m.start() for m in re.finditer(re.escape(CMD_BEGIN), text)]
        if len(positions) < 2:
            return None
        start = positions[0] + len(CMD_BEGIN)
        end = positions[1]
        raw = text[start:end].strip()
        if not raw:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(raw)
            return ParsedCommand(
                raw=CMD_BEGIN + raw + CMD_END,
                command=SimpleNamespace(
                    tool=obj.get("tool", obj.get("type", "")),
                    params=obj.get("params", {}),
                    id=obj.get("id", ""),
                ),
                fixed=False,
            )
        except Exception:
            fixed, note = self._try_fix(raw)
            try:
                obj = json.loads(fixed)
                return ParsedCommand(
                    raw=CMD_BEGIN + fixed + CMD_END,
                    command=SimpleNamespace(
                        tool=obj.get("tool", obj.get("type", "")),
                        params=obj.get("params", {}),
                        id=obj.get("id", ""),
                    ),
                    fixed=True,
                    fix_note=note,
                )
            except Exception:
                return None

    def extract_all(self, text: str) -> List[ParsedCommand]:
        """只返回第一个有效指令（每次一个）"""
        raw_cmd = self._extract_raw(text)
        if raw_cmd:
            return [raw_cmd]
        block = self._extract_json(text)
        return [block] if block else []

    def validate(self, block: ParsedCommand) -> tuple:
        tool = block.command.tool
        if not tool:
            return False, "缺少 tool 字段"
        if tool not in self._tools and tool != "test":
            return False, f"未注册工具: {tool}"
        return True, ""

    def wrap_result(self, result: ExecutionResult, fix_note: str = "") -> str:
        obj = {
            "id": result.id,
            "status": result.status,
            "tool": result.tool,
        }
        if result.output:
            obj["output"] = result.output
        if result.error:
            obj["error"] = result.error
        if fix_note:
            obj["_note"] = fix_note
        json_str = json.dumps(obj, ensure_ascii=False)
        return f"{CMD_BEGIN}\n{json_str}\n{CMD_END}"

    # ---- 自动修复（脚本处理，不靠 AI）----
    def _try_fix(self, raw: str) -> Tuple[str, str]:
        """
        简单修复策略：
        1. 尾部逗号 → 删除
        2. 字符串值内未转义的双引号 → 转义（修复 AI 输出中命令参数带引号的问题）
        3. 未转义的反斜杠 → 加转义
        返回 (修复后文本, 修复说明)
        """
        original = raw
        notes = []

        # 1. 尾部逗号
        if re.search(r",\s*([}\]])", raw):
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            notes.append("尾部逗号")

        # 2. 修复字符串值内未转义的双引号（如 "value with "quotes" inside"）
        def fix_quotes(s):
            lines = s.split('\n')
            result = []
            for line in lines:
                m = re.match(r'^(\s*"[^"]+":\s*")(.+?)(")(\s*[,}]?\s*)$', line)
                if m:
                    prefix, value, first_quote, suffix = m.group(1), m.group(2), m.group(3), m.group(4)
                    if '"' in value and '\\"' not in value:
                        line = prefix + value.replace('"', '\\"') + first_quote + suffix
                        notes.append("字符串引号")
                result.append(line)
            return '\n'.join(result)

        try:
            json.loads(raw)
        except json.JSONDecodeError:
            fixed = fix_quotes(raw)
            try:
                json.loads(fixed)
                raw = fixed
            except:
                pass

        # 3. 反斜杠转义：检测 \" 或 \\ 之外的 \，直接转义
        def escape_backslash(s):
            result = []
            i = 0
            while i < len(s):
                if s[i] == '\\':
                    if i + 1 < len(s):
                        next_c = s[i + 1]
                        if next_c in ('"', '\\', 'n', 't', 'r', 'u'):
                            result.append(s[i:i+2])
                            i += 2
                        else:
                            if not notes or notes[-1] != "路径反斜杠":
                                notes.append("路径反斜杠")
                            result.append('\\\\')
                            i += 1
                    else:
                        if notes and notes[-1] == "路径反斜杠":
                            pass
                        else:
                            notes.append("末尾反斜杠")
                        result.append('\\\\')
                        i += 1
                else:
                    result.append(s[i])
                    i += 1
            return ''.join(result)

        fixed = escape_backslash(raw)
        if fixed != original:
            if "路径反斜杠" not in notes and "末尾反斜杠" not in notes:
                notes.insert(0, "路径反斜杠")

        note_str = " + ".join(notes) if notes else ""
        return fixed, note_str


def wrap_message(msg_type: str, content: dict, msg_id: str = "") -> str:
    obj = {"type": msg_type, **content, "id": msg_id}
    return f"{CMD_BEGIN}\n{json.dumps(obj, ensure_ascii=False)}\n{CMD_END}"