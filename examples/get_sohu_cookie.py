"""搜狐号 cookie 登录示例。

用法：
  python examples/get_sohu_cookie.py

登录成功后 cookie 保存在 cookies/sohu_uploader/account.json
"""

import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.sohu_uploader.main import sohu_setup

if __name__ == "__main__":
    account_file = Path(BASE_DIR / "cookies" / "sohu_uploader" / "account.json")
    account_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_result = asyncio.run(sohu_setup(str(account_file), handle=True))
    print(f"sohu cookie setup: {cookie_result}, path={account_file}")
