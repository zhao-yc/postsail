# tests/test_zhihu_article.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from uploader.zhihu_uploader.main import ZhiHuArticle


class TestZhiHuArticle(unittest.TestCase):
    def test_rejects_empty_title(self):
        with TemporaryDirectory() as td:
            account = Path(td) / "a.json"
            account.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                ZhiHuArticle(title="  ", body="正文", tags=[], publish_date=0, account_file=account)

    def test_rejects_empty_body(self):
        with TemporaryDirectory() as td:
            account = Path(td) / "a.json"
            account.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                ZhiHuArticle(title="有效标题", body="  ", tags=[], publish_date=0, account_file=account)

    def test_accepts_title_body_and_optional_cover(self):
        with TemporaryDirectory() as td:
            account = Path(td) / "a.json"
            account.write_text("{}", encoding="utf-8")
            cover = Path(td) / "c.jpg"
            cover.write_bytes(b"fake")
            app = ZhiHuArticle(
                title="知乎测试标题",
                body="第一段\n\n第二段",
                tags=["测试"],
                publish_date=0,
                account_file=account,
                dry_run=True,
                cover_path=str(cover),
                creation_statement="虚构创作",
            )
            self.assertEqual(app.title, "知乎测试标题")
            self.assertTrue(app.dry_run)
            self.assertTrue(str(app.cover_path).endswith("c.jpg"))
            self.assertEqual(app.creation_statement, "虚构创作")

    def test_creation_statement_defaults_to_none(self):
        with TemporaryDirectory() as td:
            account = Path(td) / "a.json"
            account.write_text("{}", encoding="utf-8")
            app = ZhiHuArticle(
                title="标题",
                body="正文",
                tags=[],
                publish_date=0,
                account_file=account,
            )
            self.assertEqual(app.creation_statement, "无声明")

    def test_title_truncated_to_100(self):
        with TemporaryDirectory() as td:
            account = Path(td) / "a.json"
            account.write_text("{}", encoding="utf-8")
            long_title = "啊" * 120
            app = ZhiHuArticle(
                title=long_title,
                body="正文",
                tags=[],
                publish_date=0,
                account_file=account,
            )
            self.assertEqual(len(app.title), 100)


if __name__ == "__main__":
    unittest.main()