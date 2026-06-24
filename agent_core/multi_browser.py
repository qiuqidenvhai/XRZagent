"""
multi_browser.py — 多平台浏览器管理器

支持平台：
- DeepSeek
- 通义千问 (Tongyi Qianwen)
- 豆包 (Doubao)
- 元宝 (Yuanbao)
- ChatGPT
- Gemini
- Ollama (本地模型)

设计思路：复用母代理的 browser context，每个平台创建独立 page，
共享 cookie/登录状态，子代理也可以直接使用这些页面。
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("multi_browser")


# ============================================================
# 平台配置
# ============================================================

PLATFORMS = {
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://chat.deepseek.com",
        "input_selector": "textarea[placeholder*='问'], textarea[placeholder*='输入'], div[contenteditable='true'][role='textbox']",
        "send_selector": "button[type='submit'], button:has-text('发送'), button:has-text('Send')",
        "response_selector": ".markdown-body, .prose, [class*='message']",
        "deep_think_selector": "button:has-text('深度思考'), button:has-text('DeepThink'), div[role='button']:has-text('深度思考')",
        "upload_selector": "input[type='file']",
    },
    "tongyi": {
        "name": "通义千问",
        "url": "https://tongyi.aliyun.com/",
        "input_selector": "textarea, div[contenteditable='true']",
        "send_selector": "button[type='submit'], button:has-text('发送')",
        "response_selector": ".markdown-body, [class*='answer'], [class*='response']",
        "deep_think_selector": "",
        "upload_selector": "input[type='file']",
    },
    "doubao": {
        "name": "豆包",
        "url": "https://www.doubao.com/",
        "input_selector": "textarea, div[contenteditable='true']",
        "send_selector": "button[type='submit'], button:has-text('发送')",
        "response_selector": ".markdown-body, [class*='answer'], [class*='message-content']",
        "deep_think_selector": "",
        "upload_selector": "input[type='file']",
    },
    "yuanbao": {
        "name": "元宝",
        "url": "https://yuanbao.tencent.com/",
        "input_selector": "textarea, div[contenteditable='true']",
        "send_selector": "button[type='submit'], button:has-text('发送')",
        "response_selector": ".markdown-body, [class*='answer'], [class*='message-content']",
        "deep_think_selector": "",
        "upload_selector": "input[type='file']",
    },
    "gpt": {
        "name": "ChatGPT",
        "url": "https://chat.openai.com/",
        "input_selector": "textarea, div[contenteditable='true']",
        "send_selector": "button[type='submit'], button svg",
        "response_selector": ".ProseMirror, [class*='message']",
        "deep_think_selector": "button:has-text('Analysis'), button:has-text('Extended')",
        "upload_selector": "input[type='file']",
    },
    "gemini": {
        "name": "Gemini",
        "url": "https://gemini.google.com/",
        "input_selector": "textarea, div[contenteditable='true']",
        "send_selector": "button[type='submit']",
        "response_selector": ".markdown-body, [class*='answer']",
        "deep_think_selector": "button:has-text('Think'), button:has-text('思考')",
        "upload_selector": "input[type='file']",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "url": "http://localhost:11434",
        "input_selector": "textarea, input[type='text']",
        "send_selector": "button[type='submit']",
        "response_selector": ".markdown-body, [class*='answer']",
        "deep_think_selector": "",
        "upload_selector": "input[type='file']",
    },
}


@dataclass
class PlatformPage:
    """单个平台的页面信息"""
    platform_key: str
    name: str
    page: Any = None
    context: Any = None
    is_logged_in: bool = False
    last_response: str = ""


class MultiBrowserManager:
    """多平台浏览器管理器
    
    设计原则：
    1. 复用母代理的 browser context（已登录状态）
    2. 每个平台创建独立 page
    3. 子代理可以直接访问这些 page
    4. 共享 cookie 和登录状态
    """
    
    def __init__(self, existing_context=None):
        self._existing_context = existing_context
        self._pages: Dict[str, PlatformPage] = {}
        self._platform_configs = dict(PLATFORMS)
        self._initialized = False
    
    async def init_from_existing_context(self, browser_manager):
        """从母代理的 BrowserManager 初始化
        
        Args:
            browser_manager: 母代理的 BrowserManager 实例
        """
        if not browser_manager or not browser_manager._browser:
            logger.error("母代理浏览器未初始化")
            return False
        
        context = browser_manager._browser
        logger.info(f"开始从母代理初始化多平台浏览器...")
        
        try:
            cookies = await context.cookies()
            logger.info(f"母代理有 {len(cookies)} 条 cookies")
        except Exception as e:
            logger.warning(f"获取母代理 cookies 失败：{e}")
            cookies = []
        
        for key, config in self._platform_configs.items():
            page = await context.new_page()
            pp = PlatformPage(platform_key=key, name=config["name"], page=page, context=context)
            self._pages[key] = pp
            logger.info(f"已为平台 '{key}' 创建新页面: {config['url']}")
        
        self._initialized = True
        logger.info(f"多平台浏览器初始化完成，共 {len(self._pages)} 个平台")
        return True
    
    async def launch_all(self):
        """启动所有平台页面（加载各自的登录状态）"""
        if not self._initialized:
            logger.error("请先调用 init_from_existing_context() 初始化")
            return False
        
        tasks = []
        for key, pp in self._pages.items():
            tasks.append(self._navigate_and_check_login(key, pp))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"平台启动完成：{success_count}/{len(results)} 成功")
        return success_count > 0
    
    async def _navigate_and_check_login(self, key: str, pp: PlatformPage) -> bool:
        """导航到平台并检查登录状态"""
        config = self._platform_configs[key]
        try:
            await pp.page.goto(config["url"], wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
            
            if key == "deepseek":
                pp.is_logged_in = await self._check_deepseek_login(pp)
            elif key == "gpt":
                pp.is_logged_in = await self._check_gpt_login(pp)
            elif key == "tongyi":
                pp.is_logged_in = await self._check_tongyi_login(pp)
            elif key == "doubao":
                pp.is_logged_in = await self._check_doubao_login(pp)
            elif key == "yuanbao":
                pp.is_logged_in = await self._check_yuanbao_login(pp)
            elif key == "gemini":
                pp.is_logged_in = await self._check_gemini_login(pp)
            else:
                pp.is_logged_in = True
            
            status = "已登录" if pp.is_logged_in else "需登录"
            logger.info(f"平台 '{key}' ({config['name']}): {status}")
            return True
        except Exception as e:
            logger.warning(f"平台 '{key}' 导航失败：{e}")
            return False
    
    # ---- 各平台登录检测 ----
    
    async def _check_deepseek_login(self, pp: PlatformPage) -> bool:
        try:
            has_login_btn = await pp.page.locator('button:has-text("登录"), a:has-text("登录")').count() > 0
            has_avatar = await pp.page.locator('img[alt*="avatar"], [class*="avatar"], [class*="user"]').count() > 0
            return not has_login_btn or has_avatar
        except:
            return False
    
    async def _check_gpt_login(self, pp: PlatformPage) -> bool:
        try:
            has_signup_btn = await pp.page.locator('button:has-text("Sign up")').count() > 0
            has_profile = await pp.page.locator('[data-testid="conversation-user-avatar"]').count() > 0
            return not has_signup_btn or has_profile
        except:
            return False
    
    async def _check_tongyi_login(self, pp: PlatformPage) -> bool:
        try:
            has_login_btn = await pp.page.locator('button:has-text("登录")').count() > 0
            has_avatar = await pp.page.locator('[class*="avatar"], [class*="user-info"]').count() > 0
            return not has_login_btn or has_avatar
        except:
            return False
    
    async def _check_doubao_login(self, pp: PlatformPage) -> bool:
        try:
            has_login_btn = await pp.page.locator('button:has-text("登录")').count() > 0
            has_avatar = await pp.page.locator('[class*="avatar"], img[class*="user"]').count() > 0
            return not has_login_btn or has_avatar
        except:
            return False
    
    async def _check_yuanbao_login(self, pp: PlatformPage) -> bool:
        try:
            has_login_btn = await pp.page.locator('button:has-text("登录")').count() > 0
            has_avatar = await pp.page.locator('[class*="avatar"], img[class*="user"]').count() > 0
            return not has_login_btn or has_avatar
        except:
            return False
    
    async def _check_gemini_login(self, pp: PlatformPage) -> bool:
        try:
            has_signin_btn = await pp.page.locator('button:has-text("Sign in")').count() > 0
            has_avatar = await pp.page.locator('img[class*="avatar"], [class*="user-avatar"]').count() > 0
            return not has_signin_btn or has_avatar
        except:
            return False
    
    # ---- 发消息 ----
    
    async def send_message(self, platform_key: str, text: str) -> bool:
        """向指定平台发送消息"""
        pp = self._pages.get(platform_key)
        if not pp or not pp.page:
            logger.error(f"平台 '{platform_key}' 未初始化")
            return False
        
        if not pp.is_logged_in:
            logger.warning(f"平台 '{platform_key}' 未登录")
            return False
        
        config = self._platform_configs[platform_key]
        try:
            await pp.page.goto(config["url"], wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)
            
            textarea = pp.page.locator(config["input_selector"]).first
            if not await textarea.is_visible(timeout=5000):
                logger.error(f"平台 '{platform_key}' 找不到输入框")
                return False
            
            await textarea.click()
            await asyncio.sleep(0.2)
            await textarea.fill("")
            await asyncio.sleep(0.1)
            await textarea.fill(text)
            await asyncio.sleep(0.3)
            
            send_btn = pp.page.locator(config["send_selector"]).first
            if await send_btn.is_visible(timeout=3000):
                await send_btn.click()
            else:
                await textarea.press("Enter")
            
            logger.info(f"已向平台 '{platform_key}' 发送消息")
            return True
        except Exception as e:
            logger.error(f"平台 '{platform_key}' 发送消息失败：{e}")
            return False
    
    async def wait_response(self, platform_key: str, timeout: int = 60) -> Optional[str]:
        """等待平台回复"""
        pp = self._pages.get(platform_key)
        if not pp or not pp.page:
            return None
        
        config = self._platform_configs[platform_key]
        last_text = ""
        
        for _ in range(timeout):
            await asyncio.sleep(1)
            try:
                sel = config["response_selector"].replace("'", "\\'")
                text = await pp.page.evaluate(f"""
                    () => {{
                        const els = document.querySelectorAll('{sel}');
                        if (!els.length) return null;
                        return els[els.length - 1].innerText.trim();
                    }}
                """)
                if text and text != last_text:
                    last_text = text
                elif text and text == last_text:
                    pp.last_response = last_text
                    return last_text
            except:
                pass
        
        return pp.last_response if pp.last_response else None
    
    # ---- 深度思考 ----
    
    async def toggle_deep_think(self, platform_key: str, enable: bool = True) -> bool:
        """切换平台的深度思考模式"""
        pp = self._pages.get(platform_key)
        if not pp or not pp.page:
            return False
        
        config = self._platform_configs[platform_key]
        selector = config.get("deep_think_selector")
        if not selector:
            logger.info(f"平台 '{platform_key}' 不支持深度思考模式")
            return False
        
        try:
            btn = pp.page.locator(selector).first
            if not await btn.is_visible(timeout=3000):
                logger.warning(f"平台 '{platform_key}' 找不到深度思考按钮")
                return False
            
            is_active = await btn.evaluate("el => el.classList.contains('active') || el.getAttribute('aria-pressed') === 'true' || el.classList.contains('selected')")
            
            if is_active != enable:
                await btn.click()
                await asyncio.sleep(0.5)
            
            logger.info(f"平台 '{platform_key}' 深度思考模式已{'开启' if enable else '关闭'}")
            return True
        except Exception as e:
            logger.warning(f"平台 '{platform_key}' 切换深度思考失败：{e}")
            return False
    
    # ---- 文件上传 ----
    
    async def upload_file(self, platform_key: str, file_path: str) -> bool:
        """向指定平台上传文件"""
        pp = self._pages.get(platform_key)
        if not pp or not pp.page:
            return False
        
        config = self._platform_configs[platform_key]
        selector = config.get("upload_selector")
        if not selector:
            logger.warning(f"平台 '{platform_key}' 不支持文件上传")
            return False
        
        try:
            input_el = pp.page.locator(selector).first
            await input_el.set_input_files(file_path)
            logger.info(f"文件 '{file_path}' 已上传到平台 '{platform_key}'")
            return True
        except Exception as e:
            logger.warning(f"平台 '{platform_key}' 上传文件失败：{e}")
            return False
    
    # ---- Cookie 管理 ----
    
    async def save_cookies(self):
        """保存所有平台的 cookies"""
        for key, pp in self._pages.items():
            try:
                if pp.context:
                    cookies = await pp.context.cookies()
                    logger.info(f"已保存平台 '{key}' 的 {len(cookies)} 条 cookies")
            except Exception as e:
                logger.warning(f"保存平台 '{key}' cookies 失败：{e}")
    
    async def close_all(self):
        """关闭所有平台页面"""
        for key, pp in self._pages.items():
            try:
                if pp.page:
                    await pp.page.close()
                    logger.info(f"已关闭平台 '{key}'")
            except Exception as e:
                logger.warning(f"关闭平台 '{key}' 失败：{e}")
        
        self._pages.clear()
        self._initialized = False
        logger.info("所有平台页面已关闭")


# ============================================================
# 全局单例
# ============================================================

_multi_browser_instance: Optional[MultiBrowserManager] = None


def get_multi_browser_manager() -> Optional[MultiBrowserManager]:
    """获取全局多平台浏览器管理器单例"""
    global _multi_browser_instance
    return _multi_browser_instance


def set_multi_browser_manager(manager: MultiBrowserManager):
    """设置全局多平台浏览器管理器单例"""
    global _multi_browser_instance
    _multi_browser_instance = manager
