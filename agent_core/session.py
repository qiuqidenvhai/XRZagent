"""
session.py — DeepSeek 会话管理
支持多平台、会话历史持久化和追溯
"""
import asyncio
import logging
import json
from typing import Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("session")


# ============================================================
# 对话历史索引（全局持久化）
# ============================================================

_CONVERSATION_INDEX_PATH = Path.home() / ".xianrenzhang_agent" / "conversation_index.json"


@dataclass
class Message:
    """单条消息"""
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class ConversationRecord:
    """单次对话记录（含URL追溯）"""
    platform: str
    session_id: str
    url: str
    messages: List[Message]
    created_at: str
    tags: List[str] = None

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "session_id": self.session_id,
            "url": self.url,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "created_at": self.created_at,
            "tags": self.tags or [],
        }


class ConversationHistory:
    """对话历史管理器 - 持久化到 ~\xianrenzhang_agent\conversation_index.json

    每次完成一轮或多轮对话后，自动调用 save() 持久化。
    用户可以通过 history.search(query) / history.get_by_url(url) 追溯历史。
    """

    def __init__(self):
        self._records: List[ConversationRecord] = []
        self._load_index()

    def _load_index(self):
        if _CONVERSATION_INDEX_PATH.exists():
            try:
                data = json.loads(_CONVERSATION_INDEX_PATH.read_text(encoding="utf-8"))
                for item in data:
                    msgs = [Message(role=m["role"], content=m["content"])
                            for m in item.get("messages", [])]
                    rec = ConversationRecord(
                        platform=item["platform"],
                        session_id=item["session_id"],
                        url=item["url"],
                        messages=msgs,
                        created_at=item["created_at"],
                        tags=item.get("tags", []),
                    )
                    self._records.append(rec)
                logger.info(f"已加载 {len(self._records)} 条对话历史")
            except Exception as e:
                logger.warning(f"加载对话历史失败：{e}")

    def _save_index(self):
        _CONVERSATION_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = [rec.to_dict() for rec in self._records]
        _CONVERSATION_INDEX_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_record(self, platform: str, session_id: str, url: str,
                   messages: List[Message], tags: List[str] = None) -> ConversationRecord:
        """添加一条新对话记录"""
        rec = ConversationRecord(
            platform=platform,
            session_id=session_id,
            url=url,
            messages=messages,
            created_at=datetime.now().isoformat(),
            tags=tags or [],
        )
        self._records.append(rec)
        self._save_index()
        return rec

    def search(self, query: str, platform: str = None,
               tags: List[str] = None) -> List[ConversationRecord]:
        """全文搜索对话历史"""
        results = []
        for rec in self._records:
            if platform and rec.platform != platform:
                continue
            if tags and not any(t in rec.tags for t in tags):
                continue
            for msg in rec.messages:
                if query in msg.content:
                    results.append(rec)
                    break
        return results

    def get_by_url(self, url: str) -> Optional[ConversationRecord]:
        for rec in self._records:
            if rec.url == url:
                return rec
        return None

    def get_latest(self, platform: str = None) -> Optional[ConversationRecord]:
        records = [r for r in self._records if not platform or r.platform == platform]
        return max(records, key=lambda r: r.created_at) if records else None

    def list_records(self, platform: str = None, limit: int = 10) -> List[ConversationRecord]:
        records = [r for r in self._records if not platform or r.platform == platform]
        return records[-limit:]


# 全局单例
_conv_history: Optional[ConversationHistory] = None


def get_conversation_history() -> ConversationHistory:
    """获取全局对话历史单例"""
    global _conv_history
    if _conv_history is None:
        _conv_history = ConversationHistory()
    return _conv_history


# ============================================================
# 会话配置
# ============================================================

class SessionConfig:
    def __init__(self, quick_mode: bool = True, model: str = "deepseek",
                 thinking_mode: bool = False):
        self.quick_mode = quick_mode
        self.model = model
        self.thinking_mode = thinking_mode


# ============================================================
# DeepSeek 会话管理
# ============================================================

