import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.toutiao_uploader.main import toutiao_setup, TouTiaoVideo
from utils.files_times import generate_schedule_time_next_day, get_title_and_hashtags


if __name__ == '__main__':
    filepath = Path(BASE_DIR) / "videos"
    account_file = Path(BASE_DIR / "cookies" / "toutiao_uploader" / "account.json")
    folder_path = Path(filepath)
    files = list(folder_path.glob("*.mp4"))
    file_num = len(files)
    publish_datetimes = generate_schedule_time_next_day(file_num, 1, daily_times=[16])
    cookie_setup = asyncio.run(toutiao_setup(account_file, handle=True))
    if not cookie_setup:
        raise SystemExit("今日头条 cookie 未就绪")
    for index, file in enumerate(files):
        title, tags = get_title_and_hashtags(str(file))
        print(f"视频文件名：{file}")
        print(f"标题：{title}")
        print(f"Hashtag：{tags}")
        app = TouTiaoVideo(title, file, tags, publish_datetimes[index], account_file)
        asyncio.run(app.main(), debug=False)
