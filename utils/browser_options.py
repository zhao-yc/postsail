def get_browser_options(headless: bool, executable_path: str) -> dict:
    """统一登录与 Cookie 校验的浏览器配置，优先使用已配置的 Chrome。"""
    options = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            "--disable-infobars",
            "--start-maximized",
        ],
    }
    if executable_path:
        options["executable_path"] = executable_path
    else:
        # 未配置路径时沿用登录流程的系统 Chrome，避免依赖额外下载的 Chromium。
        options["channel"] = "chrome"
    return options
