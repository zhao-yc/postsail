import importlib
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from uploader.douyin_uploader.main import (
    DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
    DOUYIN_PUBLISH_STRATEGY_SCHEDULED,
    DouYinBaseUploader,
)


def _load_post_video():
    return importlib.import_module("myUtils.postVideo")


class TestDouyinScheduleWiring(unittest.TestCase):
    def test_post_video_douyin_enable_timer_passes_scheduled_strategy(self):
        postVideo = _load_post_video()
        captured = {}

        class FakeDouYinVideo:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def douyin_upload_video(self):
                return None

        with patch.object(postVideo, "DouYinVideo", FakeDouYinVideo), patch.object(
            postVideo, "asyncio"
        ) as mock_asyncio, patch.object(
            postVideo,
            "generate_schedule_time_next_day",
            return_value=[datetime.now() + timedelta(hours=3)],
        ):
            mock_asyncio.run = lambda coro, debug=False: None
            postVideo.post_video_DouYin(
                title="t",
                files=["a.mp4"],
                tags=["tag"],
                account_file=["cookie.json"],
                enableTimer=True,
                videos_per_day=1,
                daily_times=["10:00"],
                start_days=0,
                dry_run=True,
            )

        self.assertEqual(captured.get("publish_strategy"), DOUYIN_PUBLISH_STRATEGY_SCHEDULED)
        self.assertNotEqual(captured.get("publish_date"), 0)

    def test_post_video_douyin_immediate_keeps_immediate_strategy(self):
        postVideo = _load_post_video()
        captured = {}

        class FakeDouYinVideo:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def douyin_upload_video(self):
                return None

        with patch.object(postVideo, "DouYinVideo", FakeDouYinVideo), patch.object(
            postVideo, "asyncio"
        ) as mock_asyncio:
            mock_asyncio.run = lambda coro, debug=False: None
            postVideo.post_video_DouYin(
                title="t",
                files=["a.mp4"],
                tags=["tag"],
                account_file=["cookie.json"],
                enableTimer=False,
                dry_run=True,
            )

        self.assertEqual(captured.get("publish_strategy"), DOUYIN_PUBLISH_STRATEGY_IMMEDIATE)


class TestDouyinScheduleAutoInfer(unittest.IsolatedAsyncioTestCase):
    async def test_datetime_forces_scheduled_even_if_strategy_immediate(self):
        uploader = DouYinBaseUploader(
            publish_date=datetime.now() + timedelta(hours=3),
            account_file="cookie.json",
            publish_strategy=DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        )
        with patch("uploader.douyin_uploader.main.os.path.exists", return_value=True), patch(
            "uploader.douyin_uploader.main.cookie_auth",
            new=AsyncMock(return_value=True),
        ):
            await uploader.validate_base_args()
        self.assertEqual(uploader.publish_strategy, DOUYIN_PUBLISH_STRATEGY_SCHEDULED)
        self.assertIsInstance(uploader.publish_date, datetime)


class TestSetScheduleTimeDouyin(unittest.IsolatedAsyncioTestCase):
    async def test_raises_when_schedule_option_missing(self):
        page = MagicMock()
        empty = MagicMock()
        empty.count = AsyncMock(return_value=0)
        empty.first = empty
        empty.last = empty
        empty.filter = MagicMock(return_value=empty)
        empty.scroll_into_view_if_needed = AsyncMock()
        page.locator = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        uploader = DouYinBaseUploader(
            publish_date=datetime.now() + timedelta(hours=3),
            account_file="cookie.json",
            publish_strategy=DOUYIN_PUBLISH_STRATEGY_SCHEDULED,
        )
        with self.assertRaises(RuntimeError):
            await uploader.set_schedule_time_douyin(page, datetime.now() + timedelta(hours=3))


if __name__ == "__main__":
    unittest.main()
