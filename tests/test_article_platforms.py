"""图文平台公共约定、图片归属和明确回执的回归测试。"""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from utils.articles.adapter import create_adapter, validate_task
from utils.articles.browser import is_uploaded_image, read_result_evidence, install_native_preview_request_guard, receipt_status
from utils.articles.cli import ARTICLE_PLATFORMS
from utils.articles.model import ArticleError, capabilities, validate_options
from utils.articles.platforms import NOTE_PLATFORMS, PLATFORMS


class PlatformContractTests(unittest.TestCase):
    def test_all_platforms_have_distinct_account_types_and_adapters(self):
        """API、CLI、执行器覆盖一致，企鹅号绝不能复用视频号账号。"""
        expected = {"douyin": 3, "bilibili": 6, "baijiahao": 5, "toutiao": 7,
                    "weibo": 10, "zhihu": 9, "qiehao": 11, "sohu": 8,
                    "xiaohongshu": 1, "tencent": 2, "kuaishou": 4, "wechat": 12,
                    "jd": 13, "xiaohongshu_merchant": 14, "dongchedi": 15, "taobao": 16}
        self.assertEqual(set(ARTICLE_PLATFORMS), set(expected))
        self.assertEqual({item["platform"]: item["account_type"] for item in capabilities()}, expected)
        for platform in expected:
            adapter = create_adapter({"platform": platform, "title": "多平台文章测试",
                                      "mode": "preview", "options": {}, "tags": []}, Path("测试账号.json"), None)
            self.assertEqual(adapter.platform, platform)
        with self.assertRaisesRegex(ValueError, "不支持"):
            create_adapter({"platform": "unknown"}, Path("账号.json"), None)

    def test_implementation_is_not_reported_as_live_verified(self):
        """离线实现与真实发布验收分开，能力清单不伪造验收记录。"""
        for item in capabilities():
            self.assertFalse(item["scheduled"])
            self.assertIn("content_kind", item)
            self.assertEqual(set(item["verification"]), {"preview", "submitted", "published"})
            if item["platform"] in NOTE_PLATFORMS:
                self.assertEqual(item["content_mode"], "image_text")
                self.assertEqual(item["format_fallbacks"]["rich_text"], "plain_text_opt_in")
                self.assertNotIn("table", item["formats"])
                self.assertNotIn("bold", item["formats"])
            else:
                self.assertEqual(item["format_fallbacks"]["table"], "image")
            if item["platform"] == "douyin":
                self.assertTrue(all(item["verification"].values()))
                self.assertIn("话题、声明", item["verification_scope"])
                self.assertEqual(item["verification_date"], "2026-10-01")
            else:
                self.assertFalse(item["live_verified"])
                self.assertFalse(any(item["verification"].values()))

    def test_platform_options_cannot_be_ignored_or_truncated(self):
        """摘要超限、错误声明和不存在的平台选项必须在提交前拒绝。"""
        with self.assertRaisesRegex(ArticleError, "30"):
            validate_options("douyin", {"summary": "字" * 31})
        with self.assertRaisesRegex(ArticleError, "不支持"):
            validate_options("bilibili", {"category": "自动选择"})
        with self.assertRaises(ArticleError):
            validate_options("weibo", {"summary": 123})
        with self.assertRaisesRegex(ArticleError, "布尔"):
            validate_options("baijiahao", {"ai_generated": "false"})
        validate_options("baijiahao", {"ai_generated": False})
        validate_options("weibo", {"summary": "", "publish_text": ""})

    def test_required_cover_applies_to_new_platforms(self):
        for platform in ("douyin", "weibo", "wechat", "dongchedi"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "封面"):
                validate_task({"platform": platform, "title": "有效测试文章", "mode": "preview",
                               "content_html": "<p>正文</p>"}, {})

    def test_douyin_native_limits_and_explicit_link_conversion(self):
        """平台已核实的正文、图片、话题上限与链接策略不可静默绕过。"""
        snapshot = {"platform": "douyin", "title": "测试文章", "mode": "preview", "content_html": "<p>正文</p>"}
        for changes, message in (
            ({"content_html": "<p>" + "字" * 20001 + "</p>"}, "20000"),
            ({"content_html": '<img data-asset-id="图片">' * 31}, "30"),
            ({"tags": [str(i) for i in range(6)]}, "5"),
            ({"content_html": '<p><a href="https://example.org">原文</a></p>'}, "超链接"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_task({**snapshot, **changes}, {})
        validate_options("douyin", {"links_as_text": True})
        with self.assertRaisesRegex(ArticleError, "布尔"):
            validate_options("douyin", {"links_as_text": "true"})

    def test_new_platform_image_hosts_reject_lookalikes_and_local_previews(self):
        """只认所属平台已上传图片，外链和相似恶意域名不能冒充完成。"""
        hosts = {"douyin": "p3.douyinpic.com", "bilibili": "i0.hdslb.com",
                 "weibo": "wx1.sinaimg.cn", "qiehao": "inews.gtimg.com",
                 "xiaohongshu": "sns-img-qc.xhscdn.com", "kuaishou": "p3.yximgs.com",
                 "tencent": "finder.video.qq.com.wxapp.tc.qq.com", "wechat": "mmbiz.qpic.cn",
                 "jd": "img13.360buyimg.com", "xiaohongshu_merchant": "sns-img-qc.xhscdn.com",
                 "dongchedi": "p3-dcd.byteimg.com", "taobao": "img.alicdn.com"}
        for platform, host in hosts.items():
            self.assertTrue(is_uploaded_image({"src": f"https://{host}/a.jpg", "ready": True}, platform))
            for source in (f"https://{host}.example.com/a.jpg", f"blob:https://{host}/local",
                           "https://www.yinzon.com/未上传.jpg", f"https://{host}/pending.jpg"):
                ready = not source.endswith("pending.jpg")
                self.assertFalse(is_uploaded_image({"src": source, "ready": ready}, platform))

    def test_note_conversion_and_wechat_fields_are_explicit(self):
        for platform in ("xiaohongshu", "kuaishou", "tencent"):
            validate_options(platform, {"flatten_content": True})
            with self.assertRaisesRegex(ArticleError, "布尔"):
                validate_options(platform, {"flatten_content": "true"})
            with self.assertRaisesRegex(ArticleError, "不支持"):
                validate_options(platform, {"statement": "任意声明"})
        validate_options("wechat", {"author": "作者", "summary": "摘要"})
        with self.assertRaisesRegex(ArticleError, "8"):
            validate_options("wechat", {"author": "字" * 9})
        with self.assertRaisesRegex(ArticleError, "120"):
            validate_options("wechat", {"summary": "字" * 121})

    def test_merchant_and_commerce_require_explicit_platform_fields(self):
        required = {"product_id": "12345678", "shop_name": "测试店铺"}
        validate_options("xiaohongshu_merchant", required)
        for missing in required:
            for value in (None, "", "  "):
                options = {**required, missing: value}
                with self.subTest(missing=missing, value=value), self.assertRaisesRegex(ArticleError, "必须填写"):
                    validate_options("xiaohongshu_merchant", options)
        for value in (None, "", "  "):
            with self.assertRaisesRegex(ArticleError, "必须填写"):
                validate_options("taobao", {"statement": value})
        for statement in PLATFORMS["taobao"]["statement_options"]:
            validate_options("taobao", {"statement": statement})
        with self.assertRaisesRegex(ArticleError, "不受支持"):
            validate_options("taobao", {"statement": "自动选择"})
        with self.assertRaisesRegex(ArticleError, "不支持"):
            validate_options("taobao", {"statement": "内容无需标注", "product_links": "12345678"})
        validate_options("jd", {"product_links": "https://item.jd.com/12345678.html"})
        with self.assertRaisesRegex(ArticleError, "2000"):
            validate_options("jd", {"product_links": "1" * 2001})

    def test_new_platforms_reject_unsupported_tags_before_browser(self):
        for platform in ("dongchedi", "taobao"):
            options = {"statement": "内容无需标注"} if platform == "taobao" else {}
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "清空"):
                validate_task({"platform": platform, "title": "有效测试图文", "mode": "preview",
                               "content_html": "<p>正文</p>", "tags": ["标签"], "options": options}, {})


class NativeReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_jd_preview_blocks_publish_function_but_not_drafts_or_uploads(self):
        page = MagicMock()
        page.route = AsyncMock()
        self.assertTrue(await install_native_preview_request_guard(page, "jd"))
        pattern, callback = page.route.call_args.args
        for url, body, blocked in (
            ("https://api.m.jd.com/?functionId=articlePublishImageText", None, True),
            ("https://api.m.jd.com/articlePublishImageText", None, True),
            ("https://api.m.jd.com/api", "functionId=articlePublishImageText&body=%7B%7D", True),
            ("https://api.m.jd.com/api", '{"functionId":"articlePublishImageText"}', True),
            ("https://api.m.jd.com/?functionId=articleSaveImageTextDraft", None, False),
            ("https://api.m.jd.com/api", "functionId=imageUpload", False),
        ):
            with self.subTest(url=url, body=body):
                self.assertIsNotNone(pattern.search(url))
                route = MagicMock()
                route.request.url, route.request.post_data = url, body
                route.abort, route.continue_ = AsyncMock(), AsyncMock()
                await callback(route)
                if blocked:
                    route.abort.assert_awaited_once_with("blockedbyclient")
                    route.continue_.assert_not_awaited()
                else:
                    route.continue_.assert_awaited_once()
                    route.abort.assert_not_awaited()
        self.assertIsNone(pattern.search("https://api.m.jd.com.example.com/api"))

    async def test_note_receipts_and_wechat_preview_url_are_not_publication(self):
        self.assertEqual(receipt_status("图文发表成功"), "发表成功")
        self.assertEqual(receipt_status("笔记发布成功，等待审核"), "发布成功")
        self.assertIsNone(receipt_status("发表成功后请查看内容管理"))
        page = MagicMock(url="https://mp.weixin.qq.com/s/Abc123456789?tempkey=preview")
        page.locator.return_value.inner_text = AsyncMock(return_value="测试图文 正文")
        page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
        self.assertEqual((await read_result_evidence(page, "wechat", "测试图文"))["status"], "unknown")

    async def test_each_public_article_url_requires_matching_title(self):
        """新平台公共链接必须同时出现原稿标题；仅跳转地址不能算已发表。"""
        urls = {"douyin": "https://www.douyin.com/article/123456",
                "bilibili": "https://www.bilibili.com/opus/123456",
                "weibo": "https://weibo.com/ttarticle/p/show?id=230940123456",
                "qiehao": "https://new.qq.com/rain/a/20261001A12345",
                "wechat": "https://mp.weixin.qq.com/s/Abc123_-",
                "xiaohongshu": "https://www.xiaohongshu.com/explore/Abc123",
                "kuaishou": "https://www.kuaishou.com/short-video/Abc123"}
        for platform, url in urls.items():
            page = MagicMock(url=url)
            page.locator.return_value.inner_text = AsyncMock(return_value="多平台文章测试 正文")
            page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
            result = await read_result_evidence(page, platform, "多平台文章测试")
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["platform_url"], url)
            result = await read_result_evidence(page, platform, "另一篇文章")
            self.assertEqual(result["status"], "unknown")

    async def test_wechat_preview_blocks_writes_but_allows_reads(self):
        page = MagicMock()
        page.route = AsyncMock()
        self.assertTrue(await install_native_preview_request_guard(page, "wechat"))
        pattern, callback = page.route.call_args.args
        for action in ("masssend", "masssendmsg", "freepublish", "appmsgpublish", "operate_appmsg"):
            self.assertIsNotNone(pattern.search(f"https://mp.weixin.qq.com/cgi-bin/{action}?action=send"))
        self.assertIsNone(pattern.search("https://mp.weixin.qq.com/cgi-bin/filetransfer?action=upload"))
        for method in ("POST", "PUT", "DELETE", "GET"):
            route = MagicMock()
            route.request.method = method
            route.abort = AsyncMock()
            route.continue_ = AsyncMock()
            await callback(route)
            if method == "GET":
                route.continue_.assert_awaited_once()
                route.abort.assert_not_awaited()
            else:
                route.abort.assert_awaited_once_with("blockedbyclient")
                route.continue_.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
