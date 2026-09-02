# tests/test_dingtalk.py
import base64
import hashlib
import hmac
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

from myUtils.dingtalk import (
    DingTalkPushError,
    build_signed_webhook_url,
    format_content_stats_markdown,
    format_multi_account_stats_markdown,
    send_markdown,
    truncate_title,
)


class TruncateTitleTests(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(truncate_title("hello"), "hello")

    def test_long_truncated(self):
        s = "测" * 50
        out = truncate_title(s, max_len=40)
        self.assertEqual(len(out), 41)  # 40 chars + …
        self.assertTrue(out.endswith("…"))


class FormatMarkdownTests(unittest.TestCase):
    def test_format_includes_platform_account_and_metrics(self):
        items = [
            {
                "title": "第一条标题",
                "status": "已发布",
                "publishedAt": "2026-08-10 18:00:00",
                "coverUrl": "https://example.com/a.jpg",
                "playCount": 1234,
                "likeCount": 56,
                "commentCount": 7,
                "shareCount": 2,
                "collectCount": 9,
            },
            {
                "title": "二",
                "status": "",
                "publishedAt": "",
                "playCount": 1,
                "likeCount": 0,
                "commentCount": 0,
                "shareCount": 0,
                "collectCount": 0,
            },
        ]
        title, text = format_content_stats_markdown(
            platform_label="抖音",
            account_name="测试号",
            last_synced_at="2026-08-11 11:00:00",
            items=items,
        )
        self.assertEqual(title, "抖音 · 测试号 · 内容数据")
        self.assertIn("### 抖音 · 测试号 · 内容数据", text)
        self.assertIn("同步时间：2026-08-11 11:00:00", text)
        self.assertIn("1. **第一条标题**（已发布）", text)
        self.assertIn("![封面](https://example.com/a.jpg)", text)
        self.assertIn("浏览 1234 · 点赞 56 · 评论 7 · 分享 2 · 收藏 9", text)
        self.assertIn("2. **二**", text)
        self.assertNotIn("![封面]()\n2.", text)

    def test_format_includes_traffic_scalars_when_present(self):
        items = [
            {
                "title": "有流量",
                "status": "已发布",
                "publishedAt": "2026-08-14 12:00:00",
                "playCount": 10,
                "likeCount": 1,
                "commentCount": 0,
                "shareCount": 0,
                "collectCount": 0,
                "completionRate": 28.13,
                "avgPlayDurationSec": 8,
                "bounceRate2s": 22.2,
                "completionRate5s": 63.5,
            }
        ]
        _, text = format_content_stats_markdown(
            platform_label="抖音",
            account_name="测试号",
            last_synced_at="2026-08-14 12:00:00",
            items=items,
        )
        self.assertIn("完播率 28.13%", text)
        self.assertIn("平均时长 8秒", text)
        self.assertIn("2s跳出 22.2%", text)
        self.assertIn("5s完播 63.5%", text)

    def test_format_includes_sources_audience_boost_diagnose(self):
        items = [
            {
                "title": "完整字段",
                "status": "已发布 · 流量助推",
                "playCount": 100,
                "likeCount": 1,
                "commentCount": 0,
                "shareCount": 0,
                "collectCount": 0,
                "boostPlayCount": 233,
                "boostReason": "画质清晰度「优秀」超过80%作品",
                "contentDiagnose": [
                    {"dimension": "SCREEN", "score": 88},
                    {"dimension": "TITLE", "score": 38},
                ],
                "trafficSources": [
                    {"name": "发现页", "ratio": 40.5},
                    {"name": "关注页", "ratio": 20},
                ],
                "audienceGender": [{"name": "男", "ratio": 55}],
                "audienceAge": [{"name": "24-30", "ratio": 30}],
                "audienceRegion": [{"name": "广东", "ratio": 12}],
            }
        ]
        _, text = format_content_stats_markdown(
            platform_label="快手",
            account_name="测试号",
            last_synced_at="2026-08-18 12:00:00",
            items=items,
            include_covers=False,
        )
        self.assertIn("诊断：画质88 / 标题38", text)
        self.assertIn("助推：+233", text)
        self.assertIn("**来源**", text)
        self.assertIn("| 发现页 | 40.5% |", text)
        self.assertIn("**性别**", text)
        self.assertIn("| 男 | 55% |", text)
        self.assertIn("**年龄**", text)
        self.assertIn("**地域**", text)
        self.assertNotIn("![封面]", text)

    @patch("myUtils.dingtalk.rehost_cover_for_dingtalk", return_value="https://litter.catbox.moe/demo.jpg")
    def test_rehost_covers_uses_public_url(self, _mock_rehost):
        items = [
            {
                "title": "有封面",
                "status": "已发布",
                "coverUrl": "https://p26-sign.douyinpic.com/secret.webp",
                "playCount": 1,
                "likeCount": 0,
                "commentCount": 0,
                "shareCount": 0,
                "collectCount": 0,
            }
        ]
        _, text = format_content_stats_markdown(
            platform_label="抖音",
            account_name="测试号",
            last_synced_at="2026-08-11 11:00:00",
            items=items,
            rehost_covers=True,
        )
        self.assertIn("![封面](https://litter.catbox.moe/demo.jpg)", text)
        self.assertNotIn("douyinpic.com", text)

    @patch("myUtils.dingtalk.rehost_cover_for_dingtalk", return_value=None)
    def test_rehost_failure_skips_cover(self, _mock_rehost):
        items = [
            {
                "title": "有封面",
                "coverUrl": "https://p26-sign.douyinpic.com/secret.webp",
                "playCount": 1,
                "likeCount": 0,
                "commentCount": 0,
                "shareCount": 0,
                "collectCount": 0,
            }
        ]
        _, text = format_content_stats_markdown(
            platform_label="抖音",
            account_name="测试号",
            last_synced_at=None,
            items=items,
            rehost_covers=True,
        )
        self.assertNotIn("![封面]", text)
        self.assertIn("1. **有封面**", text)

    def test_multi_account_combined_message(self):
        title, text = format_multi_account_stats_markdown(
            sections=[
                {
                    "platform_label": "抖音",
                    "account_name": "号A",
                    "last_synced_at": "2026-08-11 11:00:00",
                    "items": [
                        {
                            "title": "作品A",
                            "playCount": 10,
                            "likeCount": 1,
                            "commentCount": 0,
                            "shareCount": 0,
                            "collectCount": 0,
                        }
                    ],
                },
                {
                    "platform_label": "小红书",
                    "account_name": "号B",
                    "last_synced_at": "2026-08-11 12:00:00",
                    "items": [
                        {
                            "title": "作品B",
                            "playCount": 20,
                            "likeCount": 2,
                            "commentCount": 0,
                            "shareCount": 0,
                            "collectCount": 0,
                        }
                    ],
                },
                {
                    "platform_label": "快手",
                    "account_name": "空号",
                    "items": [],
                },
            ]
        )
        self.assertEqual(title, "内容数据推送（2 个账号）")
        self.assertIn("### 抖音 · 号A · 内容数据", text)
        self.assertIn("### 小红书 · 号B · 内容数据", text)
        self.assertIn("---", text)
        self.assertNotIn("空号", text)

    def test_empty_items_raises(self):
        with self.assertRaises(DingTalkPushError):
            format_content_stats_markdown(
                platform_label="抖音",
                account_name="x",
                last_synced_at=None,
                items=[],
            )


class SignUrlTests(unittest.TestCase):
    def test_no_secret_returns_original(self):
        url = "https://oapi.dingtalk.com/robot/send?access_token=abc"
        self.assertEqual(build_signed_webhook_url(url, ""), url)
        self.assertEqual(build_signed_webhook_url(url, None), url)

    def test_with_secret_appends_timestamp_and_sign(self):
        url = "https://oapi.dingtalk.com/robot/send?access_token=abc"
        secret = "SECtest"
        with patch("myUtils.dingtalk.time.time", return_value=1600000000.123):
            signed = build_signed_webhook_url(url, secret)
        self.assertTrue(signed.startswith(url + "&timestamp="))
        parsed = urllib.parse.urlparse(signed)
        qs = urllib.parse.parse_qs(parsed.query)
        ts = qs["timestamp"][0]
        self.assertEqual(ts, "1600000000123")
        string_to_sign = f"{ts}\n{secret}"
        expected = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("ascii")
        self.assertEqual(qs["sign"][0], expected)


class SendMarkdownTests(unittest.TestCase):
    @patch("myUtils.dingtalk.requests.post")
    def test_send_ok(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"errcode": 0, "errmsg": "ok"},
            text='{"errcode":0}',
        )
        send_markdown(
            webhook_url="https://oapi.dingtalk.com/robot/send?access_token=abc",
            secret="",
            title="t",
            text="body",
        )
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://oapi.dingtalk.com/robot/send?access_token=abc")
        self.assertEqual(kwargs["json"]["msgtype"], "markdown")
        self.assertEqual(kwargs["json"]["markdown"]["title"], "t")
        self.assertEqual(kwargs["json"]["markdown"]["text"], "body")

    @patch("myUtils.dingtalk.requests.post")
    def test_send_dingtalk_errcode_raises(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"errcode": 310000, "errmsg": "sign not match"},
            text='{"errcode":310000}',
        )
        with self.assertRaises(DingTalkPushError) as ctx:
            send_markdown(
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=abc",
                secret="SEC",
                title="t",
                text="body",
            )
        self.assertIn("sign not match", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
