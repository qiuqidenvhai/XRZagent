"""session.py - 会话管理"""
import json
from pathlib import Path
from typing import Optional, Dict

class Session:
    def __init__(self, work_dir: str):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.work_dir / "conversation.json"
        self.messages = self._load_history()
    
    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self._save_history()
    
    def get_history(self) -> list:
        return self.messages
    
    def _load_history(self) -> list:
        if self.history_file.exists():
            return json.loads(self.history_file.read_text())
        return []
    
    def _save_history(self) -> None:
        self.history_file.write_text(json.dumps(self.messages, ensure_ascii=False, indent=2))
