"""账号类型兼容表；文章、视频和运营能力分别判定。"""
from utils.articles.platforms import PLATFORMS

ACCOUNT_PLATFORMS = {
    1: "xiaohongshu", 2: "tencent", 3: "douyin", 4: "kuaishou", 5: "baijiahao",
    6: "bilibili", 7: "toutiao", 8: "sohu", 9: "zhihu", 10: "weibo", 11: "qiehao",
    12: "yidian", 13: "dayu", 14: "netease", 15: "acfun", 16: "kuaichuan",
    17: "xueqiu", 18: "jingdong", 19: "douban", 20: "csdn", 21: "jianshu",
    22: "chejiahao", 23: "yiche", 24: "dongchedi",
}
ARTICLE_ACCOUNT_TYPES = frozenset(rules["account_type"] for rules in PLATFORMS.values())
ARTICLE_ONLY_ACCOUNT_TYPES = frozenset({8, 9, 10, 11, *range(12, 25)})
ACCOUNT_UNAVAILABLE_REASONS = {}

ACCOUNT_COOKIE_DOMAINS = {
    1: ("xiaohongshu.com",), 2: ("channels.weixin.qq.com",), 3: ("douyin.com",),
    4: ("kuaishou.com",), 5: ("baidu.com",), 6: ("bilibili.com",), 7: ("toutiao.com",),
    8: ("sohu.com",), 9: ("zhihu.com",), 10: ("weibo.com",), 11: ("qq.com",),
    12: ("yidianzixun.com",), 13: ("dayu.com",), 14: ("163.com",),
    15: ("acfun.cn",), 16: ("360kuai.com",), 17: ("xueqiu.com",),
    18: ("jd.com",), 19: ("douban.com",), 20: ("csdn.net",), 21: ("jianshu.com",),
    22: ("autohome.com.cn",),
    23: ("yiche.com",), 24: ("dcdapp.com",),
}


def resolve_account_type(value):
    """允许历史数字类型或明确的平台名称，视频号永远保留类型 2。"""
    if isinstance(value, bool):
        raise ValueError("账号平台无效")
    text = str(value).strip().lower()
    aliases = {"bilibili": 6, "b站": 6, "b站专栏": 6, "视频号": 2, "企鹅号": 11, "微博": 10}
    aliases.update({rules["label"].lower(): rules["account_type"] for rules in PLATFORMS.values()})
    if text in aliases:
        return aliases[text]
    if text in ACCOUNT_PLATFORMS.values():
        return next(kind for kind, platform in ACCOUNT_PLATFORMS.items() if platform == text)
    try:
        kind = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("账号平台无效") from exc
    if kind not in ACCOUNT_PLATFORMS:
        raise ValueError("账号平台无效")
    return kind


def validate_imported_cookie(account_type, payload):
    """校验导入格式与目标域名；真正登录状态仍须通过平台页面确认。"""
    from utils.articles.session import normalize_article_storage_state
    platform = ACCOUNT_PLATFORMS[account_type]
    state = normalize_article_storage_state(platform, payload)
    if not any(cookie["value"] and any(cookie["domain"].lstrip(".").lower() == domain or cookie["domain"].lstrip(".").lower().endswith("." + domain)
               for domain in ACCOUNT_COOKIE_DOMAINS[account_type]) for cookie in state["cookies"]):
        raise ValueError("Cookie 文件不含目标平台的有效域名凭据")
    return state


def validate_bilibili_cookie_replacement(destination, payload):
    """保护已有视频凭据；标准文章会话必须新建独立账号，不能覆盖 biliup 文件。"""
    import json
    from pathlib import Path
    destination = Path(destination)
    if not destination.is_file():
        return
    try:
        existing = json.loads(destination.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError("B站原凭据无法读取，请使用 biliup 更新或新建独立文章会话账号") from exc
    if not isinstance(existing, dict):
        return
    is_biliup = isinstance(existing.get("cookie_info"), dict) or "token_info" in existing
    if is_biliup and not isinstance(payload.get("cookie_info"), dict):
        raise ValueError("该B站账号保存了 biliup 视频凭据，禁止用标准浏览器会话覆盖；请新建独立文章会话账号，或使用 biliup 更新凭据")
    if existing.get("token_info") and not payload.get("token_info"):
        raise ValueError("上传的B站 biliup 文件缺少 token_info，禁止删除已有视频凭据；请导入完整 biliup 文件或新建独立文章会话账号")