class DeepSeekSession:
    """管理多轮对话上下文，支持会话历史自动持久化"""

    def __init__(self, browser_manager, config: Optional[SessionConfig] = None):
        self._bm = browser_manager
        self.config = config or SessionConfig()
        self._logged_in = False
        self._messages: List[Message] = []
        self._thinking_mode = False
        self._session_id = ""
        # 对话历史管理器
        self._history = get_conversation_history()

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def thinking_mode(self) -> bool:
        return self._thinking_mode

    @property
    def session_id(self) -> str:
        return self._session_id

    def toggle_thinking(self):
        """切换深度思考模式"""
        self._thinking_mode = not self._thinking_mode
        logger.info(f"思考模式切换为: {'深度思考' if self._thinking_mode else '快速模式'}")

    async def set_deep_think(self, enable: bool):
        """控制浏览器上的深度思考按钮"""
        if self._thinking_mode != enable:
            self._thinking_mode = enable
            await self._bm.toggle_deep_think(enable=enable)
            logger.info(f"深度思考模式 {'开启' if enable else '关闭'}")

    async def initialize(self):
        """初始化会话（检查/等待登录）"""
        if self._bm._browser is None:
            await self._bm.launch()
        await self._bm.navigate()
        self._logged_in = await self._bm.check_login()
        if not self._logged_in:
            logger.warning("DeepSeek 未登录，等待扫码...")
            self._logged_in = await self._bm.wait_login()
        else:
            logger.info("DeepSeek 已登录")
        await self._bm.save_cookies()

    def set_system_prompt(self, system_prompt: str):
        """设置系统提示词"""
        for i, msg in enumerate(self._messages):
            if msg.role == "system":
                self._messages[i] = Message(role="system", content=system_prompt)
                logger.info("系统提示词已替换")
                return
        self._messages.insert(0, Message(role="system", content=system_prompt))
        logger.info("系统提示词已设置")

    async def send(self, text: str) -> str:
        """发送消息并获取回复（含自动历史持久化）"""
        if not self._logged_in:
            await self.initialize()

        # 纯协议消息（内部工具调用）
        if text.strip().startswith("@@@@"):
            sent = await self._bm._send_internal(text)
            if not sent:
                raise RuntimeError("内部消息发送失败")
            response = await self._bm.wait_response() or "（未收到回复）"
            self._messages.append(Message(role="assistant", content=response))
            return response

        # 常规消息
        self._messages.append(Message(role="user", content=text))

        # 构建上下文
        full_context = self._build_context_for_send()
        sent = await self._bm.send_message(full_context)
        if not sent:
            raise RuntimeError("消息发送失败")

        await self._bm.save_cookies()

        response = await self._bm.wait_response()
        if response:
            self._messages.append(Message(role="assistant", content=response))
            await self._bm.save_cookies()
        else:
            response = "（未收到回复）"

        logger.info(f"对话完成，历史 {len(self._messages)} 条")

        # ===== 自动持久化 =====
        self._maybe_save_conversation()
        return response

    def _maybe_save_conversation(self):
        """每 5 轮或会话结束时自动持久化"""
        user_count = sum(1 for m in self._messages if m.role == "user")
        if user_count % 5 == 0 or user_count == 0:
            self._do_save_conversation()

    def _do_save_conversation(self):
        """实际执行持久化"""
        if not self._session_id:
            self._generate_session_id()
        url = self.get_current_url()
        self._history.add_record(
            platform="deepseek",
            session_id=self._session_id,
            url=url,
            messages=list(self._messages),
            tags=[],
        )
        logger.info(f"对话已自动持久化 (session={self._session_id})")

    def _generate_session_id(self):
        """生成唯一会话ID"""
        import hashlib
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snippet = "_".join([m.content[:30] for m in self._messages[:3]])
        self._session_id = hashlib.md5(f"{ts}_{snippet}".encode()).hexdigest()[:12]
        return self._session_id

    def _build_context_for_send(self) -> str:
        """构建完整上下文用于发送到浏览器"""
        lines = []
        for msg in self._messages:
            if msg.role == "system":
                lines.append(f"[系统提示]\n{msg.content}\n{'='*40}")
            elif msg.role == "user":
                lines.append(f"[用户] {msg.content}")
            elif msg.role == "assistant":
                lines.append(f"[助手] {msg.content[:500]}")
        return "\n\n".join(lines)

    def get_current_url(self) -> str:
        if self._bm and hasattr(self._bm, '_page') and self._bm._page:
            return self._bm._page.url
        return ""

    def save_conversation(self, file_path: str = None) -> str:
        """手动保存对话到本地 JSON 文件"""
        if file_path is None:
            task_root = Path.home() / "XianRenZhang_tasks"
            task_root.mkdir(exist_ok=True)
            if hasattr(self, '_task_name') and self._task_name:
                task_dir = task_root / self._task_name
            else:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                task_dir = task_root / f"conversation_{ts}"
            task_dir.mkdir(parents=True, exist_ok=True)
            file_path = str(task_dir / "conversation.json")

        data = {
            "url": self.get_current_url(),
            "messages": [{"role": m.role, "content": m.content} for m in self._messages],
            "session_id": self._session_id,
        }
        Path(file_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"对话已保存到 {file_path}")
        return file_path

    def load_conversation(self, file_path: str) -> bool:
        """从文件加载对话历史"""
        try:
            data = json.loads(Path(file_path).read_text(encoding="utf-8"))
            self._messages.clear()
            for m in data.get("messages", []):
                self._messages.append(Message(role=m["role"], content=m["content"]))
            logger.info(f"对话已从 {file_path} 加载，共 {len(self._messages)} 条消息")
            return True
        except Exception as e:
            logger.warning(f"加载对话失败：{e}")
            return False

    def clear_history(self):
        """清空当前会话历史"""
        self._messages.clear()
        self._session_id = ""

    def rebuild_context_prompt(self) -> str:
        """重建上下文提示（最近20条）"""
        recent = self._messages[-20:]
        lines = []
        for msg in recent:
            role = "用户" if msg.role == "user" else "助手"
            lines.append(f"「{role}」{msg.content[:300]}")
        return "\n".join(lines)
