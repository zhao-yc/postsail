"""新增文章平台账号隔离与正向登录证据，不访问真实账号或执行发布。"""
import asyncio
import io
import json
import os
import sqlite3
import unittest
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from myUtils import auth, login
from utils.platform_accounts import (
    ACCOUNT_COOKIE_DOMAINS,
    ACCOUNT_PLATFORMS,
    ACCOUNT_UNAVAILABLE_REASONS,
    ARTICLE_ONLY_ACCOUNT_TYPES,
    resolve_account_type,
    validate_imported_cookie,
)


NEW_ACCOUNTS = {
    12: "yidian", 13: "dayu", 14: "netease", 15: "acfun", 16: "kuaichuan",
    17: "xueqiu", 18: "jingdong", 19: "douban", 20: "csdn", 21: "jianshu",
    22: "chejiahao", 23: "yiche", 24: "dongchedi",
}
PAUSED_AUTOMOTIVE_ACCOUNTS = {
    kind: "fixture：平台维护期间暂不支持登录、导入或发布" for kind in (22, 23, 24)
}


def fake_state(domain):
    return {"cookies": [{"name": "fixture_session", "value": "not-a-real-credential", "domain": domain, "path": "/"}], "origins": []}


class ExtendedArticleAccountTests(unittest.TestCase):
    def test_new_types_and_names_remain_independent(self):
        for kind, platform in NEW_ACCOUNTS.items():
            with self.subTest(platform=platform):
                self.assertEqual(ACCOUNT_PLATFORMS[kind], platform)
                self.assertEqual(resolve_account_type(platform), kind)
                self.assertEqual(resolve_account_type(str(kind)), kind)
                self.assertIn(kind, ARTICLE_ONLY_ACCOUNT_TYPES)
        self.assertEqual(resolve_account_type("视频号"), 2)
        self.assertEqual(resolve_account_type("qiehao"), 11)

    def test_official_cookie_domain_requires_exact_domain_boundary(self):
        for kind in NEW_ACCOUNTS:
            domain = ACCOUNT_COOKIE_DOMAINS[kind][0]
            for allowed in (domain, "." + domain, "creator." + domain):
                with self.subTest(kind=kind, allowed=allowed):
                    self.assertTrue(validate_imported_cookie(kind, fake_state(allowed)))
            for foreign in (domain + ".attacker.example", "evil" + domain, "example.com"):
                with self.subTest(kind=kind, foreign=foreign), self.assertRaises(ValueError):
                    validate_imported_cookie(kind, fake_state(foreign))
        with self.assertRaises(ValueError):
            validate_imported_cookie(16, fake_state(".kuaishou.com"))

    def test_every_new_cookie_check_uses_its_own_article_platform(self):
        with patch.object(auth, "cookie_auth_article_account", new=AsyncMock(return_value=True)) as check:
            for kind, platform in NEW_ACCOUNTS.items():
                if kind in ACCOUNT_UNAVAILABLE_REASONS:
                    continue
                self.assertTrue(asyncio.run(auth.check_cookie(kind, "fixture.json")))
                self.assertEqual(check.call_args.args[0], platform)
                self.assertEqual(check.call_args.args[1].name, "fixture.json")

    def test_auth_rejects_login_hash_and_lookalike_hosts_before_evidence(self):
        for kind, platform in NEW_ACCOUNTS.items():
            if platform not in auth.ARTICLE_LOGIN_PROBES:
                self.assertIn(kind, ACCOUNT_UNAVAILABLE_REASONS)
                continue
            probe = auth.ARTICLE_LOGIN_PROBES[platform]
            for url in (f'https://{probe["host"]}.attacker.example/editor',
                        f'https://{probe["host"]}/#/login',
                        f'https://{probe["host"]}/sign_in',
                        f'http://{probe["host"]}/editor'):
                page = MagicMock(url=url)
                with self.subTest(platform=platform, url=url):
                    self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, platform)))
                    page.evaluate.assert_not_called()
                    page.locator.assert_not_called()

    def test_read_only_identity_api_requires_positive_account_data(self):
        fixtures = {
            "yidian": {"status": "success", "result": {"mediaId": "fixture"}},
            "netease": {"code": 1, "data": {"wemediaId": "fixture"}},
            "jianshu": {"nickname": "fixture"},
            "acfun": {"info": {"userId": "fixture"}},
            "chejiahao": {"returncode": 0, "result": {"userid": "12345", "role": 2}},
        }
        for platform, data in fixtures.items():
            probe = auth.ARTICLE_LOGIN_PROBES[platform]
            response = SimpleNamespace(ok=True, url=probe["identity_url"], json=AsyncMock(return_value=data))
            page = SimpleNamespace(url=probe["url"], request=SimpleNamespace(get=AsyncMock(return_value=response)),
                                   evaluate=AsyncMock(return_value=None))
            with self.subTest(platform=platform):
                self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, platform)))
                self.assertEqual(page.request.get.call_args.args[0], probe["identity_url"])
                response.json.return_value = {"success": True}
                self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, platform)))
                response.ok = False
                self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, platform)))

    def test_read_only_identity_api_rejects_redirected_response(self):
        probe = auth.ARTICLE_LOGIN_PROBES["yidian"]
        response = SimpleNamespace(ok=True, url="https://mp.yidianzixun.com.attacker.example/api",
                                   json=AsyncMock(return_value={"status": "success", "result": {"mediaId": "fixture"}}))
        page = SimpleNamespace(url=probe["url"], request=SimpleNamespace(get=AsyncMock(return_value=response)),
                                   evaluate=AsyncMock(return_value=None))
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "yidian")))
        response.json.assert_not_awaited()

    def test_chejiahao_identity_uses_only_its_exact_official_api_host(self):
        probe = auth.ARTICLE_LOGIN_PROBES["chejiahao"]
        response = SimpleNamespace(ok=True, url=probe["identity_url"],
                                   json=AsyncMock(return_value={"returncode": 0, "result": {"userid": "12345", "role": 2}}))
        page = SimpleNamespace(url=probe["url"], request=SimpleNamespace(get=AsyncMock(return_value=response)),
                                   evaluate=AsyncMock(return_value=None))
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))
        for destination in ("https://creator.autohome.com.cn.attacker.example/openapi/ypttd/yjc/csc/creator/creatorinfo",
                            "https://chejiahao.autohome.com.cn/openapi/ypttd/yjc/csc/creator/creatorinfo",
                            "https://creator.autohome.com.cn/login",
                            "http://creator.autohome.com.cn/openapi/ypttd/yjc/csc/creator/creatorinfo"):
            response.url = destination
            with self.subTest(destination=destination):
                self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))
        response.url = probe["identity_url"]
        for identity in (None, {}, {"role": 2}, {"userid": False, "role": 2},
                         {"userid": 0, "role": 2}, {"userid": -1, "role": 2},
                         {"userid": "unknown", "role": 2}, {"userid": "  ", "role": 2},
                         {"userid": {"id": 12345}, "role": 2}, {"userid": "12345", "role": 1}):
            response.json.return_value = {"returncode": 0, "result": identity}
            with self.subTest(identity=identity):
                self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))
        for code in (False, "0", 401, 403, None):
            response.json.return_value = {"returncode": code, "result": {"userid": "12345", "role": 2}}
            self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))
        page.evaluate.return_value = "fixture-oa-token"
        response.json.return_value = {"returncode": 0, "result": {"userid": "12345", "role": 3}}
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))
        self.assertEqual(page.request.get.call_args.kwargs["headers"]["Authorization"], "fixture-oa-token")
        response.json.return_value = {"returncode": 401, "result": {}}
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "chejiahao")))

    def test_page_identity_must_be_boolean_positive(self):
        for platform in ("dayu", "xueqiu", "jingdong", "douban", "yiche", "dongchedi"):
            page = SimpleNamespace(url=auth.ARTICLE_LOGIN_PROBES[platform]["url"],
                                   wait_for_function=AsyncMock(), evaluate=AsyncMock(return_value=True))
            self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, platform)))
            for missing in (False, None, "true", 1):
                page.evaluate.return_value = missing
                self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, platform)))

    def test_editor_probe_requires_unique_editable_fields_and_action(self):
        probe = auth.ARTICLE_LOGIN_PROBES["kuaichuan"]
        page = MagicMock(url=probe["url"])
        fields = {}
        for key in ("title", "body", "action"):
            match = MagicMock()
            match.first.wait_for = AsyncMock()
            match.count = AsyncMock(return_value=1)
            match.nth.return_value.is_visible = AsyncMock(return_value=True)
            match.nth.return_value.is_editable = AsyncMock(return_value=True)
            fields[probe[key]] = match
        page.locator.side_effect = fields.__getitem__
        self.assertTrue(asyncio.run(auth.article_account_is_logged_in(page, "kuaichuan")))
        fields[probe["body"]].nth.return_value.is_editable.return_value = False
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "kuaichuan")))
        fields[probe["body"]].nth.return_value.is_editable.return_value = True
        fields[probe["body"]].count.return_value = 2
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "kuaichuan")))
        fields[probe["body"]].count.return_value = 1
        fields[probe["action"]].first.wait_for.side_effect = RuntimeError("No publisher controls")
        self.assertFalse(asyncio.run(auth.article_account_is_logged_in(page, "kuaichuan")))

    def test_manual_login_rejects_wrong_account_type(self):
        status = Queue()
        with patch.object(login, "async_playwright") as browser:
            self.assertFalse(asyncio.run(login.article_account_cookie_gen("fixture", status, "csdn", 18)))
        self.assertEqual(status.get_nowait(), "500")
        browser.assert_not_called()

    @patch.dict(ACCOUNT_UNAVAILABLE_REASONS, PAUSED_AUTOMOTIVE_ACCOUNTS)
    def test_paused_automotive_accounts_never_open_browser_or_validate_cookie(self):
        with patch.object(login, "async_playwright") as browser, \
                patch.object(auth, "cookie_auth_article_account", new=AsyncMock()) as check:
            for kind in (22, 23, 24):
                status = Queue()
                self.assertFalse(asyncio.run(login.article_account_cookie_gen("fixture", status, NEW_ACCOUNTS[kind], kind)))
                self.assertEqual(status.get_nowait(), "500")
                self.assertFalse(asyncio.run(auth.check_cookie(kind, "fixture.json")))
            browser.assert_not_called()
            check.assert_not_awaited()

    def test_headless_host_offers_cookie_import_without_launch(self):
        status = Queue()
        with patch("sys.platform", "linux"), patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}), \
                patch.object(login, "async_playwright") as browser:
            self.assertFalse(asyncio.run(login.article_account_cookie_gen("fixture", status, "yidian", 12)))
        self.assertEqual(status.get_nowait(), "IMPORT_COOKIE")
        browser.assert_not_called()


class ExtendedArticleAccountRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sau_backend
        cls.backend = sau_backend

    def test_new_login_types_dispatch_to_generic_article_login(self):
        with patch.object(self.backend, "article_account_cookie_gen", new=AsyncMock(return_value=True)) as start:
            for kind, platform in NEW_ACCOUNTS.items():
                status = Queue()
                self.backend.run_async_function(str(kind), "fixture", status)
                if kind in ACCOUNT_UNAVAILABLE_REASONS:
                    self.assertEqual(status.get_nowait(), "500")
                    continue
                start.assert_awaited_with("fixture", status, platform, kind)
                self.assertTrue(status.empty())

    def test_video_requests_rejected_before_any_batch_starts(self):
        client = self.backend.app.test_client()
        with patch.dict(self.backend.app.extensions, {"legacy_article_publish": MagicMock()}) as extensions:
            for kind in NEW_ACCOUNTS:
                for route, payload in (("/postVideo", {"type": kind, "contentType": "video"}),
                                       ("/postVideoBatch", [{"type": 10, "contentType": "article"},
                                                            {"type": kind, "contentType": "video"}])):
                    with self.subTest(kind=kind, route=route):
                        response = client.post(route, json=payload)
                        self.assertEqual(response.status_code, 400)
                        self.assertIn("仅支持文章", response.json["msg"])
            extensions["legacy_article_publish"].assert_not_called()

    def test_implicit_and_named_article_requests_are_routed_as_articles(self):
        for kind, platform in NEW_ACCOUNTS.items():
            self.assertTrue(self.backend._is_article_request({"type": kind}))
            self.assertTrue(self.backend._is_article_request({"type": platform, "contentType": "article"}))

    def test_legacy_article_routes_normalize_named_platforms(self):
        client = self.backend.app.test_client()
        submit = MagicMock(return_value={"id": "fixture-batch"})
        with patch.dict(self.backend.app.extensions, {"legacy_article_publish": submit}):
            for route, body in (("/postVideo", {"type": "csdn"}), ("/postVideoBatch", [{"type": "yidian"}])):
                response = client.post(route, json=body)
                self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(submit.call_args_list[0].args[0]["type"], 20)
            self.assertEqual(submit.call_args_list[1].args[0]["type"], 12)

    @patch.dict(ACCOUNT_UNAVAILABLE_REASONS, PAUSED_AUTOMOTIVE_ACCOUNTS)
    def test_paused_automotive_article_routes_reject_before_any_batch_starts(self):
        client = self.backend.app.test_client()
        submit = MagicMock(return_value={"id": "fixture-batch"})
        with patch.dict(self.backend.app.extensions, {"legacy_article_publish": submit}):
            for kind, platform in ((22, "chejiahao"), (23, "yiche"), (24, "dongchedi")):
                body = {"type": platform, "contentType": "article"}
                for route, payload in (("/postVideo", body), ("/postVideoBatch", [body])):
                    with self.subTest(platform=platform, route=route):
                        response = client.post(route, json=payload)
                        self.assertEqual(response.status_code, 400, response.json)
                        self.assertEqual(response.json["msg"], ACCOUNT_UNAVAILABLE_REASONS[kind])
                self.assertEqual(body["type"], platform)
            response = client.post("/postVideoBatch", json=[{"type": "weibo"}, {"type": "chejiahao"}])
            self.assertEqual(response.status_code, 400)
            submit.assert_not_called()

    def test_jingdong_refresh_updates_status_without_rewriting_credentials(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "db").mkdir()
            (base / "cookiesFile").mkdir()
            cookie = base / "cookiesFile" / "existing.json"
            cookie.write_text("existing-local-session", encoding="utf-8")
            with sqlite3.connect(base / "db" / "database.db") as conn:
                conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
                conn.execute("INSERT INTO user_info VALUES(1,18,'existing.json','existing-account',1)")
            with patch.object(self.backend, "BASE_DIR", base), \
                    patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=False)) as check:
                response = self.backend.app.test_client().get("/getValidAccounts")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"][0][4], 0)
            self.assertEqual(cookie.read_text(encoding="utf-8"), "existing-local-session")
            check.assert_awaited_once_with(18, "existing.json")

    @patch.dict(ACCOUNT_UNAVAILABLE_REASONS, PAUSED_AUTOMOTIVE_ACCOUNTS)
    def test_paused_automotive_import_and_refresh_preserve_existing_accounts(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "db").mkdir()
            (base / "cookiesFile").mkdir()
            rows = [(kind, kind, f"existing-{kind}.json", f"fixture-{kind}", kind % 2) for kind in (22, 23, 24)]
            for row in rows:
                (base / "cookiesFile" / row[2]).write_text("existing-local-session", encoding="utf-8")
            with sqlite3.connect(base / "db" / "database.db") as conn:
                conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
                conn.executemany("INSERT INTO user_info VALUES(?,?,?,?,?)", rows)
            with patch.object(self.backend, "BASE_DIR", base), \
                    patch.object(self.backend, "check_cookie", new=AsyncMock()) as check:
                client = self.backend.app.test_client()
                for kind in (22, 23, 24):
                    for route in ("/importCookie", "/uploadCookie"):
                        body = json.dumps(fake_state(ACCOUNT_COOKIE_DOMAINS[kind][0])).encode()
                        response = client.post(route, data={"platform": NEW_ACCOUNTS[kind], "name": "fixture",
                                                            "id": str(kind), "file": (io.BytesIO(body), "fixture.json")})
                        with self.subTest(kind=kind, route=route):
                            self.assertEqual(response.status_code, 400)
                            self.assertEqual(response.json["msg"], ACCOUNT_UNAVAILABLE_REASONS[kind])
                response = client.get("/getValidAccounts")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["data"], [list(row) for row in rows])
                check.assert_not_awaited()
            with sqlite3.connect(base / "db" / "database.db") as conn:
                self.assertEqual(conn.execute("SELECT * FROM user_info ORDER BY id").fetchall(), rows)
            self.assertEqual(len(list((base / "cookiesFile").iterdir())), 3)
            for row in rows:
                self.assertEqual((base / "cookiesFile" / row[2]).read_text(), "existing-local-session")

    def test_each_new_platform_can_import_and_validate_isolated_session(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "db").mkdir()
            (base / "cookiesFile").mkdir()
            with sqlite3.connect(base / "db" / "database.db") as conn:
                conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            with patch.object(self.backend, "BASE_DIR", base), \
                    patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)) as check:
                client = self.backend.app.test_client()
                for kind, platform in NEW_ACCOUNTS.items():
                    if kind in ACCOUNT_UNAVAILABLE_REASONS:
                        continue
                    body = json.dumps(fake_state(ACCOUNT_COOKIE_DOMAINS[kind][0])).encode()
                    response = client.post("/importCookie", data={"platform": platform, "name": "fixture",
                                                                  "file": (io.BytesIO(body), "fixture.json")})
                    with self.subTest(platform=platform):
                        self.assertEqual(response.status_code, 200, response.json)
                        self.assertEqual(response.json["data"]["type"], kind)
                        check.assert_awaited_with(kind, check.call_args.args[1])
                self.assertEqual(len(list((base / "cookiesFile").glob("*.json"))),
                                 len(set(NEW_ACCOUNTS) - set(ACCOUNT_UNAVAILABLE_REASONS)))

    def test_named_login_uses_registered_article_account_type(self):
        client = self.backend.app.test_client()
        with patch.object(self.backend.threading, "Thread") as thread, \
                patch.object(self.backend, "sse_stream", return_value=iter(["data: MANUAL_LOGIN\n\n"])), \
                patch.dict(self.backend.active_queues, {}, clear=True):
            for kind, platform in ((18, "jingdong"), (22, "chejiahao"), (23, "yiche"), (24, "dongchedi")):
                with self.subTest(platform=platform):
                    response = client.get("/login", query_string={"type": platform, "id": "fixture"})
                    if kind in ACCOUNT_UNAVAILABLE_REASONS:
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.json["msg"], ACCOUNT_UNAVAILABLE_REASONS[kind])
                        self.assertEqual(thread.call_count, 1)
                        continue
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.mimetype, "text/event-stream")
                    self.assertEqual(thread.call_args.kwargs["args"][:2], (str(kind), "fixture"))
                    thread.return_value.start.assert_called()
                    response.close()


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "本地浏览器用例需显式启用")
class JingdongIdentityBrowserTests(unittest.IsolatedAsyncioTestCase):
    """以本地页面模拟官方身份形状，所有请求拦截，不访问京东或使用真实凭据。"""

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        from utils.articles.browser import launch_article_browser
        import conf
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, conf.LOCAL_CHROME_PATH)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<html><body>fixture</body></html>"))
        await self.page.goto("https://dr.jd.com/n/publish-article.html")

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def test_requires_positive_talent_id_and_name_from_current_page(self):
        for user in (None, {}, {"name": "fixture"}, {"id": 42},
                     {"id": 0, "name": "fixture"}, {"id": -1, "name": "fixture"},
                     {"id": True, "name": "fixture"}, {"id": {}, "name": "fixture"},
                     {"id": 42, "name": "   "}):
            with self.subTest(user=user):
                await self.page.evaluate("user => { window._gdata = {user}; }", user)
                self.assertFalse(await auth.article_account_is_logged_in(self.page, "jingdong", timeout=50))
        for user in ({"id": 42, "name": "fixture"}, {"id": "42", "name": "fixture"}):
            await self.page.evaluate("user => { window._gdata = {user}; }", user)
            self.assertTrue(await auth.article_account_is_logged_in(self.page, "jingdong", timeout=50))

    async def test_login_redirect_or_similar_host_rejects_even_with_identity(self):
        for url in ("https://dr.jd.com/page/login.html?returnurl=/n/publish-article.html",
                    "https://dr.jd.com.attacker.example/n/publish-article.html"):
            await self.page.goto(url)
            await self.page.evaluate("() => { window._gdata = {user: {id: 42, name: 'fixture'}}; }")
            self.assertFalse(await auth.article_account_is_logged_in(self.page, "jingdong", timeout=50))


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "本地浏览器用例需显式启用")
class AutomotiveIdentityBrowserTests(unittest.IsolatedAsyncioTestCase):
    """执行真实探针 JavaScript；平台页面与身份响应均为本地隔离数据。"""

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        from utils.articles.browser import launch_article_browser
        import conf
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, conf.LOCAL_CHROME_PATH)
        self.page = await self.browser.new_page()
        await self.page.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<html><body>fixture</body></html>"))

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def test_yiche_requires_server_confirmed_login_not_cookie(self):
        await self.page.goto(auth.ARTICLE_LOGIN_PROBES["yiche"]["url"])
        await self.page.evaluate("() => { document.cookie='username=fixture'; localStorage.setItem('userInfoStatus', '{\"authStatus\":1}'); }")
        self.assertFalse(await auth.article_account_is_logged_in(self.page, "yiche", timeout=50))
        for account in ({"isLogined": True, "userId": 12345}, {"isLogined": True, "userId": "12345"}):
            await self.page.evaluate("account => { window.Bitauto = {Login:{result:account}}; }", account)
            self.assertTrue(await auth.article_account_is_logged_in(self.page, "yiche", timeout=50))
        for account in ({"isLogined": False}, {"isLogined": "true", "userId": 12345},
                        {"isLogined": True, "userId": 0}, {"isLogined": True, "userId": True},
                        {"isLogined": True, "userId": "unknown"}, {"userId": 12345}):
            await self.page.evaluate("account => { window.Bitauto.Login.result = account; }", account)
            self.assertFalse(await auth.article_account_is_logged_in(self.page, "yiche", timeout=50))

    async def test_dongchedi_requires_successful_user_query_identity(self):
        await self.page.goto(auth.ARTICLE_LOGIN_PROBES["dongchedi"]["url"])
        await self.page.evaluate("() => { document.cookie='sessionid=expired-fixture'; window.Garr = {}; }")
        self.assertFalse(await auth.article_account_is_logged_in(self.page, "dongchedi", timeout=50))
        for user_id in (12345, "12345"):
            await self.page.evaluate("id => { window.Garr.pgc_info = {user:{id},media:{}}; }", user_id)
            self.assertTrue(await auth.article_account_is_logged_in(self.page, "dongchedi", timeout=50))
        for user_id in (None, False, True, 0, -1, 1.5, "0", "unknown", "", {}):
            await self.page.evaluate("id => { window.Garr.pgc_info = {user:{id},media:{}}; }", user_id)
            self.assertFalse(await auth.article_account_is_logged_in(self.page, "dongchedi", timeout=50))

    async def test_identity_on_login_or_similar_domain_cannot_validate_account(self):
        for platform in ("yiche", "dongchedi"):
            host = auth.ARTICLE_LOGIN_PROBES[platform]["host"]
            for url in (f"https://{host}/login/", f"https://{host}.attacker.example/article"):
                await self.page.goto(url)
                await self.page.evaluate("() => { window.Bitauto={Login:{result:{isLogined:true,userId:12345}}}; window.Garr={pgc_info:{user:{id:12345}}}; }")
                self.assertFalse(await auth.article_account_is_logged_in(self.page, platform, timeout=50))


if __name__ == "__main__":
    unittest.main()
