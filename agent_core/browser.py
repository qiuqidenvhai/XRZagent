"""
browser.py — Playwright 浏览器管理器（支持子代理）
"""
import asyncio
import logging
import json
import tempfile
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("browser")

DEEPSEEK_URL = "https://chat.deepseek.com"
CHAT_URL = "https://chat.deepseek.com/"

# 浏览器数据目录（用户数据，包含登录状态）
COOKIE_DIR = Path.home() / ".xianrenzhang_agent" / "browser_data"
COOKIE_FILE = COOKIE_DIR / "deepseek_cookies.json"

# 凭据管理目录（固定位置，子代理从这里复制）
CREDENTIALS_DIR = Path.home() / ".xianrenzhang_agent" / "credentials"
MANAGED_COOKIE_FILE = CREDENTIALS_DIR / "deepseek_cookies.json"


class BrowserManager:
    def __init__(self, headless: bool = False, user_data_dir: Optional[str] = None,
                 cookie_file: Optional[str] = None):
        self.headless = headless
        self.user_data_dir = user_data_dir or str(COOKIE_DIR)
        # 支持自定义 cookie 文件路径（用于子代理）
        self._custom_cookie_file = cookie_file
        self._browser = None
        self._page = None
        self._playwright = None

    @property
    def context(self):
        return self._browser

    async def launch(self):
        if self._browser is not None:
            logger.info("浏览器已启动，复用")
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        data_dir = Path(self.user_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_lock_files(data_dir)

        last_error = None
        for attempt, udir in enumerate([str(data_dir), tempfile.mkdtemp(prefix="xrz_chrome_")]):
            if attempt > 0:
                logger.warning(f"主目录失败，尝试临时目录：{udir}")
            try:
                self._browser = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=udir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 900},
                    args=self._default_args(),
                    accept_downloads=True,
                )
                break
            except Exception as e:
                last_error = e
                logger.warning(f"启动失败：{e}")
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                    self._browser = None

        if self._browser is None:
            raise RuntimeError(f"Chromium 启动失败：{last_error}")

        # 加载保存的 cookies
        await self._load_cookies()
        
        self._page = self._browser.pages[0] if self._browser.pages else await self._browser.new_page()
        logger.info(f"浏览器启动成功：{self.user_data_dir}")

    def _default_args(self):
        return [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-service-autorun",
            "--password-store=basic",
            "--no-sandbox",
            "--disable-gpu",
        ]

    def _cleanup_lock_files(self, data_dir: Path):
        for p in data_dir.iterdir():
            if any(x in p.name.lower() for x in ["singleton", "lock", "chromeport"]):
                try:
                    p.unlink(missing_ok=True)
                    logger.info(f"已清理锁文件：{p.name}")
                except Exception:
                    pass

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _load_cookies(self):
        """加载 cookies - 支持自定义路径"""
        # 优先使用自定义 cookie 文件，其次是凭据管理目录，最后是默认位置
        if self._custom_cookie_file:
            cookie_file = Path(self._custom_cookie_file)
        elif MANAGED_COOKIE_FILE.exists():
            cookie_file = MANAGED_COOKIE_FILE
        else:
            cookie_file = COOKIE_FILE
        
        if not cookie_file.exists():
            return
        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            if self._browser and cookies:
                await self._browser.add_cookies(cookies)
                logger.info(f"已加载 {len(cookies)} 条 cookies 从 {cookie_file}")
        except Exception as e:
            logger.warning(f"加载 cookies 失败：{e}")

    async def save_cookies(self):
        """保存当前浏览器 cookies 到文件"""
        if not self._browser:
            return
        try:
            cookies = await self._browser.cookies()
            
            # 确保目录存在
            COOKIE_DIR.mkdir(parents=True, exist_ok=True)
            CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            
            # 保存到所有位置
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            MANAGED_COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            
            # 如果有自定义 cookie 文件，也保存到那里（子代理凭据）
            if self._custom_cookie_file:
                custom_path = Path(self._custom_cookie_file)
                custom_path.parent.mkdir(parents=True, exist_ok=True)
                custom_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"已保存 {len(cookies)} 条 cookies 到自定义路径 {self._custom_cookie_file}")
            
            logger.info(f"已保存 {len(cookies)} 条 cookies")
        except Exception as e:
            logger.warning(f"保存 cookies 失败：{e}")

    async def navigate(self, url: str = DEEPSEEK_URL):
        if self._page is None:
            raise RuntimeError("页面未初始化")
        await self._page.goto(url, wait_until="networkidle", timeout=30000)
        logger.info(f"已导航：{url}")

    async def check_login(self) -> bool:
        """检查是否已登录 DeepSeek"""
        if self._page is None:
            return False
        try:
            # 多种登录状态检测方式
            # 1. 检查是否有登录按钮
            login_btn = self._page.locator('button:has-text("登录"), a:has-text("登录"), button:has-text("Login")')
            has_login_btn = await login_btn.count() > 0
            
            # 2. 检查是否有用户头像/设置
            user_avatar = self._page.locator('img[alt*="avatar"], [class*="avatar"], [class*="user-icon"]')
            has_avatar = await user_avatar.count() > 0
            
            # 3. 检查 URL 是否在聊天页面
            is_chat_page = "chat.deepseek.com" in self._page.url
            
            # 如果有头像或者在聊天页面且没有登录按钮，则认为已登录
            logged_in = has_avatar or (is_chat_page and not has_login_btn)
            
            logger.info(f"登录检查：has_login_btn={has_login_btn}, has_avatar={has_avatar}, is_chat_page={is_chat_page}, logged_in={logged_in}")
            return logged_in
        except Exception as e:
            logger.warning(f"登录检查异常：{e}")
            return False

    async def wait_login(self, timeout: int = 120) -> bool:
        """等待用户登录"""
        import time
        start = time.time()
        print(f"等待登录（最多 {timeout} 秒）...")
        
        while time.time() - start < timeout:
            if await self.check_login():
                await self.save_cookies()
                logger.info("登录成功，凭据已保存")
                return True
            await asyncio.sleep(3)
        
        logger.error("登录超时")
        return False

    async def new_session(self):
        """新建对话"""
        if self._page is None:
            await self.navigate()
        try:
            btn = self._page.locator("a[href='/'], a:has-text('新对话'), a:has-text('New Chat'), button:has-text('新对话')")
            if await btn.count() > 0:
                await btn.first.click()
                await self._page.wait_for_load_state("networkidle")
                logger.info("新对话已创建")
        except Exception as e:
            logger.warning(f"新建会话：{e}")
            await self.navigate()

    async def send_message(self, text: str) -> bool:
        """发送消息到 DeepSeek"""
        if self._page is None:
            raise RuntimeError("页面未初始化")
        if "chat.deepseek.com" not in self._page.url:
            await self.navigate()

        # 多种选择器尝试
        textarea = None
        selectors = [
            "textarea[placeholder*='问']",
            "textarea[placeholder*='输入']",
            "textarea[placeholder*='Ask']",
            "textarea[placeholder*='Type']",
            "textarea",
            "div[contenteditable='true'][role='textbox']",
            "div[class*='input'] textarea",
            "div[class*='composer'] textarea",
        ]
        
        for sel in selectors:
            try:
                el = self._page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    textarea = el
                    logger.info(f"找到输入框：{sel}")
                    break
            except Exception:
                pass

        if textarea is None:
            logger.error("未找到输入框，保存截图调试")
            await self._page.screenshot(path="debug_no_input.png")
            return False

        # 清空并填写
        await textarea.click()
        await asyncio.sleep(0.2)
        await textarea.fill("")
        await asyncio.sleep(0.1)
        await textarea.fill(text)
        await asyncio.sleep(0.2)

        # 尝试多种发送方式
        sent = False
        for sel in ["button[type='submit']", "button:has-text('发送')", "button:has-text('Send')"]:
            btn = self._page.locator(sel)
            if await btn.count() > 0 and await btn.first.is_enabled():
                await btn.first.click()
                logger.info("消息已发送（点击按钮）")
                sent = True
                break
        
        if not sent:
            await textarea.press("Enter")
            logger.info("消息已发送（Enter 键）")
            sent = True

        return sent

    async def _send_internal(self, text: str) -> bool:
        """内部发送协议消息：发完立即从 DOM 删除，不暴露给用户"""
        if self._page is None:
            raise RuntimeError("页面未初始化")
        if "chat.deepseek.com" not in self._page.url:
            await self.navigate()

        msg_count_before = await self._page.evaluate("""
            () => document.querySelectorAll('[data-role="user"], .user-message, [class*="user"]').length
        """)

        textarea = None
        for sel in ["textarea[placeholder*='说'], textarea",
                    "div[contenteditable='true'][role='textbox']"]:
            try:
                el = self._page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    textarea = el
                    break
            except Exception:
                pass

        if textarea is None:
            return False

        await textarea.click()
        await asyncio.sleep(0.1)
        await textarea.fill(text)
        await asyncio.sleep(0.1)

        for sel in ["button[type='submit']", "button:has-text('发送')"]:
            btn = self._page.locator(sel)
            if await btn.count() > 0 and await btn.first.is_enabled():
                await btn.first.click()
                break
        else:
            await textarea.press("Enter")

        await asyncio.sleep(0.5)

        try:
            deleted = await self._page.evaluate(f"""
                () => {{
                    const allUser = document.querySelectorAll('[data-role="user"], .user-message, [class*="user_msg"]');
                    if (allUser.length > {msg_count_before}) {{
                        allUser[allUser.length - 1].remove();
                        return true;
                    }}
                    const allMsgs = document.querySelectorAll('[class*="message_content"], [class*="msg_content"], [class*="bubble"]');
                    for (let i = allMsgs.length - 1; i >= 0; i--) {{
                        const el = allMsgs[i];
                        if (el.innerText && el.innerText.trim().startsWith('@@@@')) {{
                            el.remove();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            logger.info(f"内部消息删除结果：{deleted}")
        except Exception as e:
            logger.warning(f"删除内部消息失败：{e}")

        return True

    async def wait_response(self, timeout: int = 120) -> Optional[str]:
        """等待 AI 回复"""
        if self._page is None:
            return None

        logger.info(f"等待回复（超时 {timeout}s）...")
        last_text = ""
        stable = 0

        for _ in range(timeout):
            await asyncio.sleep(1)
            try:
                text = await self._page.evaluate("""
                    () => {
                        const els = document.querySelectorAll(".markdown-body, .prose, [class*='message']");
                        if (!els.length) return null;
                        return els[els.length - 1].innerText.trim();
                    }
                """)
                if text and text != last_text:
                    last_text = text
                    stable = 0
                    logger.info(f"收到内容 ({len(text)} 字符)...")
                elif text and text == last_text:
                    stable += 1
                    if stable >= 3:
                        logger.info(f"回复完成：{len(text)} 字符")
                        return text
                else:
                    loading = await self._page.query_selector(".loading, [class*='generating']")
                    if not loading and last_text:
                        stable += 1
                        if stable >= 2:
                            return last_text
            except Exception as e:
                logger.warning(f"等待回复异常：{e}")

        return last_text if last_text else None

    async def browser_click(self, selector: str) -> str:
        if self._page is None:
            return "错误：页面未初始化"
        try:
            await self._page.locator(selector).first.click()
            return f"已点击：{selector}"
        except Exception as e:
            return f"点击失败：{e}"

    async def browser_fill(self, selector: str, text: str) -> str:
        if self._page is None:
            return "错误：页面未初始化"
        try:
            await self._page.locator(selector).first.fill(text)
            return f"已填写 {selector}"
        except Exception as e:
            return f"填写失败：{e}"

    async def browser_screenshot(self, path: str) -> str:
        if self._page is None:
            return "错误：页面未初始化"
        try:
            await self._page.screenshot(path=path, full_page=True)
            return f"截图已保存：{path}"
        except Exception as e:
            return f"截图失败：{e}"

    async def browser_get_text(self, selector: str) -> str:
        if self._page is None:
            return "错误：页面未初始化"
        try:
            return await self._page.locator(selector).first.inner_text()
        except Exception as e:
            return f"获取文本失败：{e}"

    async def browser_get_thinking_content(self) -> str:
        """获取当前深度思考内容（如果正在显示）"""
        if self._page is None:
            return ""
        try:
            # 尝试多种可能的深度思考内容选择器
            selectors = [
                "[class*='thinking']",
                "[class*='deep-think']",
                "[class*='reasoning']",
                "[class*='思考']",
                ".thinking-content",
                ".reasoning-content",
            ]
            for sel in selectors:
                try:
                    elem = self._page.locator(sel).first
                    if await elem.is_visible(timeout=500):
                        return await elem.inner_text()
                except:
                    continue
            return ""
        except Exception as e:
            return ""

    async def browser_get_html(self) -> str:
        if self._page is None:
            return "错误：页面未初始化"
        try:
            return await self._page.content()
        except Exception as e:
            return f"获取 HTML 失败：{e}"

    async def toggle_deep_think(self, enable: bool = True) -> bool:
        """切换深度思考模式
        
        支持多平台：DeepSeek、通义千问、豆包、元宝、ChatGPT、Gemini
        """
        if self._page is None:
            return False
        try:
            # 尝试多种平台的深度思考按钮选择器
            selectors_by_platform = {
                "deepseek": [
                    "button:has-text('深度思考')",
                    "button:has-text('DeepThink')",
                    "button:has-text('深度')",
                    "[class*='deep'] button",
                    "[class*='think'] button",
                    "div[role='button']:has-text('深度思考')",
                    "div[role='button']:has-text('深度')",
                ],
                "tongyi": [
                    "button:has-text('深度思考')",
                    "button:has-text('深度')",
                    "[class*='think'] button",
                ],
                "gpt": [
                    "button:has-text('Analysis')",
                    "button:has-text('Extended')",
                    "[class*='analysis'] button",
                ],
                "gemini": [
                    "button:has-text('Think')",
                    "[class*='think'] button",
                ],
            }
            
            all_selectors = []
            for sel_list in selectors_by_platform.values():
                all_selectors.extend(sel_list)
            
            for sel in all_selectors:
                try:
                    btn = self._page.locator(sel).first
                    
                    if await btn.count() > 0:
                        # 检查当前状态
                        is_active = await btn.evaluate("""el => {
                            const computed = window.getComputedStyle(el);
                            const bg = computed.backgroundColor || '';
                            const hasActiveClass = el.classList.contains('active') || 
                                                  el.classList.contains('selected') ||
                                                  el.classList.contains('enabled') ||
                                                  el.classList.contains('thinking');
                            const ariaPressed = el.getAttribute('aria-pressed') === 'true';
                            const ariaExpanded = el.getAttribute('aria-expanded') === 'true';
                            const isChecked = el.getAttribute('aria-checked') === 'true';
                            // 检查背景色是否为蓝色/紫色（激活状态常见特征）
                            const isColored = bg.includes('rgb(0') || bg.includes('blue') || bg.includes('#1890ff') || bg.includes('purple');
                            return hasActiveClass || ariaPressed || ariaExpanded || isChecked || isColored;
                        }""")
                        
                        target_state = enable
                        if is_active == target_state:
                            logger.info(f"深度思考模式已是{'开启' if enable else '关闭'}状态")
                            return True
                        
                        await btn.click()
                        await asyncio.sleep(0.8)
                        logger.info(f"深度思考模式已{'开启' if enable else '关闭'}")
                        return True
                except Exception:
                    continue
            
            logger.warning("未找到深度思考按钮 - 请检查界面是否有变化")
            return False
        except Exception as e:
            logger.warning(f"切换深度思考模式失败：{e}")
            return False

    async def is_deep_think_active(self) -> bool:
        """检查深度思考模式是否激活"""
        if self._page is None:
            return False
        try:
            selectors = [
                "button:has-text('深度思考')",
                "button:has-text('DeepThink')",
            ]
            
            for sel in selectors:
                btn = self._page.locator(sel).first
                if await btn.count() > 0:
                    is_active = await btn.evaluate("el => el.classList.contains('active') || el.getAttribute('aria-pressed') === 'true' || el.classList.contains('selected')")
                    return bool(is_active)
            
            return False
        except Exception:
            return False


def copy_credentials_to_managed_dir():
    """将浏览器数据目录的凭据复制到凭据管理目录"""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    
    if COOKIE_FILE.exists():
        shutil.copy2(COOKIE_FILE, MANAGED_COOKIE_FILE)
        logger.info(f"凭据已复制到：{MANAGED_COOKIE_FILE}")
        return True
    return False
