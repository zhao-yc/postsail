"""知乎文章发布示例（支持 dry_run）。

用法：
1. python examples/get_zhihu_cookie.py
2. 修改 title / body / account_file
3. python examples/upload_article_to_zhihu.py
"""

import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.zhihu_uploader.main import ZhiHuArticle, zhihu_setup


if __name__ == "__main__":
    account_file = Path(BASE_DIR) / "cookies" / "zhihu_uploader" / "account.json"

    title = "测试知乎文章标题"
    body = (
        "这是一篇用于联调的测试正文。\n\n"
        "第二段：换行应能保留。\n"
        "第三段：确认 dry_run 时不会点击发布。"
    )
    dry_run = True

    cookie_ok = asyncio.run(zhihu_setup(account_file, handle=True))
    if not cookie_ok:
        raise SystemExit("知乎 cookie 未就绪")

    cover_path = None  # 可选：Path(BASE_DIR) / "videoFile" / "cover.jpg"
    # 创作声明：包含剧透 / 包含医疗建议 / 虚构创作 / 包含理财内容 /
    # 包含 AI 辅助创作 作者对内容负责 / 无声明
    creation_statement = "无声明"

    app = ZhiHuArticle(
        title=title,
        body=body,
        tags=["测试"],
        publish_date=0,
        account_file=account_file,
        dry_run=dry_run,
        cover_path=cover_path,
        creation_statement=creation_statement,
    )
    if dry_run:
        app.headless = False
    asyncio.run(app.main(), debug=False)
