"""八平台公共约定、图片归属和明确回执的回归测试。"""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from utils.articles.adapter import create_adapter, validate_task
from utils.articles.browser import is_uploaded_image, read_result_evidence
from utils.articles.cli import ARTICLE_PLATFORMS
from utils.articles.model import ArticleError, capabilities, validate_options
from utils.articles.platforms import PLATFORMS


class PlatformContractTests(unittest.TestCase):
    def test_eight_platforms_have_distinct_account_types_and_adapters(self):
        """API、CLI、执行器覆盖一致，企鹅号绝不能复用视频号账号。"""
        expected = {"douyin": 3, "bilibili": 6, "baijiahao": 5, "toutiao": 7,
                    "weibo": 10, "zhihu": 9, "qiehao": 11, "sohu": 8}
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
        for platform in ("douyin", "weibo"):
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
                 "weibo": "wx1.sinaimg.cn", "qiehao": "inews.gtimg.com"}
        for platform, host in hosts.items():
            self.assertTrue(is_uploaded_image({"src": f"https://{host}/a.jpg", "ready": True}, platform))
            for source in (f"https://{host}.example.com/a.jpg", f"blob:https://{host}/local",
                           "https://www.yinzon.com/未上传.jpg", f"https://{host}/pending.jpg"):
                ready = not source.endswith("pending.jpg")
                self.assertFalse(is_uploaded_image({"src": source, "ready": ready}, platform))


class NativeReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_public_article_url_requires_matching_title(self):
        """新平台公共链接必须同时出现原稿标题；仅跳转地址不能算已发表。"""
        urls = {"douyin": "https://www.douyin.com/article/123456",
                "bilibili": "https://www.bilibili.com/opus/123456",
                "weibo": "https://weibo.com/ttarticle/p/show?id=230940123456",
                "qiehao": "https://new.qq.com/rain/a/20261001A12345"}
        for platform, url in urls.items():
            page = MagicMock(url=url)
            page.locator.return_value.inner_text = AsyncMock(return_value="多平台文章测试 正文")
            page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
            result = await read_result_evidence(page, platform, "多平台文章测试")
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["platform_url"], url)
            result = await read_result_evidence(page, platform, "另一篇文章")
            self.assertEqual(result["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
