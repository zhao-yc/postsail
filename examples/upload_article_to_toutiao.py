"""今日头条图文文章发布示例（支持 dry_run）。

用法：
1. 先登录拿到 cookie，放到 cookies/toutiao_uploader/account.json
   或 cookiesFile 下已有 type=7 账号文件
2. 修改下面 title / body / account_file
3. python examples/upload_article_to_toutiao.py
"""

import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.toutiao_uploader.main import TouTiaoArticle, toutiao_setup


if __name__ == "__main__":
    account_file = Path(BASE_DIR) / "cookies" / "toutiao_uploader" / "account.json"
    # 也可用 cookiesFile 下已保存的 json：
    # account_file = Path(BASE_DIR) / "cookiesFile" / "your-uuid.json"

    title = "测试图文标题"
    body = (
        "这是一篇用于联调的测试正文。\n\n"
        "第二段：换行应能保留。\n"
        "第三段：确认 dry_run 时不会点击发布。"
    )
    tags = ["测试", "自动发布"]
    dry_run = True  # 先预览，确认无误后再改 False

    cookie_ok = asyncio.run(toutiao_setup(account_file, handle=True))
    if not cookie_ok:
        raise SystemExit("今日头条 cookie 未就绪")

    # 可选封面（单图，JPEG/PNG，最大 20MB）：
    # cover_path = Path(BASE_DIR) / "videoFile" / "your_cover.jpg"
    cover_path = None

    # 可选作品声明（单选），与创作者后台文案一致：
    # 取材网络 / 引用站内 / 个人观点，仅供参考 / 引用AI /
    # 虚构演绎，故事经历 / 投资观点，仅供参考 / 健康医疗分享，仅供参考
    # 也可传字符串：work_statements = "个人观点，仅供参考"
    work_statements = "个人观点，仅供参考"

    app = TouTiaoArticle(
        title=title,
        body=body,
        tags=tags,
        publish_date=0,
        account_file=account_file,
        dry_run=dry_run,
        cover_path=cover_path,
        work_statements=work_statements,
    )
    if dry_run:
        app.headless = False
    asyncio.run(app.main(), debug=False)
