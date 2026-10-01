"""粉丝采集字段边界：不读作品作者，不把缩写或无效值当精确账号数据。"""
import unittest

from utils.analytics.collectors.profile import extract_profile_followers, parse_label_count


class AnalyticsProfileTests(unittest.TestCase):
    def test_extract_explicit_profile_and_zero_followers(self):
        self.assertEqual(extract_profile_followers({"data": {"user_info": {"fans_count": 123}}}),
                         (123, "data.user_info.fans_count"))
        self.assertEqual(extract_profile_followers({"data": {"uid": "123", "follower_count": 0}}),
                         (0, "data.follower_count"))

    def test_does_not_extract_authors_and_missing_profile_values(self):
        self.assertEqual(extract_profile_followers({"data": {"items": [{"author": {"uid": "其他账号", "follower_count": 100}}]}}), (None, None))
        self.assertEqual(extract_profile_followers({"data": {"follower_count": 100}}), (None, None))
        self.assertEqual(extract_profile_followers({"profile": {"fans_count": -1}}), (None, None))
        self.assertEqual(extract_profile_followers({"profile": {"fans_count": "1.2万"}}), (None, None))

    def test_exact_dom_label_count_in_both_orders(self):
        self.assertEqual(parse_label_count("粉丝数\n12,345", "粉丝数"), 12345)
        self.assertEqual(parse_label_count("0\n粉丝", "粉丝"), 0)
        self.assertEqual(parse_label_count("粉丝：99", "粉丝"), 99)
        for text in ("粉丝\n1.2万", "粉丝增长\n12", "粉丝\n10\n关注\n99", "粉丝\n99%"):
            self.assertIsNone(parse_label_count(text, "粉丝"))


if __name__ == "__main__":
    unittest.main()
