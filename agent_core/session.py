"""
session.py — DeepSeek 会话管理
"""
import asyncio
import logging
from typing import Optional, List, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("session")


class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    role: MessageRole
    content: str


@dataclass
class SessionConfig:
    quick_mode: bool = True
    model: str = "deepseek"
    thinking_mode: bool = False  # False=快速模式 True=深度思考


class DeepSeekSession:
    """管理 DeepSeek 多轮对话上下文"""

    def __init__(self, bm, config: Optional[SessionConfig] = None):
        self._bm = bm
        self.config = config or SessionConfig()
        self._logged_in = False
        self._messages: List[Message] = []
        self._history_len = 0
        self._thinking_mode = False  # False=快速模式 True=深度思考

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def thinking_mode(self) -> bool:
        return self._thinking_mode

    def toggle_thinking(self):
        """切换深度思考模式（深度思考=慢速，输出推理过程）
        
        注意：此方法只切换内部标志，实际的浏览器按钮由 Commander 或 Terminal 控制
        """
        self._thinking_mode = not self._thinking_mode
        logger.info(f"思考模式切换为: {'深度思考' if self._thinking_mode else '快速模式'}")

    async def set_deep_think(self, enable: bool):
        """设置深度思考模式（实际控制浏览器按钮）
        
        由 Commander 调用，当 AI 决定需要深度思考时开启，
        DeepSeek 输出完成后自动关闭
        """
        if self._thinking_mode != enable:
            self._thinking_mode = enable
            await self._bm.toggle_deep_think(enable=enable)
            logger.info(f"深度思考模式 {'开启' if enable else '关闭'}")

    async def initialize(self):
        """初始化会话（重用已有 bm，不重复 launch）"""
        if self._bm._browser is None:
            await self._bm.launch()
        await self._bm.navigate()
        self._logged_in = await self._bm.check_login()
        if not self._logged_in:
            logger.warning("DeepSeek 未登录，等待扫码...")
            self._logged_in = await self._bm.wait_login()
        else:
            logger.info("DeepSeek 已登录，保存 cookie 供子代理使用")
            # 已登录也要保存 cookie，这样子代理可以复用
            await self._bm.save_cookies()

    def set_system_prompt(self, system_prompt: str):
        """设置系统提示词（作为第一条消息）"""
        # 如果第一条是 system 消息，替换它；否则插入到开头
        if self._messages and self._messages[0].role == MessageRole.SYSTEM:
            self._messages[0] = Message(role=MessageRole.SYSTEM, content=system_prompt)
        else:
            self._messages.insert(0, Message(role=MessageRole.SYSTEM, content=system_prompt))
        logger.info("系统提示词已设置")

    def _is_complex_task(self, text: str) -> bool:
        """判断是否为复杂任务，需要开启深度思考"""
        complex_keywords = [
            "分析", "研究", "调研", "报告", "总结", "归纳",
            "比较", "对比", "评估", "优化", "设计", "架构",
            "复杂", "详细", "深入", "全面", "系统",
            "代码", "程序", "算法", "逻辑", "实现",
            "问题", "解决", "方案", "策略", "规划",
        ]
        text_lower = text.lower()
        # 检查关键词
        keyword_count = sum(1 for kw in complex_keywords if kw in text_lower)
        # 长文本也可能是复杂任务
        is_long = len(text) > 200
        return keyword_count >= 2 or is_long

    async def send(self, text: str, on_thinking: Optional[Callable] = None,
                  continuation: Optional[str] = None,
                  auto_think: bool = True) -> str:
        """发送消息并获取回复。
        
        Args:
            text: 要发送的消息
            on_thinking: 思考过程中的回调
            continuation: 继续对话的上下文
            auto_think: 是否自动根据任务复杂度切换深度思考模式
        """
        if not self._logged_in:
            await self.initialize()

        if text.strip().startswith("@@@@"):
            sent = await self._bm._send_internal(text)
            if not sent:
                raise RuntimeError("内部消息发送失败")
            response = await self._bm.wait_response()
            if response:
                self._messages.append(Message(role=MessageRole.ASSISTANT, content=response))
            else:
                response = "（未收到回复）"
            return response

        if continuation:
            text = text + "\n\n" + continuation
        self._messages.append(Message(role=MessageRole.USER, content=text))

        # 不再自动开启深度思考，由 DeepSeek 自行决定
        # 构建完整上下文（包含系统提示词和历史消息）
        # 对于网页版 DeepSeek，需要把所有上下文一起发送
        full_context = self._build_context_for_send()
        sent = await self._bm.send_message(full_context)
        if not sent:
            raise RuntimeError("消息发送失败")

        # 每次发送后保存 cookie（防止中途丢失）
        await self._bm.save_cookies()

        response = await self._bm.wait_response()
        if response:
            self._messages.append(Message(role=MessageRole.ASSISTANT, content=response))
            # 回复后也保存 cookie
            await self._bm.save_cookies()
        else:
            response = "（未收到回复）"

        logger.info(f"对话完成，历史 {len(self._messages)} 条")
        return response

    def _build_context_for_send(self) -> str:
        """构建发送给浏览器的完整上下文"""
        lines = []
        
        # 添加系统提示词（如果有）
        for msg in self._messages:
            if msg.role == MessageRole.SYSTEM:
                lines.append(f"[系统提示]\n{msg.content}")
                lines.append("" + "="*40)
                break
        
        # 添加历史对话（最多最近10轮，不包括系统消息）
        history_msgs = [m for m in self._messages if m.role != MessageRole.SYSTEM]
        recent = history_msgs[-10:] if len(history_msgs) > 10 else history_msgs
        
        for msg in recent:
            if msg.role == MessageRole.USER:
                lines.append(f"[用户] {msg.content}")
            elif msg.role == MessageRole.ASSISTANT:
                lines.append(f"[助手] {msg.content[:500]}")  # 助手回复截短
        
        return "\n\n".join(lines)

    def rebuild_context_prompt(self) -> str:
        """重建上下文提示（最近20条）"""
        recent = self._messages[-20:] if len(self._messages) > 20 else self._messages
        lines = []
        for msg in recent:
            role = "用户" if msg.role == MessageRole.USER else "助手"
            lines.append(f"「{role}」{msg.content[:300]}")
        return "\n".join(lines)

    def get_last_conv_url(self) -> str:
        """从最近保存的对话文件读取 URL，返回 None 表示无保存记录"""
        import json
        from pathlib import Path
        task_root = Path.home() / "XianRenZhang_tasks"
        if not task_root.exists():
            return None
        # 找最新修改的任务目录
        dirs = sorted([d for d in task_root.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs:
            conv_file = d / "conversation.json"
            if conv_file.exists():
                try:
                    data = json.loads(conv_file.read_text(encoding="utf-8"))
                    url = data.get("url", "")
                    # 验证是 DeepSeek URL
                    if url and "deepseek" in url.lower():
                        return url
                except Exception:
                    pass
        return None

    def get_history(self) -> List[Message]:
        return list(self._messages)

    def clear_history(self):
        """清空对话历史"""
        self._messages.clear()
        self._history_len = 0

    def get_current_url(self) -> str:
        """获取当前 DeepSeek 对话的 URL"""
        if self._bm and self._bm._page:
            return self._bm._page.url
        return ""

    def save_conversation(self, file_path: str = None) -> str:
        """保存对话到文件（含 URL 和所有消息）
        
        Args:
            file_path: 保存路径，默认使用当前任务目录
            
        Returns:
            保存的文件路径
        """
        import json
        from pathlib import Path
        
        if file_path is None:
            task_root = Path.home() / "XianRenZhang_tasks"
            task_root.mkdir(exist_ok=True)
            # 找到当前任务目录
            if hasattr(self, '_task_name') and self._task_name:
                task_dir = task_root / self._task_name
            else:
                # 使用时间戳命名
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                task_dir = task_root / f"conversation_{ts}"
            task_dir.mkdir(parents=True, exist_ok=True)
            conv_file = task_dir / "conversation.json"
        else:
            conv_file = Path(file_path)
        
        data = {
            "url": self.get_current_url(),
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in self._messages if m.role != MessageRole.SYSTEM
            ],
            "system_prompt": next((m.content for m in self._messages if m.role == MessageRole.SYSTEM), ""),
        }
        
        conv_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"对话已保存到 {conv_file}")
        return str(conv_file)
    
    def load_conversation(self, file_path: str = None, url: str = None) -> bool:
        """从文件加载对话
        
        Args:
            file_path: 对话文件路径
            url: 可选的 DeepSeek 对话 URL（如果不从文件读取）
            
        Returns:
            是否成功
        """
        import json
        from pathlib import Path
        
        if file_path is None:
            return False
        
        try:
            data = json.loads(Path(file_path).read_text(encoding="utf-8"))
            
            # 加载消息
            self._messages.clear()
            if data.get("system_prompt"):
                self._messages.append(Message(role=MessageRole.SYSTEM, content=data["system_prompt"]))
            for m in data.get("messages", []):
                self._messages.append(Message(role=MessageRole.USER if m["role"] == "user" else MessageRole.ASSISTANT, content=m["content"]))
            
            logger.info(f"对话已从 {file_path} 加载，共 {len(self._messages)} 条消息")
            return True
        except Exception as e:
            logger.warning(f"加载对话失败：{e}")
            return False

    async def analyze_image(self, image_path: str, prompt: str = "描述这张图片的内容") -> str:
        import os, base64, json, urllib.request

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return "错误: 需要设置 DEEPSEEK_API_KEY 环境变量"

        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return f"错误: 无法读取图片 {image_path}: {e}"

        data = json.dumps({
            "model": "deepseek-chat",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": prompt}
                ]
            }]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=data,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            return f"错误: API 调用失败: {e}"
