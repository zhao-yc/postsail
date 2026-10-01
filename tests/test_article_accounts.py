"""账号隔离、会话兼容与跨系统终端回退测试，不启动真实登录或发布。"""
import asyncio
import io
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from myUtils import auth, login
from utils.articles.session import load_article_storage_state, normalize_article_storage_state
from utils.platform_accounts import ARTICLE_ACCOUNT_TYPES, resolve_account_type, validate_imported_cookie


def cookie_state(domain=".weibo.com"):
    """构造不含真实账号凭据的隔离测试会话。"""
    return {"cookies": [{"name": "测试凭据", "value": "测试值", "domain": domain, "path": "/"}], "origins": []}


class ArticleAccountTests(unittest.TestCase):
    def test_account_types_keep_video_channel_distinct(self):
        self.assertEqual(resolve_account_type("tencent"), 2)
        self.assertEqual(resolve_account_type("qiehao"), 11)
        self.assertEqual(resolve_account_type("weibo"), 10)
        self.assertEqual(ARTICLE_ACCOUNT_TYPES, {3, 5, 6, 7, 8, 9, 10, 11})
        with self.assertRaises(ValueError):
            resolve_account_type(True)

    def test_biliup_conversion_does_not_change_source_or_tokens(self):
        payload = {"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "测试值"}]},
                   "token_info": {"access_token": "测试值"}}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "biliup.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes()
            result = load_article_storage_state("bilibili", path)
            self.assertEqual(result["cookies"][0]["domain"], ".bilibili.com")
            self.assertEqual(result["origins"], [])
            self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("domain", payload["cookie_info"]["cookies"][0])
        self.assertNotIn("token_info", result)

    def test_standard_state_and_storage_preserved_in_memory(self):
        state = cookie_state(".bilibili.com")
        state["origins"] = [{"origin": "https://www.bilibili.com", "localStorage": [{"name": "编辑器", "value": "设置"}]}]
        result = normalize_article_storage_state("bilibili", state)
        self.assertEqual(result["origins"], state["origins"])
        self.assertNotIn("secure", state["cookies"][0])
        for invalid in ({}, [], {"cookies": [None], "origins": []}, {"cookies": [], "origins": [{"origin": 1}]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_article_storage_state("weibo", invalid)

    def test_import_rejects_foreign_platform_cookie(self):
        with self.assertRaises(ValueError):
            validate_imported_cookie(10, cookie_state(".qq.com"))
        validate_imported_cookie(11, cookie_state("om.qq.com"))

    def test_new_auth_types_dispatch_independently(self):
        with patch.object(auth, "cookie_auth_article_account", new=AsyncMock(return_value=True)) as check:
            self.assertTrue(asyncio.run(auth.check_cookie(10, "测试.json")))
            self.assertEqual(check.call_args.args[0], "weibo")
            self.assertTrue(asyncio.run(auth.check_cookie(11, "测试.json")))
            self.assertEqual(check.call_args.args[0], "qiehao")
        with patch.object(auth, "cookie_auth_tencent", new=AsyncMock(return_value=True)) as video:
            self.assertTrue(asyncio.run(auth.check_cookie(2, "测试.json")))
            video.assert_awaited_once()

    def test_login_check_rejects_login_redirect_despite_visible_fields(self):
        page = MagicMock()
        page.url = "https://om.qq.com/userAuth/index"
        page.locator.return_value.first.wait_for = AsyncMock()
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "qiehao")))
        page.url = "https://om.qq.com/manage/index"
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "qiehao")))
        page.locator.return_value.first.wait_for = AsyncMock(side_effect=RuntimeError("缺少后台标识"))
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "qiehao")))

    def test_bilibili_standard_auth_uses_read_only_api_without_mutating_file(self):
        response = SimpleNamespace(ok=True, json=AsyncMock(return_value={"code": 0, "data": {"isLogin": True}}))
        context = SimpleNamespace(get=AsyncMock(return_value=response), dispose=AsyncMock())
        playwright = SimpleNamespace(request=SimpleNamespace(new_context=AsyncMock(return_value=context)))
        manager = AsyncMock()
        manager.__aenter__.return_value = playwright
        with TemporaryDirectory() as folder:
            path = Path(folder) / "测试.json"
            path.write_text(json.dumps(cookie_state(".bilibili.com")), encoding="utf-8")
            before = path.read_bytes()
            with patch.object(auth, "async_playwright", return_value=manager):
                self.assertTrue(asyncio.run(auth.cookie_auth_bilibili(path)))
            self.assertEqual(path.read_bytes(), before)
        context.get.assert_awaited_once_with("https://api.bilibili.com/x/web-interface/nav", timeout=30_000)
        context.dispose.assert_awaited_once()

    def test_weibo_authenticated_draft_list_is_read_only_login_evidence(self):
        page = MagicMock()
        page.url = "https://card.weibo.com/article/v3/editor"
        page.locator.return_value.count = AsyncMock(return_value=0)
        write = page.locator.return_value.filter.return_value
        write.first.wait_for = AsyncMock()
        write.first.click = AsyncMock()
        drafts = page.get_by_text.return_value
        drafts.first.wait_for = AsyncMock()
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "weibo")))
        write.first.click.assert_not_awaited()
        drafts.first.wait_for = AsyncMock(side_effect=RuntimeError("没有草稿管理"))
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "weibo")))
        page.url = "https://passport.weibo.com/login"
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "weibo")))
        page.url = "https://card.weibo.com.attacker.example/article/v3/editor"
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "weibo")))

    def test_weibo_existing_editor_remains_valid_without_draft_creation(self):
        page = MagicMock()
        page.url = "https://card.weibo.com/article/v3/editor"
        page.locator.return_value.count = AsyncMock(return_value=1)
        page.locator.return_value.first.is_visible = AsyncMock(return_value=True)
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "weibo")))
        page.get_by_text.assert_not_called()

    def test_linux_terminal_is_configurable_and_has_import_fallback(self):
        import conf
        with patch.object(conf, "BILIBILI_TERMINAL_COMMAND", ["终端", "--"], create=True), \
                patch("subprocess.Popen") as spawn:
            login.launch_bilibili_login_terminal("/路径/biliup", "/路径/账号.json", system="linux")
            self.assertEqual(spawn.call_args.args[0], ["终端", "--", "/路径/biliup", "-u", "/路径/账号.json", "login"])
        with patch.object(conf, "BILIBILI_TERMINAL_COMMAND", [], create=True), patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "导入 Cookie"):
                login.launch_bilibili_login_terminal("biliup", "账号.json", system="linux")

    def test_macos_terminal_quotes_shell_and_applescript_separately(self):
        with patch("subprocess.Popen") as spawn:
            login.launch_bilibili_login_terminal("/a path/biliup", "/tmp/$(touch hacked)\"账号.json", system="darwin")
        args = spawn.call_args.args[0]
        self.assertEqual(args[0], "osascript")
        self.assertIn("'/tmp/$(touch hacked)", args[-1])
        self.assertIn('\\"账号.json', args[-1])
        self.assertNotIn("shell", spawn.call_args.kwargs)


