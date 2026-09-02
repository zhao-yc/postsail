# tests/test_tencent_video_label.py
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from uploader.tencent_uploader.main import TencentVideo, format_str_for_short_title


class TestTencentVideoLabel(unittest.TestCase):
    def test_format_short_title_empty_returns_empty(self):
        self.assertEqual(format_str_for_short_title(""), "")
        self.assertEqual(format_str_for_short_title("   "), "")
        self.assertEqual(format_str_for_short_title(None), "")  # type: ignore[arg-type]

    def _build(self, td: str, **kwargs) -> TencentVideo:
        account = Path(td) / "a.json"
        account.write_text("{}", encoding="utf-8")
        video = Path(td) / "v.mp4"
        video.write_bytes(b"fake")
        params = dict(
            title="测试标题",
            file_path=str(video),
            tags=[],
            publish_date=0,
            account_file=str(account),
        )
        params.update(kwargs)
        return TencentVideo(**params)

    def test_ai_generated_defaults_false(self):
        with TemporaryDirectory() as td:
            app = self._build(td)
            self.assertFalse(app.ai_generated)

    def test_ai_generated_true_stored(self):
        with TemporaryDirectory() as td:
            app = self._build(td, ai_generated=True)
            self.assertTrue(app.ai_generated)

    def test_set_video_label_skips_when_false(self):
        with TemporaryDirectory() as td:
            app = self._build(td, ai_generated=False)
            page = MagicMock()
            result = asyncio.run(app.set_video_label(page))
            self.assertFalse(result)
            page.get_by_text.assert_not_called()
