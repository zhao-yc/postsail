# -*- coding: utf-8 -*-
"""
百家号图文文章发布示例

使用方法：
    python examples/upload_article_to_baijiahao.py

功能：
    - 发布图文文章到百家号
    - 支持标题、正文、标签
    - 支持封面图片（可选）
    - 支持立即发布或定时发布
"""

import asyncio
from pathlib import Path
from datetime import datetime, timedelta

from uploader.baijiahao_uploader.main import baijiahao_setup, BaiJiaHaoArticle


async def main():
    # Cookie 文件路径（需要先通过 get_baijiahao_cookie.py 获取）
    account_file = Path("cookiesFile/baijiahao_account.json")

    # 确保 cookie 有效
    if not await baijiahao_setup(account_file, handle=True):
        print("❌ Cookie 验证失败，请先运行 get_baijiahao_cookie.py 获取 cookie")
        return

    # 文章内容
    title = "如何高效管理时间：5个实用技巧"

    body = """
在快节奏的现代生活中，时间管理变得越来越重要。以下是5个实用的时间管理技巧，帮助你提高工作效率。

1. **制定清晰的目标**
明确你想要达成的目标，将大目标分解为小任务，这样更容易执行和跟踪进度。

2. **使用番茄工作法**
将工作时间分为25分钟的专注时段，中间休息5分钟。这种方法可以帮助你保持专注，避免疲劳。

3. **优先处理重要任务**
使用艾森豪威尔矩阵，将任务按照重要性和紧急性分类，优先处理重要且紧急的任务。

4. **避免多任务处理**
研究表明，多任务处理会降低工作效率。专注于一件事，完成后再开始下一件。

5. **定期回顾和调整**
每周花时间回顾你的进度，调整计划，确保你朝着正确的方向前进。

掌握这些时间管理技巧，你会发现工作效率显著提升，生活也会更加从容有序。
"""

    # 文章标签
    tags = ["时间管理", "工作效率", "生活技巧", "个人成长", "自我提升"]

    # 封面图片路径（百家号图文必填）
    cover_path = "videoFile/your_cover.jpg"  # 例如: "videoFile/cover.jpg"

    # 发布时间设置
    # 0 表示立即发布
    # datetime 对象表示定时发布
    publish_date = 0  # 立即发布
    # publish_date = datetime.now() + timedelta(hours=2)  # 2小时后发布

    # 是否仅预览不发布（测试时建议设置为 True）
    dry_run = True  # 设置为 True 时只预览不发布，方便测试

    print(f"📝 开始发布百家号图文文章...")
    print(f"标题：{title}")
    print(f"正文长度：{len(body)} 字符")
    print(f"标签：{tags}")
    print(f"封面：{cover_path or '无'}")
    print(f"发布模式：{'仅预览' if dry_run else ('立即发布' if publish_date == 0 else f'定时发布({publish_date})')}")
    print("-" * 60)

    # 创建发布实例
    app = BaiJiaHaoArticle(
        title=title,
        body=body,
        tags=tags,
        publish_date=publish_date,
        account_file=account_file,
        dry_run=dry_run,
        cover_path=cover_path,
    )

    try:
        # 执行发布
        await app.main()
        print("\n✅ 发布流程完成！")
        if dry_run:
            print("💡 这是预览模式，文章未实际发布")
            print("💡 如需实际发布，请将 dry_run 设置为 False")
    except Exception as e:
        print(f"\n❌ 发布失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
