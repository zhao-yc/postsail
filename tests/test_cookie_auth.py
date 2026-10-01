import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from myUtils import auth


class CookieAuthBrowserTests(unittest.TestCase):
    def _check_platforms(self, chrome_path):
        """模拟已登录页面，覆盖扫码完成后真正调用的六个平台校验入口。"""
        for platform_type in (1, 2, 3, 4, 5, 7):
            with self.subTest(platform_type=platform_type, chrome_path=chrome_path):
                page = MagicMock()
                page.url = "https://mp.toutiao.com/profile_v4/index"
                page.goto = AsyncMock()
                page.wait_for_url = AsyncMock()
                page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError("未出现登录提示"))
                page.wait_for_timeout = AsyncMock()
                page.get_by_text.return_value.count = AsyncMock(return_value=0)
                page.get_by_text.return_value.wait_for = AsyncMock(side_effect=PlaywrightTimeoutError("未出现登录提示"))
                context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
                browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
                launch = AsyncMock(return_value=browser)
                playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
                manager = AsyncMock()
                manager.__aenter__.return_value = playwright

                with patch.object(auth, "LOCAL_CHROME_PATH", chrome_path), \
                        patch.object(auth, "LOCAL_CHROME_HEADLESS", True), \
                        patch.object(auth, "async_playwright", return_value=manager), \
                        patch.object(auth, "set_init_script", new=AsyncMock(side_effect=lambda value: value)):
                    result = asyncio.run(auth.check_cookie(platform_type, "测试账号.json"))

                self.assertTrue(result)
                options = launch.call_args.kwargs
                self.assertTrue(options["headless"])
                if chrome_path:
                    self.assertEqual(options["executable_path"], chrome_path)
                    self.assertNotIn("channel", options)
                else:
                    self.assertEqual(options["channel"], "chrome")
                    self.assertNotIn("executable_path", options)
                browser.new_context.assert_awaited_once_with(
                    storage_state=Path(auth.BASE_DIR / "cookiesFile" / "测试账号.json")
                )

    def test_cookie_checks_use_configured_chrome(self):
        """配置 Chrome 路径后，校验阶段不能退回未安装的 Chromium。"""
        self._check_platforms("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    def test_cookie_checks_use_system_chrome_without_path(self):
        """没有显式路径时，校验与登录都应使用系统 Chrome 通道。"""
        self._check_platforms("")


if __name__ == "__main__":
    unittest.main()
