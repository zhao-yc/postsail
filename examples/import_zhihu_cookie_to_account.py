"""把 cookies/zhihu_uploader/account.json 导入账号管理（type=9）。

若 cookie 缺少登录凭证 z_c0，会自动打开浏览器让你重新登录。

用法：
  .\\.venv\\Scripts\\python.exe examples/import_zhihu_cookie_to_account.py
  .\\.venv\\Scripts\\python.exe examples/import_zhihu_cookie_to_account.py --name 我的知乎
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from conf import BASE_DIR
from myUtils.auth import check_cookie
from uploader.zhihu_uploader.main import zhihu_cookie_gen


def _has_z_c0(cookie_path: Path) -> bool:
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(c.get("name") == "z_c0" for c in data.get("cookies", []))


async def main(user_name: str) -> None:
    src = Path(BASE_DIR) / "cookies" / "zhihu_uploader" / "account.json"
    src.parent.mkdir(parents=True, exist_ok=True)

    if (not src.is_file()) or (not _has_z_c0(src)):
        print("当前 cookie 未登录或缺少 z_c0，即将打开浏览器，请完成知乎登录…")
        await zhihu_cookie_gen(str(src))

    if not _has_z_c0(src):
        raise SystemExit("登录后仍未检测到 z_c0，请重试")

    cookies_dir = Path(BASE_DIR) / "cookiesFile"
    cookies_dir.mkdir(exist_ok=True)
    file_name = f"{uuid.uuid1()}.json"
    dst = cookies_dir / file_name
    shutil.copy2(src, dst)

    ok = await check_cookie(9, file_name)
    status = 1 if ok else 0

    db = Path(BASE_DIR) / "db" / "database.db"
    with sqlite3.connect(db) as conn:
        cur = conn.cursor()
        # 若已有同名知乎账号则覆盖 cookie；否则新增
        cur.execute(
            "SELECT id, filePath FROM user_info WHERE type = 9 AND userName = ?",
            (user_name,),
        )
        row = cur.fetchone()
        if row:
            old_id, old_path = row
            cur.execute(
                "UPDATE user_info SET filePath = ?, status = ? WHERE id = ?",
                (file_name, status, old_id),
            )
            conn.commit()
            old_file = cookies_dir / str(old_path)
            if old_file.is_file() and old_file.resolve() != dst.resolve():
                try:
                    old_file.unlink()
                except Exception:
                    pass
            print(f"已更新账号 id={old_id} type=9 name={user_name} status={status} file={file_name}")
        else:
            cur.execute(
                "INSERT INTO user_info (type, filePath, userName, status) VALUES (?, ?, ?, ?)",
                (9, file_name, user_name, status),
            )
            conn.commit()
            print(f"已新增账号 id={cur.lastrowid} type=9 name={user_name} status={status} file={file_name}")

    if not ok:
        print("提示：即时校验未通过（可能是无头环境风控），但账号已入库；可在账号管理刷新后试用发布。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="知乎账号", help="账号显示名称")
    args = parser.parse_args()
    asyncio.run(main(args.name))