class CookieImportRoutesTests(unittest.TestCase):
    def setUp(self):
        """所有账号数据放临时数据库，真实用户目录不会写入。"""
        import sau_backend
        self.backend = sau_backend
        self.temporary = TemporaryDirectory()
        self.base = Path(self.temporary.name)
        (self.base / "db").mkdir()
        (self.base / "cookiesFile").mkdir()
        self.existing = self.base / "cookiesFile" / "原账号.json"
        self.existing.write_text("原始会话", encoding="utf-8")
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            conn.execute("INSERT INTO user_info VALUES(1,10,'原账号.json','微博账号',0)")
        self.base_patch = patch.object(sau_backend, "BASE_DIR", self.base)
        self.base_patch.start()
        self.client = sau_backend.app.test_client()

    def tearDown(self):
        self.base_patch.stop()
        self.temporary.cleanup()

    def upload(self, route="/uploadCookie", platform="10", state=None):
        """通过 multipart 提交虚构会话，不访问真实平台。"""
        data = {"file": (io.BytesIO(json.dumps(state or cookie_state()).encode()), "测试.json"),
                "platform": platform, "id": "1", "name": "新增账号"}
        return self.client.post(route, data=data)

    def test_wrong_platform_rejected_before_validation(self):
        with patch.object(self.backend, "check_cookie", new=AsyncMock()) as check:
            response = self.upload(platform="11")
        self.assertEqual(response.status_code, 400)
        check.assert_not_called()
        self.assertEqual(self.existing.read_text(), "原始会话")

    def test_failed_auth_preserves_original_and_cleans_temporary(self):
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=False)):
            response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.existing.read_text(), "原始会话")
        self.assertEqual(list((self.base / "cookiesFile").iterdir()), [self.existing])

    def test_new_qiehao_import_creates_distinct_type(self):
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)) as check:
            response = self.upload("/importCookie", platform="qiehao", state=cookie_state(".qq.com"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["type"], 11)
        self.assertEqual(check.call_args.args[0], 11)
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            self.assertEqual(conn.execute("SELECT type,status FROM user_info WHERE id=2").fetchone(), (11, 1))

    def prepare_bilibili_account(self):
        """设置含虚构视频 token 的旧账号，检验字节级保留而不使用真实凭据。"""
        payload = {"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "虚构值"}]},
                   "token_info": {"access_token": "虚构token", "refresh_token": "虚构refresh"}}
        self.existing.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            conn.execute("UPDATE user_info SET type=6 WHERE id=1")
        return payload

    def test_bilibili_standard_replacement_preserves_existing_video_tokens(self):
        self.prepare_bilibili_account()
        before = self.existing.read_bytes()
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)) as check:
            response = self.upload(platform="6", state=cookie_state(".bilibili.com"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("新建独立文章会话账号", response.json["msg"])
        check.assert_not_called()
        self.assertEqual(self.existing.read_bytes(), before)
        self.assertEqual(list((self.base / "cookiesFile").iterdir()), [self.existing])
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            self.assertEqual(conn.execute("SELECT status FROM user_info WHERE id=1").fetchone()[0], 0)

    def test_bilibili_standard_state_can_create_independent_article_account(self):
        self.prepare_bilibili_account()
        before = self.existing.read_bytes()
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)):
            response = self.upload("/importCookie", platform="6", state=cookie_state(".bilibili.com"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["type"], 6)
        self.assertEqual(self.existing.read_bytes(), before)
        new_path = self.base / "cookiesFile" / response.json["data"]["filePath"]
        self.assertNotEqual(new_path, self.existing)
        self.assertEqual(load_article_storage_state("bilibili", new_path)["cookies"][0]["domain"], ".bilibili.com")

    def test_complete_biliup_replacement_remains_available(self):
        payload = self.prepare_bilibili_account()
        payload["token_info"]["access_token"] = "新的虚构token"
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)):
            response = self.upload(platform="6", state=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.existing.read_text())["token_info"]["access_token"], "新的虚构token")

    def test_incomplete_biliup_replacement_cannot_remove_existing_tokens(self):
        payload = self.prepare_bilibili_account()
        before = self.existing.read_bytes()
        payload.pop("token_info")
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)) as check:
            response = self.upload(platform="6", state=payload)
        self.assertEqual(response.status_code, 400)
        check.assert_not_called()
        self.assertEqual(self.existing.read_bytes(), before)

    def test_existing_standard_article_session_can_be_updated(self):
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            conn.execute("UPDATE user_info SET type=6 WHERE id=1")
        self.existing.write_text(json.dumps(cookie_state(".bilibili.com")), encoding="utf-8")
        state = cookie_state(".bilibili.com")
        state["cookies"][0]["value"] = "更新的文章会话"
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)):
            response = self.upload(platform="6", state=state)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(load_article_storage_state("bilibili", self.existing)["cookies"][0]["value"], "更新的文章会话")

    def test_biliup_credentials_written_during_validation_are_preserved(self):
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            conn.execute("UPDATE user_info SET type=6 WHERE id=1")
        self.existing.write_text(json.dumps(cookie_state(".bilibili.com")), encoding="utf-8")
        updated = {"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "虚构值"}]},
                   "token_info": {"access_token": "期间更新的虚构token"}}
        async def validate_and_update(*args):
            """模拟平台校验期间另一登录流程保存新的完整视频凭据。"""
            self.existing.write_text(json.dumps(updated), encoding="utf-8")
            return True
        with patch.object(self.backend, "check_cookie", new=AsyncMock(side_effect=validate_and_update)):
            response = self.upload(platform="6", state=cookie_state(".bilibili.com"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(self.existing.read_text()), updated)
        with sqlite3.connect(self.base / "db" / "database.db") as conn:
            self.assertEqual(conn.execute("SELECT status FROM user_info WHERE id=1").fetchone()[0], 0)

    def test_legacy_articles_only_use_declared_capabilities(self):
        for kind in ARTICLE_ACCOUNT_TYPES:
            self.assertTrue(self.backend._is_article_request({"type": str(kind), "contentType": "article"}))
        for kind in (1, 2, 4):
            self.assertFalse(self.backend._is_article_request({"type": kind, "contentType": "article"}))
        for kind in (3, 5, 6, 7):
            self.assertFalse(self.backend._is_article_request({"type": kind, "contentType": "video"}))
        self.assertNotIn("weibo", self.backend.SUPPORTED_STATS_PLATFORMS)
        self.assertNotIn("qiehao", self.backend.SUPPORTED_STATS_PLATFORMS)

    def test_unsupported_article_never_runs_video_dispatch(self):
        with patch.dict(self.backend.app.extensions, {"legacy_article_publish": MagicMock()}):
            for route, data in (("/postVideo", {"type": 2, "contentType": "article", "fileList": ["视频.mp4"]}),
                                ("/postVideo", {"type": 10, "contentType": "video"}),
                                ("/postVideoBatch", [{"type": 11, "contentType": "video"}])):
                response = self.client.post(route, json=data)
                self.assertEqual(response.status_code, 400)
            self.backend.app.extensions["legacy_article_publish"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
