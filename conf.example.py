from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior
DINGTALK_WEBHOOK_URL = ""  # DingTalk group robot webhook; empty disables push
DINGTALK_SECRET = ""  # optional robot secret for signed webhooks
DINGTALK_PUSH_COVERS = True  # False = do not embed cover images in DingTalk messages
DINGTALK_REHOST_COVERS = True  # rehost covers to a temp public JPEG URL so DingTalk can display them
