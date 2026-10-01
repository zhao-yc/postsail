"""文章 CLI 的离线契约验证，不连接真实平台或真实服务。"""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

import sau_cli
from utils.articles.cli import ArticleApiClient, ArticleCliError, prepare_content


def response(data=None, *, code=200, status=200, msg="处理完成"):
    """模拟后端统一响应，不依赖 Flask 测试客户端。"""
    return SimpleNamespace(status_code=status, json=lambda: {"code": code, "msg": msg, "data": data})


class ArticleContentImportTests(unittest.TestCase):
    def test_markdown_local_images_references_and_html_preserve_remote_and_code(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "图 (1).png").write_bytes(b"image")
            article = directory / "article.md"
            article.write_text(
                "# 标题\n![一](<图 (1).png>)\n![二][本地图]\n[本地图]: <图 (1).png>\n"
                '<img src="图 (1).png" alt="三">\n'
                "![外链](https://example.com/public.png)\n"
                "`![代码](不存在.png)`\n```markdown\n![围栏](不存在.png)\n```\n"
                "    ![缩进代码](不存在.png)\n",
                encoding="utf-8",
            )
            client = Mock()
            client.upload_asset.return_value = {"id": 8, "url": "/api/article-assets/8/content"}
            content, kind = prepare_content(client, article, None)
        self.assertEqual(kind, "markdown")
        self.assertEqual(client.upload_asset.call_count, 1)
        self.assertEqual(content.count("/api/article-assets/8/content"), 3)
        self.assertIn("https://example.com/public.png", content)
        self.assertIn("![代码](不存在.png)", content)
        self.assertIn("![围栏](不存在.png)", content)

    def test_parenthesis_and_escaped_markdown_image_path(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "image(1).png").write_bytes(b"image")
            article = directory / "article.md"
            article.write_text("![一](image(1).png)\n![二](image\\(1\\).png)", encoding="utf-8")
            client = Mock()
            client.upload_asset.return_value = {"id": 2, "url": "/api/article-assets/2/content"}
            content, _ = prepare_content(client, article, None)
        self.assertEqual(client.upload_asset.call_count, 1)
        self.assertEqual(content.count("/api/article-assets/2/content"), 2)

    def test_html_replaces_src_not_data_src_or_other_attributes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "local.png").write_bytes(b"image")
            article = directory / "article.html"
            article.write_text('<p>正文</p><img data-src="lazy.png" src="local.png" alt="例图">', encoding="utf-8")
            client = Mock()
            client.upload_asset.return_value = {"id": 8, "url": "/api/article-assets/8/content"}
            content, kind = prepare_content(client, article, None)
        self.assertEqual(kind, "html")
        self.assertIn('data-src="lazy.png"', content)
        self.assertIn('src="/api/article-assets/8/content"', content)
        self.assertIn('alt="例图"', content)

    def test_all_paths_validated_before_any_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "article"
            directory.mkdir()
            (directory / "valid.png").write_bytes(b"image")
            (directory.parent / "private.png").write_bytes(b"private")
            article = directory / "article.md"
            article.write_text("![允许](valid.png)\n![禁止](../private.png)", encoding="utf-8")
            client = Mock()
            with self.assertRaisesRegex(ArticleCliError, "越出文章目录"):
                prepare_content(client, article, None)
            client.upload_asset.assert_not_called()

    def test_encoded_traversal_and_non_http_scheme_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            article = Path(temp) / "article.md"
            client = Mock()
            for destination in ("%2e%2e/private.png", "file:///private.png", "data:image/png;base64,test", "C:\\private.png"):
                with self.subTest(destination=destination):
                    article.write_text(f"![禁止]({destination})", encoding="utf-8")
                    with self.assertRaises(ArticleCliError):
                        prepare_content(client, article, None)
            client.upload_asset.assert_not_called()

    def test_symlink_cannot_escape_article_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "article"
            directory.mkdir()
            secret = directory.parent / "private.png"
            secret.write_bytes(b"private")
            try:
                (directory / "shortcut.png").symlink_to(secret)
            except OSError:
                self.skipTest("当前环境不允许创建符号链接")
            article = directory / "article.md"
            article.write_text("![禁止](shortcut.png)", encoding="utf-8")
            with self.assertRaisesRegex(ArticleCliError, "越出文章目录"):
                prepare_content(Mock(), article, None)

    def test_plaintext_never_scans_fake_image_markup(self):
        with tempfile.TemporaryDirectory() as temp:
            article = Path(temp) / "article.txt"
            article.write_text("![纯文本](不存在.png)", encoding="utf-8")
            client = Mock()
            content, kind = prepare_content(client, article, None)
        self.assertEqual(kind, "text")
        self.assertEqual(content, "![纯文本](不存在.png)")
        client.upload_asset.assert_not_called()


