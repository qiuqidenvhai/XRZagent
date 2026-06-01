"""
subagent_main.py — 子代理独立进程入口
- 作为独立 Python 进程运行
- 协议和母代理完全相同
- 通过命令行参数接收任务
- 结果写入文件，母代理读取
"""
import asyncio
import sys
import json
import argparse
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_core.browser import BrowserManager, CREDENTIALS_DIR, MANAGED_COOKIE_FILE, COOKIE_FILE
from agent_core.session import DeepSeekSession
from agent_core.commander import Commander
from agent_core.protocol import Protocol


class SubAgentProcess:
    """子代理进程 - 独立运行，和母代理协议相同"""
    
    def __init__(self, task_dir: str, query: str, task_type: str, parent_pid: int = None):
        self.task_dir = Path(task_dir)
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.query = query
        self.task_type = task_type
        self.parent_pid = parent_pid
        
        self.work_dir = self.task_dir / "work"
        self.work_dir.mkdir(exist_ok=True)
        
        # 子代理特定目录
        self.subagent_data_dir = self.task_dir / "browser_data"
        self.subagent_cred_dir = self.task_dir / "credentials"
        
        self.browser = None
        self.session = None
        self.commander = None
        
        # 结果文件路径
        self.result_file = self.task_dir / "result.json"
        self.status_file = self.task_dir / "status.txt"
        self.output_dir = self.task_dir / "output"
        self.output_dir.mkdir(exist_ok=True)
        
    def _copy_credentials(self):
        """从母代理凭据管理目录复制凭据到子代理临时目录"""
        import shutil
        
        self.subagent_cred_dir.mkdir(parents=True, exist_ok=True)
        target_cookie = self.subagent_cred_dir / "deepseek_cookies.json"
        
        if MANAGED_COOKIE_FILE.exists():
            shutil.copy2(MANAGED_COOKIE_FILE, target_cookie)
            print(f"[INFO] 凭据已复制到: {target_cookie}")
            return True
        else:
            print(f"[WARN] 母代理凭据不存在: {MANAGED_COOKIE_FILE}")
            return False
    
    def _write_status(self, status: str, message: str = ""):
        """写入状态文件通知母代理"""
        status_data = {
            "status": status,
            "message": message,
            "task_dir": str(self.task_dir),
            "output_dir": str(self.output_dir),
        }
        self.status_file.write_text(json.dumps(status_data), encoding="utf-8")
        print(f"[STATUS] {status}: {message}")
    
    def _write_result(self, success: bool, output: str = "", error: str = "", files: list = None):
        """写入结果文件"""
        result = {
            "success": success,
            "output": output,
            "error": error,
            "files": files or [],
            "query": self.query,
            "task_type": self.task_type,
        }
        self.result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[RESULT] 结果已写入: {self.result_file}")
    
    async def run(self):
        """运行子代理任务"""
        print(f"\n{'='*50}")
        print(f"[子代理启动] 任务类型: {self.task_type}")
        print(f"[子代理启动] 工作目录: {self.task_dir}")
        print(f"[子代理启动] 查询: {self.query[:100]}...")
        print(f"{'='*50}\n")
        
        # 1. 通知母代理启动
        self._write_status("STARTED", f"子代理已启动，工作目录: {self.task_dir}")
        
        # 2. 复制凭据
        has_creds = self._copy_credentials()
        if not has_creds:
            self._write_status("ERROR", "无法获取凭据")
            self._write_result(False, error="无法获取母代理凭据")
            return False
        
        try:
            # 3. 启动浏览器（使用子代理自己的数据目录和凭据）
            print("[INFO] 启动浏览器...")
            self._write_status("INITIALIZING", "正在启动浏览器...")
            
            # 子代理使用自己的凭据文件路径
            subagent_cookie_file = str(self.subagent_cred_dir / "deepseek_cookies.json")
            self.browser = BrowserManager(
                headless=False,  # 子代理也使用有头模式以便观察
                user_data_dir=str(self.subagent_data_dir),
                cookie_file=subagent_cookie_file  # 使用子代理自己的凭据
            )
            await self.browser.launch()
            
            # 4. 检查登录状态
            print("[INFO] 检查登录状态...")
            await self.browser.navigate()
            
            if not await self.browser.check_login():
                print("[WARN] 未登录，尝试使用凭据...")
                # 凭据应该在 launch 时已经加载
                await self.browser.navigate()
                if not await self.browser.check_login():
                    self._write_status("ERROR", "凭据无效，需要重新登录")
                    self._write_result(False, error="凭据无效")
                    await self.browser.close()
                    return False
            
            print("[OK] 已登录")
            self._write_status("RUNNING", "正在执行任务...")
            
            # 5. 初始化会话和 Commander
            self.session = DeepSeekSession(self.browser)
            self.commander = Commander(
                browser_manager=self.browser,
                session=self.session,
                work_dir=str(self.work_dir),
            )
            await self.commander.start(session=self.session)
            
            # 6. 执行任务
            print(f"[INFO] 开始执行任务: {self.query}")
            
            # 构建任务提示
            task_prompt = self._build_task_prompt()
            
            # 运行任务
            reply = await self.commander.run_with_loop(
                user_instruction=task_prompt,
                file_path=None,
                context_hints=f"这是一个子代理任务，类型: {self.task_type}",
            )
            
            # 7. 收集输出文件
            output_files = []
            for f in self.work_dir.rglob("*"):
                if f.is_file():
                    # 复制到输出目录
                    dest = self.output_dir / f.name
                    import shutil
                    shutil.copy2(f, dest)
                    output_files.append(str(dest.relative_to(self.task_dir)))
            
            # 8. 写入结果
            self._write_status("COMPLETED", "任务完成")
            self._write_result(
                success=True,
                output=reply,
                files=output_files
            )
            
            print(f"\n[OK] 子代理任务完成")
            print(f"[OK] 结果文件: {self.result_file}")
            print(f"[OK] 输出文件数: {len(output_files)}")
            
            return True
            
        except Exception as e:
            error_msg = f"子代理执行错误: {e}"
            print(f"[ERROR] {error_msg}")
            self._write_status("FAILED", error_msg)
            self._write_result(False, error=error_msg)
            return False
            
        finally:
            # 9. 清理
            if self.browser:
                await self.browser.close()
                print("[INFO] 浏览器已关闭")
    
    def _build_task_prompt(self) -> str:
        """构建任务提示"""
        base_prompt = f"""请完成以下任务：

{self.query}

任务要求：
1. 这是一个子代理任务，你不能创建新的子代理（MAX_DEPTH=1）
2. 所有输出文件请保存在当前工作目录
3. 完成后调用 done() 工具报告结果
4. 如果遇到问题，详细记录错误信息

任务类型: {self.task_type}
工作目录: {self.work_dir}
"""
        return base_prompt


def main():
    parser = argparse.ArgumentParser(description="仙人掌 Agent - 子代理进程")
    parser.add_argument("--task-dir", required=True, help="任务工作目录")
    parser.add_argument("--query", required=True, help="任务查询内容")
    parser.add_argument("--type", default="research", help="任务类型")
    parser.add_argument("--parent-pid", type=int, default=None, help="母代理进程ID")
    
    args = parser.parse_args()
    
    # 创建并运行子代理
    subagent = SubAgentProcess(
        task_dir=args.task_dir,
        query=args.query,
        task_type=args.type,
        parent_pid=args.parent_pid
    )
    
    success = asyncio.run(subagent.run())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
