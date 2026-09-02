from datetime import timedelta
from datetime import datetime
from pathlib import Path

from conf import BASE_DIR


def get_absolute_path(relative_path: str, base_dir: str = None) -> str:
    # Convert the relative path to an absolute path
    absolute_path = Path(BASE_DIR) / base_dir / relative_path
    return str(absolute_path)


def get_title_and_hashtags(filename):
    """
  获取视频标题和 hashtag

  Args:
    filename: 视频文件名

  Returns:
    视频标题和 hashtag 列表
  """

    # 获取视频标题和 hashtag txt 文件名
    txt_filename = filename.replace(".mp4", ".txt")

    # 读取 txt 文件
    with open(txt_filename, "r", encoding="utf-8") as f:
        content = f.read()

    # 获取标题和 hashtag
    splite_str = content.strip().split("\n")
    title = splite_str[0]
    hashtags = splite_str[1].replace("#", "").split(" ")

    return title, hashtags


def _parse_daily_time(item) -> tuple[int, int]:
    """Parse daily time as (hour, minute). Accepts int hour or 'HH:MM' string."""
    if isinstance(item, bool):
        raise ValueError(f"非法发布时间: {item}")
    if isinstance(item, (int, float)):
        hour = int(item)
        if hour < 0 or hour > 23:
            raise ValueError(f"非法发布时间小时: {item}")
        return hour, 0

    text = str(item).strip()
    if not text:
        raise ValueError("发布时间不能为空")
    if ":" in text:
        hour_str, minute_str, *rest = text.split(":")
        if rest:
            raise ValueError(f"非法发布时间: {item}")
        hour = int(hour_str)
        minute = int(minute_str)
    else:
        hour = int(text)
        minute = 0
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"非法发布时间: {item}")
    return hour, minute


def generate_schedule_time_next_day(total_videos, videos_per_day=1, daily_times=None, timestamps=False, start_days=0):
    """
    Generate a schedule for video uploads, starting from the next day.

    Args:
    - total_videos: Total number of videos to be uploaded.
    - videos_per_day: Number of videos to be uploaded each day.
    - daily_times: Optional list of specific times of the day to publish the videos.
      Supports integer hours (e.g. 10) or 'HH:MM' strings (e.g. '10:00') from the web UI.
    - timestamps: Boolean to decide whether to return timestamps or datetime objects.
    - start_days: Start from after start_days.

    Returns:
    - A list of scheduling times for the videos, either as timestamps or datetime objects.
    """
    # Compat: many callers historically passed start_days as the 4th positional arg,
    # which overwrote `timestamps`. Treat non-bool 4th values as start_days.
    if not isinstance(timestamps, bool):
        start_days = int(timestamps)
        timestamps = False

    videos_per_day = int(videos_per_day)
    start_days = int(start_days or 0)
    total_videos = int(total_videos)

    if videos_per_day <= 0:
        raise ValueError("videos_per_day should be a positive integer")

    if daily_times is None:
        # Default times to publish videos if not provided
        daily_times = [6, 11, 14, 16, 22]

    parsed_times = [_parse_daily_time(item) for item in daily_times]

    if videos_per_day > len(parsed_times):
        raise ValueError("videos_per_day should not exceed the length of daily_times")

    # Generate timestamps
    schedule = []
    current_time = datetime.now()

    for video in range(total_videos):
        day = video // videos_per_day + start_days + 1  # +1 to start from the next day
        daily_video_index = video % videos_per_day

        # Calculate the time for the current video
        hour, minute = parsed_times[daily_video_index]
        time_offset = timedelta(
            days=day,
            hours=hour - current_time.hour,
            minutes=minute - current_time.minute,
            seconds=-current_time.second,
            microseconds=-current_time.microsecond,
        )
        timestamp = current_time + time_offset

        schedule.append(timestamp)

    if timestamps:
        schedule = [int(time.timestamp()) for time in schedule]
    return schedule
