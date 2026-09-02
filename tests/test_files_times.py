# tests/test_files_times.py
import unittest
from datetime import datetime

from utils.files_times import _parse_daily_time, generate_schedule_time_next_day


class TestFilesTimes(unittest.TestCase):
    def test_parse_daily_time_int_and_hhmm(self):
        self.assertEqual(_parse_daily_time(10), (10, 0))
        self.assertEqual(_parse_daily_time("10:00"), (10, 0))
        self.assertEqual(_parse_daily_time("10:30"), (10, 30))

    def test_generate_accepts_frontend_hhmm(self):
        schedule = generate_schedule_time_next_day(
            total_videos=1,
            videos_per_day=1,
            daily_times=["10:00"],
            start_days=0,
        )
        self.assertEqual(len(schedule), 1)
        self.assertIsInstance(schedule[0], datetime)
        self.assertEqual(schedule[0].hour, 10)
        self.assertEqual(schedule[0].minute, 0)

    def test_generate_compat_positional_start_days(self):
        # Historical callers: 4th positional was start_days, not timestamps
        schedule = generate_schedule_time_next_day(1, 1, ["11:00"], 0)
        self.assertEqual(len(schedule), 1)
        self.assertIsInstance(schedule[0], datetime)
        self.assertEqual(schedule[0].hour, 11)
