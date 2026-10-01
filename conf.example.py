from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior
ARTICLE_BROWSER_HEADLESS = True  # 文章发布是否隐藏浏览器；验证码出现时任务会提示人工处理
ARTICLE_RENDER_FONT = "Noto Sans CJK SC, PingFang SC, Microsoft YaHei, sans-serif"  # 表格与代码截图字体
ARTICLE_PREVIEW_SECONDS = 0  # 可选预览保留浏览器的秒数；0 为截图后关闭
ARTICLE_WORKER_ENABLED = True  # 后端内置串行文章执行器；测试时可关闭
ARTICLE_ASSET_MAX_BYTES = 20 * 1024 * 1024  # 原稿图片大小上限；发布时另按平台限制校验
INTERACTION_WORKER_ENABLED = True  # 允许消息运行器；实际后台采集和自动回复需在界面显式启用
ANALYTICS_PUSH_WORKER_ENABLED = True  # 允许报表调度器；新安装推送设置默认关闭
FEISHU_WEBHOOK_URL = ""  # 可选飞书群机器人地址；为空时通过数据推送设置配置
FEISHU_SECRET = ""  # 可选机器人签名密钥
WECOM_WEBHOOK_URL = ""  # 可选企业微信群机器人地址
DINGTALK_WEBHOOK_URL = ""  # DingTalk group robot webhook; empty disables push
DINGTALK_SECRET = ""  # optional robot secret for signed webhooks
DINGTALK_PUSH_COVERS = True  # False = do not embed cover images in DingTalk messages
DINGTALK_REHOST_COVERS = True  # rehost covers to a temp public JPEG URL so DingTalk can display them
