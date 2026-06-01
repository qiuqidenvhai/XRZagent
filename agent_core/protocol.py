"""
protocol.py — 乔人掌 Agent JSON 指令协议解析器
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
            return False, "未注册工具: " + tool
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
        return CMD_BEGIN + "\n" + json_str + "\n" + CMD_END

    def _try_fix(self, raw: str) -> Tuple[str, str]:
        original = raw
        notes = []

        # 1. 尾部逗号
        trailing_comma = re.search(r",\s*([}\]])", raw)
        if trailing_comma:
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            notes.append("尾部逗号")

        # 2. 驱动器号转义（始终执行，因为 Python json 可能把 \t 当作 tab）
        if re.search(r'[A-Za-z]:[A-Za-z0-9]', raw):
            raw = re.sub(r'([A-Za-z]):([A-Za-z0-9])', lambda m: m.group(1) + ":\\" + m.group(2), raw)
            notes.append("驱动器路径")

        # 3. 未转义反斜杠
        def escape_one(s):
            result = []
            i = 0
            n = len(s)
            while i < n:
                c = s[i]
                if c != '\\':
                    result.append(c)
                    i += 1
                    continue
                if i + 1 >= n:
                    if "末尾反斜杠" not in notes:
                        notes.append("末尾反斜杠")
                    result.append('\\\\')
                    i += 1
                    continue
                next_c = s[i + 1]
                if next_c in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't'):
                    result.append(s[i:i+2])
                    i += 2
                    continue
                if next_c == 'u':
                    if i + 5 < n and all(ch in '0123456789abcdefABCDEF' for ch in s[i+2:i+6]):
                        result.append(s[i:i+6])
                        i += 6
                        continue
                    if "路径反斜杠" not in notes:
                        notes.append("路径反斜杠")
                    result.append('\\\\')
                    i += 2
                    continue
                if "路径反斜杠" not in notes:
                    notes.append("路径反斜杠")
                result.append('\\\\')
                i += 2
            return ''.join(result)

        fixed = escape_one(raw)
        if fixed != original:
            if "路径反斜杠" not in notes and "末尾反斜杠" not in notes:
                notes.insert(0, "路径反斜杠")

        note_str = " + ".join(notes) if notes else ""
        return fixed, note_str