class ArticleCliContractTests(unittest.TestCase):
    def run_command(self, argv, responses):
        """通过真实 sau 入口解析参数，仅替换网络边界。"""
        session = Mock()
        session.request.side_effect = responses
        stdout = io.StringIO()
        with patch("utils.articles.cli.requests.Session", return_value=session), contextlib.redirect_stdout(stdout):
            code = sau_cli.main(["article", "--json", *argv])
        return code, json.loads(stdout.getvalue()), session

    def test_flags_before_and_after_action_do_not_clobber(self):
        args = sau_cli.build_parser().parse_args(["article", "--server", "http://example.test", "--json", "accounts"])
        self.assertEqual(args.platform, "article")
        self.assertTrue(args.json)
        self.assertEqual(args.server, "http://example.test")
        args = sau_cli.build_parser().parse_args(["article", "accounts", "--server", "http://example.test", "--json"])
        self.assertEqual(args.server, "http://example.test")
        self.assertTrue(args.json)

    def test_import_uploads_local_assets_then_posts_original_format(self):
        with tempfile.TemporaryDirectory() as temp:
            article = Path(temp) / "article.md"
            (Path(temp) / "body.png").write_bytes(b"image")
            cover = Path(temp) / "cover.png"
            cover.write_bytes(b"cover")
            article.write_text("# 中文标题\n![正文](body.png)", encoding="utf-8")
            code, output, session = self.run_command(
                ["import", "--file", str(article), "--title", "中文标题", "--cover", str(cover), "--tags", "#技术,教程"],
                [response({"id": 1, "url": "/api/article-assets/1/content"}),
                 response({"id": 2, "url": "/api/article-assets/2/content"}), response({"id": 7, "revision": 1})],
            )
        self.assertEqual(code, 0)
        self.assertEqual(output["data"]["revision"], 1)
        payload = session.request.call_args.kwargs["json"]
        self.assertEqual(payload["format"], "markdown")
        self.assertIn("/api/article-assets/1/content", payload["content"])
        self.assertEqual(payload["cover_asset_id"], 2)
        self.assertEqual(payload["tags"], ["技术", "教程"])
        self.assertIn("files", session.request.call_args_list[0].kwargs)

    def test_update_only_touches_selected_fields_and_checks_revision(self):
        code, _, session = self.run_command(["update", "7", "--title", "更新标题"], [response({"revision": 4}), response({"id": 7, "revision": 5})])
        self.assertEqual(code, 0)
        self.assertEqual(session.request.call_args.args[0], "PATCH")
        self.assertEqual(session.request.call_args.kwargs["json"], {"title": "更新标题", "expected_revision": 4})

    def test_update_explicit_revision_can_clear_cover_and_tags(self):
        code, _, session = self.run_command(["update", "7", "--revision", "4", "--clear-cover", "--tags", ""], [response({"id": 7, "revision": 5})])
        self.assertEqual(code, 0)
        self.assertEqual(session.request.call_count, 1)
        self.assertEqual(session.request.call_args.kwargs["json"], {"cover_asset_id": None, "tags": [], "expected_revision": 4})

    def test_publish_fetches_current_revision_and_defaults_to_formal_publish(self):
        code, output, session = self.run_command(
            ["publish", "7", "--platform", "zhihu", "--account-id", "2", "--account-id", "3", "--idempotency-key", "stable-key"],
            [response({"revision": 4}), response({"id": 11, "tasks": [{"id": 12, "status": "queued"}]})],
        )
        self.assertEqual(code, 0)
        payload = session.request.call_args.kwargs["json"]
        self.assertEqual(payload["mode"], "publish")
        self.assertEqual(payload["revision"], 4)
        self.assertEqual([target["account_id"] for target in payload["targets"]], [2, 3])
        self.assertEqual(output["idempotency_key"], "stable-key")
        self.assertEqual(output["data"]["tasks"][0]["status"], "queued")

    def test_multiplatform_targets_preserve_overrides_and_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            targets = Path(temp) / "targets.json"
            items = [{"platform": "zhihu", "account_id": 2, "overrides": {"options": {"statement": "AI辅助创作"}}},
                     {"platform": "baijiahao", "account_id": 3, "overrides": {"title": "平台标题", "cover_asset_id": 5}}]
            targets.write_text(json.dumps(items), encoding="utf-8")
            code, _, session = self.run_command(["publish", "7", "--revision", "4", "--targets", str(targets), "--preview"], [response({"id": 11})])
        self.assertEqual(code, 0)
        payload = session.request.call_args.kwargs["json"]
        self.assertEqual(payload["mode"], "preview")
        self.assertEqual(payload["targets"], items)
        self.assertTrue(payload["idempotency_key"])

    def test_rejects_duplicate_targets_before_network(self):
        code, output, session = self.run_command(["publish", "7", "--platform", "zhihu", "--account-id", "2", "--account-id", "2"], [])
        self.assertEqual(code, 1)
        self.assertIn("重复", output["msg"])
        session.request.assert_not_called()

    def test_account_platform_uses_existing_api_ids(self):
        with patch.dict(os.environ, {"OMNIPOST_API_URL": "http://service.test:5409"}):
            code, output, session = self.run_command(["accounts", "--platform", "sohu"], [response([{"id": 2, "platform": "sohu"}, {"id": 3, "platform": "zhihu"}])])
        self.assertEqual(code, 0)
        self.assertEqual(session.request.call_args.args[1], "http://service.test:5409/api/article-accounts")
        self.assertEqual([account["id"] for account in output["data"]], [2])

    def test_wait_stops_after_submitted_without_assuming_published(self):
        code, output, session = self.run_command(["status", "11", "--wait"], [response({"id": 11, "tasks": [{"id": 12, "status": "submitted"}]})])
        self.assertEqual(code, 0)
        self.assertEqual(session.request.call_count, 1)
        self.assertEqual(output["data"]["tasks"][0]["status"], "submitted")

    def test_wait_polls_queued_and_ends_on_needs_action(self):
        with patch("utils.articles.cli.time.sleep") as sleep:
            code, output, session = self.run_command(
                ["status", "11", "--wait"],
                [response({"tasks": [{"status": "queued"}]}), response({"tasks": [{"status": "needs_action"}]})],
            )
        self.assertEqual(code, 0)
        self.assertEqual(session.request.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(output["data"]["tasks"][0]["status"], "needs_action")

    def test_wait_timeout_has_bounded_exit_and_keeps_latest_batch(self):
        with patch("utils.articles.cli.time", SimpleNamespace(monotonic=Mock(side_effect=[0, 3]), sleep=Mock())):
            code, output, session = self.run_command(["status", "11", "--wait", "--timeout", "1"], [response({"tasks": [{"status": "running"}]})])
        self.assertEqual(code, 2)
        self.assertTrue(output["wait_timed_out"])
        self.assertEqual(output["data"]["tasks"][0]["status"], "running")
        self.assertEqual(session.request.call_args.kwargs["timeout"], 1)

    def test_retry_and_resolve_have_distinct_safe_endpoints(self):
        code, _, session = self.run_command(["retry", "12"], [response({"id": 12, "status": "queued"})])
        self.assertEqual(code, 0)
        self.assertTrue(session.request.call_args.args[1].endswith("/12/retry"))
        code, _, session = self.run_command(["resolve", "12", "--resolution", "published", "--platform-url", "https://example.com/article/1", "--note", "已核对平台页面"], [response({"id": 12, "status": "published"})])
        self.assertEqual(code, 0)
        self.assertTrue(session.request.call_args.args[1].endswith("/12/resolve"))
        self.assertEqual(session.request.call_args.kwargs["json"]["resolution"], "published")

    def test_http_or_business_error_returns_json_and_nonzero(self):
        code, output, _ = self.run_command(["get", "7"], [response(None, status=409, code=409, msg="修订号已变化")])
        self.assertEqual(code, 1)
        self.assertEqual(output["msg"], "修订号已变化")

    def test_publish_network_failure_preserves_idempotency_key(self):
        code, output, _ = self.run_command(
            ["publish", "7", "--revision", "4", "--platform", "zhihu", "--account-id", "2", "--idempotency-key", "stable-key"],
            [requests.ConnectionError("连接中断")],
        )
        self.assertEqual(code, 1)
        self.assertEqual(output["idempotency_key"], "stable-key")

    def test_article_module_does_not_import_flask(self):
        source = Path("utils/articles/cli.py").read_text(encoding="utf-8")
        self.assertNotIn("from flask", source)
        self.assertNotIn("import flask", source)


class ArticleCliApiIntegrationTests(unittest.TestCase):
    """CLI 调用真实隔离 API，验证资源 ID 和后端契约，不运行平台浏览器。"""

    def setUp(self):
        from flask import Flask
        from utils.articles.routes import register_article_routes

        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "cookiesFile").mkdir()
        for name in ("zhihu.json", "toutiao.json"):
            (self.base / "cookiesFile" / name).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
        self.database = self.base / "test.sqlite"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            connection.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", [
                (1, 9, "zhihu.json", "隔离知乎账号", 1), (2, 7, "toutiao.json", "隔离头条账号", 1),
            ])
        app = Flask(__name__)
        app.config.update(ARTICLE_WORKER_ENABLED=False, ARTICLE_BASE_DIR=self.base, ARTICLE_DB_PATH=self.database)
        register_article_routes(app, SimpleNamespace(BASE_DIR=self.base))
        self.web = app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, method, url, **kwargs):
        """把 requests 的 JSON 和 multipart 参数交给 Flask 测试客户端。"""
        from urllib.parse import urlsplit

        body = kwargs.get("json")
        files = kwargs.get("files")
        if files:
            data = {key: (io.BytesIO(item[1].read()), item[0], item[2]) for key, item in files.items()}
            result = self.web.open(urlsplit(url).path, method=method, data=data)
        else:
            result = self.web.open(urlsplit(url).path, method=method, json=body)
        return SimpleNamespace(status_code=result.status_code, json=result.get_json)

    def command(self, *argv):
        """不监听 TCP 端口，不访问真实项目数据库。"""
        session = SimpleNamespace(request=self.request)
        stdout = io.StringIO()
        with patch("utils.articles.cli.requests.Session", return_value=session), contextlib.redirect_stdout(stdout):
            code = sau_cli.main(["article", "--json", *argv])
        return code, json.loads(stdout.getvalue())

    def test_real_api_import_update_preview_publish_and_resolve(self):
        from PIL import Image
        from utils.articles.service import ArticleService

        draft = self.base / "draft"
        draft.mkdir()
        Image.new("RGB", (640, 480), "white").save(draft / "image.png")
        article_file = draft / "article.md"
        article_file.write_text("## 中文小节\n\n带有 **加粗** 的段落。\n\n![配图](image.png)", encoding="utf-8")
        code, imported = self.command("import", "--file", str(article_file), "--title", "独立多平台测试教程", "--cover", str(draft / "image.png"))
        self.assertEqual(code, 0, imported)
        article = imported["data"]
        self.assertRegex(article["id"], r"^[0-9a-f]{32}$")
        self.assertRegex(article["cover_asset_id"], r"^[0-9a-f]{32}$")
        self.assertIn("data-asset-id", article["content_html"])
        self.assertIn("<h2>", article["content_html"])
        self.assertIn("<strong>", article["content_html"])
        code, updated = self.command("update", article["id"], "--title", "修订后的独立测试教程", "--revision", "1")
        self.assertEqual(code, 0, updated)
        self.assertEqual(updated["data"]["revision"], 2)
        code, accounts = self.command("accounts", "--platform", "zhihu")
        self.assertEqual([item["id"] for item in accounts["data"]], [1])
        self.assertNotIn("filePath", str(accounts))
        code, caps = self.command("capabilities")
        self.assertEqual(len(caps["data"]["platforms"]), 4)
        self.assertTrue(all(not item["live_verified"] for item in caps["data"]["platforms"]))

        def runner(snapshot, cookie_file, assets, on_submit, evidence_dir):
            """使用确定的假回执，验证任务状态，绝不访问内容平台。"""
            if snapshot["mode"] == "preview":
                return {"status": "previewed", "message": "模拟预览完成"}
            on_submit()
            return {"status": "unknown", "message": "模拟提交后断线"}

        service = ArticleService(self.database, self.base / "articleData" / "assets", self.base / "cookiesFile",
                                 self.base / "articleData" / "evidence", runner=runner)
        self.assertTrue(service.acquire())
        code, preview = self.command("publish", article["id"], "--preview", "--platform", "zhihu", "--account-id", "1", "--idempotency-key", "integration-preview")
        self.assertEqual(code, 0, preview)
        self.assertRegex(preview["data"]["id"], r"^[0-9a-f]{32}$")
        service.run_next()
        code, preview_status = self.command("status", preview["data"]["id"], "--wait")
        self.assertEqual(code, 0, preview_status)
        self.assertEqual(preview_status["data"]["tasks"][0]["status"], "previewed")
        code, publication = self.command("publish", article["id"], "--platform", "zhihu", "--account-id", "1", "--idempotency-key", "integration-publish")
        self.assertEqual(code, 0, publication)
        code, duplicate = self.command("publish", article["id"], "--platform", "zhihu", "--account-id", "1", "--idempotency-key", "integration-publish")
        self.assertEqual(code, 0, duplicate)
        self.assertEqual(publication["data"]["id"], duplicate["data"]["id"])
        service.run_next()
        code, status = self.command("status", publication["data"]["id"], "--wait")
        task = status["data"]["tasks"][0]
        self.assertEqual(task["status"], "unknown")
        code, rejected = self.command("retry", task["id"])
        self.assertEqual(code, 1, rejected)
        code, resolution = self.command("resolve", task["id"], "--resolution", "not_published", "--note", "隔离测试确认没有发表")
        self.assertEqual(code, 0, resolution)
        self.assertTrue(resolution["data"]["tasks"][0]["retry_allowed"])
        code, retried = self.command("retry", task["id"])
        self.assertEqual(code, 0, retried)
        self.assertEqual(retried["data"]["tasks"][0]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
