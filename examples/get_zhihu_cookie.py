"""知乎 cookie 登录示例。

用法：
  python examples/get_zhihu_cookie.py

登录成功后 cookie 保存在 cookies/zhihu_uploader/account.json
"""

import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.zhihu_uploader.main import zhihu_setup

if __name__ == "__main__":
    account_file = Path(BASE_DIR / "cookies" / "zhihu_uploader" / "account.json")
    account_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_result = asyncio.run(zhihu_setup(str(account_file), handle=True))
    print(f"zhihu cookie setup: {cookie_result}, path={account_file}")
