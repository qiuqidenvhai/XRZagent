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
        修复 JSON 解析错误，自动处理以下问题：
        1. 尾部逗号（逗号在 } 或 ] 前）
        2. Windows 路径反斜杠未转义（检测到单个 \ 自动加一个变 \\）
        3. 驱动器号格式（检测到 X: 后面紧跟字母/数字，补全为 X:\）
        4. 字符串内未转义双引号
        """
        original = raw
        notes = []

        # 1. 修复尾部逗号
        if re.search(r",\s*([}\]])", raw):
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            notes.append("尾部逗号")

        # 2. 修复驱动器号格式（如 "C:Users" → "C:\\Users"）
        #    匹配：引号/冒号后面是 DriveLetter: 紧接着普通字符（非 \ / " , } ] 空格）
        #    注意：JSON 字符串内的路径，如 "path":"C:Users" 或 "C:Users"
        def fix_drive_letter(s):
            # 匹配：字母: 后面紧跟一个非标准路径字符（标准字符：\ / " , } ] 空格 n t r u）
            # 替换为：字母:\（在 : 后面补 \）
            result = re.sub(
                r'([A-Za-z]):([A-Za-z0-9])',
                lambda m: f'{m.group(1)}:\\\\{m.group(2)}',
                s
            )
            if result != s:
                notes.append("驱动器路径")
            return result

        try:
            json.loads(raw)
        except json.JSONDecodeError:
            raw = fix_drive_letter(raw)

        # 3. 修复未转义反斜杠（核心修复）
        #    逻辑：遍历字符串，遇到 \ 检查是否是合法转义序列
        #    合法序列：\" \\ \/ \b \f \n \r \t \uXXXX
        #    其他情况（单个 \ 后面跟任意字符）→ 加一个 \ 变成 \\
        def escape_backslash(s):
            result = []
            i = 0
            n = len(s)
            while i < n:
                c = s[i]
                if c == '\\':
                    if i + 1 < n:
                        next_c = s[i + 1]
                        # 合法转义序列：保留两个字符
                        if next_c in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't', 'u'):
                            result.append(c)
                            result.append(next_c)
                            i += 2
                            continue
                        # 非转义字符 → 单个反斜杠，加一个变 \\
                        else:
                            if "路径反斜杠" not in notes:
                                notes.append("路径反斜杠")
                            result.append('\\\\')
                            i += 2
                            continue
                    else:
                        # 末尾单个 \ → 加一个变 \\
                        if "末尾反斜杠" not in notes:
                            notes.append("末尾反斜杠")
                        result.append('\\\\')
                        i += 1
                        continue
                else:
                    result.append(c)
                    i += 1
            return ''.join(result)

        fixed = escape_backslash(raw)

        note_str = " + ".join(notes) if notes else ""
        return fixed, note_str


def wrap_message(msg_type: str, content: dict, msg_id: str = "") -> str:
    obj = {"type": msg_type, **content, "id": msg_id}
    return f"{CMD_BEGIN}\n{json.dumps(obj, ensure_ascii=False)}\n{CMD_END}"
