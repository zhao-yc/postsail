"""抖音官方私信回调与回复；普通创作者 cookie 不具备开放平台授权。"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from .base import InteractionAdapterError, account_value, business_code, request_json, timestamp, validate_reply


def load_open_config(account):
    """账号旁的可选配置独立保存，不能进入公开仓库或消息 raw 字段。"""
    cookie_path = account_value(account, "cookie_path")
    if not cookie_path:
        raise InteractionAdapterError("needs_login", "该账号尚未配置抖音开放平台私信授权")
    path = Path(cookie_path).with_suffix(".interactions.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InteractionAdapterError("needs_login", "请为该账号配置抖音开放平台授权文件，详情见互动平台接入文档") from exc
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in ("open_id", "client_key")):
        raise InteractionAdapterError("needs_login", "抖音开放平台授权文件缺少账号或应用标识")
    if any(key in payload and not isinstance(payload[key], str) for key in ("client_secret", "business_token")):
        raise InteractionAdapterError("needs_login", "抖音开放平台授权字段格式错误，请按接入文档配置")
    if "scopes" in payload and (not isinstance(payload["scopes"], list) or any(not isinstance(scope, str) for scope in payload["scopes"])):
        raise InteractionAdapterError("needs_login", "抖音授权 scopes 必须是权限名称列表")
    return payload


def parse_webhook(account, body: bytes, signature: str) -> dict:
    """先校验原始字节签名和账号归属，再解析消息；不接受未签名入站。"""
    config = load_open_config(account)
    secret = str(config.get("client_secret") or "")
    if not secret:
        raise InteractionAdapterError("needs_login", "抖音回调验证需要配置应用密钥")
    expected = hashlib.sha1(secret.encode() + body).hexdigest()
    if not isinstance(signature, str) or not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise InteractionAdapterError("permission_denied", "抖音回调签名无效")
    try:
        payload = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise InteractionAdapterError("invalid_request", "抖音回调不是有效 JSON") from exc
    if not isinstance(payload, dict) or payload.get("client_key") != config["client_key"]:
        raise InteractionAdapterError("permission_denied", "抖音回调应用标识与账号配置不匹配")
    event = payload.get("event")
    if event not in ("verify_webhook", "im_receive_msg", "im_send_msg", "im_enter_direct_msg"):
        # 新关注不是进入私信，不能把其他已签名事件伪装成欢迎事件。
        return {"items": []}
    content = payload.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError as exc:
            raise InteractionAdapterError("invalid_request", "抖音回调内容不是有效 JSON") from exc
    if not isinstance(content, dict):
        raise InteractionAdapterError("invalid_request", "抖音回调缺少内容对象")
    if event == "verify_webhook":
        if "challenge" not in content:
            raise InteractionAdapterError("invalid_request", "抖音回调验证缺少 challenge")
        return {"challenge": content["challenge"]}
    sender, receiver, owner = str(payload.get("from_user_id") or ""), str(payload.get("to_user_id") or ""), str(config["open_id"])
    if owner not in (sender, receiver):
        raise InteractionAdapterError("permission_denied", "抖音回调消息不属于该账号")
    welcome = event == "im_enter_direct_msg"
    if welcome and receiver != owner:
        raise InteractionAdapterError("permission_denied", "抖音进私信事件的接收者不属于该账号")
    if content.get("conversation_type") != 1 or (not welcome and content.get("message_type") != "text"):
        # 官方文档有群聊和媒体事件，当前只接收可安全回复的单人文本私信。
        return {"items": []}
    mid, thread = str(content.get("server_message_id") or ""), str(content.get("conversation_short_id") or "")
    if not mid or not thread or (not welcome and not isinstance(content.get("text"), str)):
        raise InteractionAdapterError("invalid_request", "抖音文本私信缺少消息或会话标识")
    info = next((row for row in content.get("user_infos") or [] if isinstance(row, dict) and row.get("open_id") == sender), {})
    outbound = sender == owner
    item = {"platformMessageId": mid, "kind": "welcome" if welcome else "private", "threadId": thread, "parentId": None, "itemId": None, "itemTitle": "",
            "authorId": sender, "authorName": str(info.get("nick_name") or sender), "authorAvatar": str(info.get("avatar") or ""),
            "text": "用户进入私信会话" if welcome else content["text"], "createdAt": timestamp(content.get("create_time")), "direction": "outbound" if outbound else "inbound",
            "raw": {"provider": "douyin_openapi", "ownerId": owner, "peerId": receiver if outbound else sender, "conversationId": thread, "event": payload["event"]}}
    return {"items": [item]}


def send_private_reply(account, message, text, reply_key):
    """只使用官方回复场景，不主动向陌生人触达；超时永远不重试。"""
    text = validate_reply(message, text, reply_key)
    config, raw = load_open_config(account), message.get("raw") or {}
    welcome = message.get("kind") == "welcome"
    if message.get("kind") not in ("private", "welcome") or raw.get("provider") != "douyin_openapi" or raw.get("ownerId") != config["open_id"]:
        raise InteractionAdapterError("invalid_target", "私信不属于当前开放平台账号")
    if welcome and raw.get("event") != "im_enter_direct_msg":
        raise InteractionAdapterError("invalid_target", "欢迎语缺少官方进入私信事件，不能通过关注或历史私信推断")
    if not config.get("business_token"):
        raise InteractionAdapterError("needs_login", "请配置具备 im.direct_message 权限的 business_token")
    if config.get("scopes") is not None and "im.direct_message" not in config["scopes"]:
        raise InteractionAdapterError("permission_denied", "抖音授权缺少 im.direct_message 权限，请重新授权")
    try:
        created = datetime.fromisoformat(str(message.get("createdAt") or "").replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - created).total_seconds()
    except (TypeError, ValueError) as exc:
        raise InteractionAdapterError("invalid_target", "无法确认私信时间，不能调用官方限时回复接口") from exc
    window = 30 if welcome else 86400
    if not 0 <= age <= window or not raw.get("peerId") or str(raw.get("conversationId")) != str(message.get("threadId")):
        raise InteractionAdapterError("invalid_target", "抖音欢迎语已超出 30 秒窗口或会话无效" if welcome else "抖音私信已超出 24 小时回复窗口或会话信息无效")
    payload = request_json("POST", "https://open.douyin.com/im/send/msg/", params={"open_id": config["open_id"]},
        headers={"access-token": config["business_token"], "Content-Type": "application/json"},
        json={"scene": "im_enter_direct_msg" if welcome else "im_reply_msg", "content": {"msg_type": 1, "text": {"text": text}},
              "msg_id": message["platformMessageId"], "conversation_id": message["threadId"], "to_user_id": raw["peerId"]}, sending=True)
    data, extra = payload.get("data") or {}, payload.get("extra") or {}
    codes = [block.get("error_code") for block in (data, extra) if isinstance(block, dict) and "error_code" in block]
    if not codes:
        raise InteractionAdapterError("send_unknown", "抖音没有返回明确的消息回执，请到平台核对")
    if any(business_code(code, "抖音", sending=True) != 0 for code in codes) or payload.get("all_send_success") is False:
        raise InteractionAdapterError("platform_rejected", "抖音拒绝回复私信，请检查授权、回复窗口和发送频率")
    reply_id = payload.get("msg_id") or data.get("msg_id")
    if not isinstance(reply_id, (str, int)) or isinstance(reply_id, bool) or not str(reply_id).strip():
        raise InteractionAdapterError("send_unknown", "抖音没有返回明确的消息回执，请到平台核对")
    return {"platformReplyId": str(reply_id), "text": text, "confirmed": True}
