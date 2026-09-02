"""搜狐号图文文章发布示例（支持 dry_run）。

用法：
1. 先登录拿到 cookie：
   python examples/get_sohu_cookie.py
   或使用 cookiesFile 下已有 type=8 账号文件
2. 修改下面 title / body / account_file
3. python examples/upload_article_to_sohu.py
"""

import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.sohu_uploader.main import SoHuArticle, sohu_setup


if __name__ == "__main__":
    account_file = Path(BASE_DIR) / "cookies" / "sohu_uploader" / "account.json"
    # 也可用 cookiesFile 下已保存的 json：
    # account_file = Path(BASE_DIR) / "cookiesFile" / "your-uuid.json"

    title = "测试搜狐号图文标题"
    body = (
        "这是一篇用于联调的测试正文。\n\n"
        "第二段：换行应能保留。\n"
        "第三段：确认 dry_run 时不会点击发布。"
    )
    tags = ["测试", "自动发布"]
    dry_run = True  # 先预览，确认无误后再改 False

    cookie_ok = asyncio.run(sohu_setup(account_file, handle=True))
    if not cookie_ok:
        raise SystemExit("搜狐号 cookie 未就绪")

    # 可选封面（可多张；jpg/jpeg/png/gif，单张最大 10MB）：
    # cover_paths = [
    #     Path(BASE_DIR) / "videoFile" / "cover1.jpg",
    #     Path(BASE_DIR) / "videoFile" / "cover2.png",
    # ]
    cover_paths = None

    # 信息来源（单选）：无特别声明 / 引用声明 / 包含AI创作内容 / 包含虚构创作
    info_source = "无特别声明"

    app = SoHuArticle(
        title=title,
        body=body,
        tags=tags,
        publish_date=0,
        account_file=account_file,
        dry_run=dry_run,
        cover_paths=cover_paths,
        info_source=info_source,
    )
    if dry_run:
        app.headless = False
    asyncio.run(app.main(), debug=False)
