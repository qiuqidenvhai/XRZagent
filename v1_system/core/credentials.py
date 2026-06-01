"""
credentials.py - 凭据管理系统
关键特性：
- 主凭据目录：~/.xianrenzhang_agent/credentials/（永不移动）
- 临时副本：子代理使用副本，避免锁定主凭据
- 自动备份：登录时自动保存凭据
"""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict


class CredentialsManager:
    """凭据管理器"""
    
    # 主凭据目录（固定位置，永不移动）
    CREDS_ROOT = Path.home() / ".xianrenzhang_agent" / "credentials"
    COOKIE_FILE = CREDS_ROOT / "deepseek_cookies.json"
    SESSION_FILE = CREDS_ROOT / "session_info.json"
    
    def __init__(self):
        """初始化凭据目录"""
        self.CREDS_ROOT.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def get_creds_root() -> Path:
        """获取主凭据目录"""
        return CredentialsManager.CREDS_ROOT
    
    @staticmethod
    def save_cookies(cookies: list, backup: bool = True) -> bool:
        """
        保存 cookies
        :param cookies: cookies 列表
        :param backup: 是否备份旧 cookies
        :return: 是否成功
        """
        try:
            CredentialsManager.CREDS_ROOT.mkdir(parents=True, exist_ok=True)
            
            # 备份旧凭据
            if backup and CredentialsManager.COOKIE_FILE.exists():
                backup_file = CredentialsManager.CREDS_ROOT / "deepseek_cookies.bak.json"
                shutil.copy2(CredentialsManager.COOKIE_FILE, backup_file)
            
            # 保存新凭据
            CredentialsManager.COOKIE_FILE.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception as e:
            print(f"[CredentialsManager] 保存 cookies 失败: {e}")
            return False
    
    @staticmethod
    def load_cookies() -> Optional[list]:
        """加载 cookies"""
        if CredentialsManager.COOKIE_FILE.exists():
            try:
                return json.loads(
                    CredentialsManager.COOKIE_FILE.read_text(encoding="utf-8")
                )
            except Exception as e:
                print(f"[CredentialsManager] 加载 cookies 失败: {e}")
        return None
    
    @staticmethod
    def is_logged_in() -> bool:
        """检查是否已登录"""
        cookies = CredentialsManager.load_cookies()
        if not cookies or not isinstance(cookies, list):
            return False
        return len(cookies) > 2
    
    @staticmethod
    def save_session_info(info: Dict) -> bool:
        """保存会话信息"""
        try:
            CredentialsManager.CREDS_ROOT.mkdir(parents=True, exist_ok=True)
            CredentialsManager.SESSION_FILE.write_text(
                json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception as e:
            print(f"[CredentialsManager] 保存会话信息失败: {e}")
            return False
    
    @staticmethod
    def load_session_info() -> Optional[Dict]:
        """加载会话信息"""
        if CredentialsManager.SESSION_FILE.exists():
            try:
                return json.loads(
                    CredentialsManager.SESSION_FILE.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        return None
    
    @staticmethod
    def create_temp_copy(prefix: str = "subagent") -> Path:
        """
        为子代理创建临时凭据副本
        :param prefix: 临时目录前缀
        :return: 临时凭据目录路径
        """
        import tempfile
        
        temp_dir = Path(tempfile.mkdtemp(prefix=f"{prefix}_cred_"))
        
        # 复制 cookies
        if CredentialsManager.COOKIE_FILE.exists():
            shutil.copy2(
                CredentialsManager.COOKIE_FILE,
                temp_dir / "deepseek_cookies.json"
            )
        
        # 复制 session info
        if CredentialsManager.SESSION_FILE.exists():
            shutil.copy2(
                CredentialsManager.SESSION_FILE,
                temp_dir / "session_info.json"
            )
        
        return temp_dir
    
    @staticmethod
    def cleanup_temp_copy(temp_dir: Path) -> bool:
        """清理临时凭据副本"""
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            return True
        except Exception as e:
            print(f"[CredentialsManager] 清理临时凭据失败: {e}")
            return False


class WorkspaceManager:
    """工作空间管理器"""
    
    # 工作空间根目录
    WORKSPACE_ROOT = Path("D:/软件/XianRenZhang_workspace") if Path("D:/").exists() else (Path.home() / "XianRenZhang_workspace")
    
    def __init__(self, task_name: str = "任务1"):
        """初始化工作空间"""
        self.task_name = task_name
        self.task_dir = self.WORKSPACE_ROOT / task_name
        self.task_dir.mkdir(parents=True, exist_ok=True)
        
        # 子目录
        self.files_dir = self.task_dir / "files"
        self.memory_dir = self.task_dir / "memory"
        self.subagents_dir = self.task_dir / "subagents"
        
        for d in [self.files_dir, self.memory_dir, self.subagents_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def get_task_dir(self) -> Path:
        """获取任务目录"""
        return self.task_dir
    
    def get_files_dir(self) -> Path:
        """获取文件目录"""
        return self.files_dir
    
    def get_memory_dir(self) -> Path:
        """获取记忆目录"""
        return self.memory_dir
    
    def get_subagent_dir(self, subagent_id: str) -> Path:
        """获取子代理工作目录"""
        subagent_dir = self.subagents_dir / subagent_id
        subagent_dir.mkdir(parents=True, exist_ok=True)
        return subagent_dir
    
    def cleanup(self) -> bool:
        """清理任务目录"""
        try:
            if self.task_dir.exists():
                shutil.rmtree(self.task_dir)
            return True
        except Exception as e:
            print(f"[WorkspaceManager] 清理工作空间失败: {e}")
            return False
    
    @staticmethod
    def list_tasks() -> list:
        """列出所有任务"""
        if WorkspaceManager.WORKSPACE_ROOT.exists():
            return [d.name for d in WorkspaceManager.WORKSPACE_ROOT.iterdir() if d.is_dir()]
        return []
    
    @staticmethod
    def get_next_task_name() -> str:
        """获取下一个任务名称"""
        tasks = WorkspaceManager.list_tasks()
        num = 1
        while f"任务{num}" in tasks:
            num += 1
        return f"任务{num}"
