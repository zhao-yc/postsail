import asyncio
from pathlib import Path

from conf import BASE_DIR
from uploader.toutiao_uploader.main import toutiao_setup

if __name__ == '__main__':
    account_file = Path(BASE_DIR / "cookies" / "toutiao_uploader" / "account.json")
    account_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_result = asyncio.run(toutiao_setup(str(account_file), handle=True))
    print(f'toutiao cookie setup: {cookie_result}, path={account_file}')
