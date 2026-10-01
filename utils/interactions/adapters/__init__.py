"""真实平台互动适配器注册及诚实的能力说明。"""
from __future__ import annotations

from copy import deepcopy

from .base import InteractionAdapterError, account_value
from .bilibili import BilibiliAdapter
from .channels import ChannelsAdapter
from .douyin import DouyinAdapter
from .douyin_openapi import load_open_config
from .xiaohongshu import XiaohongshuAdapter

ADAPTERS = {"douyin": DouyinAdapter, "tencent": ChannelsAdapter,
            "xiaohongshu": XiaohongshuAdapter, "bilibili": BilibiliAdapter}

CAPABILITIES = [
    {"platform": "douyin", "label": "抖音", "kinds": ["comment", "private", "welcome"], "fetchableKinds": ["comment"],
     "operations": {"comment": {"fetch": "available", "reply": "unverified", "transport": "browser"},
                    "private": {"fetch": "needs_login", "reply": "unverified", "transport": "webhook"},
                    "welcome": {"fetch": "needs_login", "reply": "unverified", "transport": "webhook"}},
     "status": "unverified", "reason": "已验证网页登录态主评论及子回复读取；真实回复尚未发送验收。私信和进入会话欢迎语需官方 im.direct_message 授权及回调配置。",
     "requires": ["账号管理中的抖音登录态", "私信另需开放平台授权及可访问的 HTTPS 回调"]},
    {"platform": "tencent", "label": "视频号", "kinds": ["comment", "private"], "fetchableKinds": ["comment", "private"],
     "operations": {"comment": {"fetch": "unverified", "reply": "unverified", "transport": "http"},
                    "private": {"fetch": "unverified", "reply": "unverified", "transport": "http"}},
     "status": "unverified", "reason": "按原作者 SDK 实现创作者助手的评论和私信接口，尚缺真实视频号账号验证；仅管理自己的作品和会话。",
     "requires": ["账号管理中的视频号登录态及平台互动权限"]},
    {"platform": "xiaohongshu", "label": "小红书私信版", "kinds": ["private"], "fetchableKinds": ["private"],
     "operations": {"private": {"fetch": "unverified", "reply": "unverified", "transport": "browser"}},
     "status": "unverified", "reason": "接入普通账号新版 /chat 网页私信，未接入评论；需该账号已开通网页私信，尚缺真实账号验证。",
     "requires": ["账号管理中的小红书网页登录态", "平台账号已开通网页私信"]},
    {"platform": "bilibili", "label": "B站", "kinds": ["comment", "private"], "fetchableKinds": ["comment", "private"],
     "operations": {"comment": {"fetch": "unverified", "reply": "unverified", "transport": "http"},
                    "private": {"fetch": "unverified", "reply": "unverified", "transport": "http"}},
     "status": "unverified", "reason": "已实现自己作品评论、已有私信会话及回复；基于接口原项目文档，尚缺真实账号发送和读取验收。",
     "requires": ["账号管理中的 B站登录态，发送还需 bili_jct"]},
]
for _platform, _label in (("kuaishou", "快手"), ("baijiahao", "百家号"), ("toutiao", "今日头条"), ("sohu", "搜狐"), ("zhihu", "知乎")):
    CAPABILITIES.append({"platform": _platform, "label": _label, "kinds": [], "fetchableKinds": [], "operations": {},
                         "status": "unsupported", "reason": "尚未接入互动采集和回复；支持发布或数据统计不代表支持互动管理。", "requires": []})


def get_adapter(platform: str):
    """未接入平台直接报错，绝不返回成功的空适配器。"""
    factory = ADAPTERS.get(str(platform).strip().lower())
    if not factory:
        raise InteractionAdapterError("unsupported", "该平台尚未接入互动管理，请使用平台官方客户端")
    return factory()


def list_capabilities(account=None) -> list[dict]:
    """能力列表不访问外网；账号专用状态只检查凭据存在性，不声称有效。"""
    items = deepcopy(CAPABILITIES)
    if account is None:
        return items
    from pathlib import Path
    platform = account_value(account, "platform")
    cookie_path = account_value(account, "cookie_path")
    for item in items:
        if item["platform"] != platform or item["status"] == "unsupported":
            continue
        if not cookie_path or not Path(cookie_path).is_file():
            item["status"] = "needs_login"
            item["reason"] = "请先在账号管理中登录；" + item["reason"]
            for operation in item["operations"].values():
                operation["fetch"] = operation["reply"] = "needs_login"
        if platform == "douyin":
            try:
                config = load_open_config(account)
                if not config.get("client_secret") or not config.get("business_token"):
                    raise InteractionAdapterError("needs_login", "抖音私信及欢迎语需要完整的应用密钥和 business_token 授权")
                scopes = config.get("scopes")
                if scopes is not None and "im.direct_message" not in scopes:
                    raise InteractionAdapterError("needs_login", "配置的抖音授权缺少 im.direct_message 权限")
                state = "unverified"
            except InteractionAdapterError as exc:
                state = "needs_login"
                item["reason"] += " " + str(exc)
            for kind in ("private", "welcome"):
                item["operations"][kind]["fetch"] = item["operations"][kind]["reply"] = state
    return items


__all__ = ["get_adapter", "list_capabilities", "InteractionAdapterError"]
