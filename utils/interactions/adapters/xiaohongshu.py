"""小红书普通账号网页私信，沿用站点自身会话和真实输入框。"""
from __future__ import annotations

import json
from urllib.parse import quote, urlsplit

from .base import InteractionAdapterError, browser_page, business_code, decode_cursor, encode_cursor, require_kind, timestamp, validate_reply

CHAT_URL = "https://www.xiaohongshu.com/chat"
API = "https://edith.xiaohongshu.com"


class XiaohongshuAdapter:
    """不要求外部签名服务；只有网页已开通私信的账号可使用。"""

    platform = "xiaohongshu"

    def _get(self, page, path):
        """只向已知站点发正常只读请求，登录凭据仍由浏览器管理。"""
        response = page.evaluate("""async url => {
            const r = await fetch(url, {credentials: 'include', cache: 'no-store'});
            let body = null; try { body = await r.json(); } catch (_) {}
            return {status: r.status, body};
        }""", API + path)
        if response.get("status") in (401, 403):
            raise InteractionAdapterError("needs_login", "小红书网页登录态已失效或需要完成验证")
        payload = response.get("body")
        if response.get("status") != 200 or not isinstance(payload, dict):
            raise InteractionAdapterError("platform_error", "小红书网页私信接口不可用，请核对账号是否已开通网页私信")
        if payload.get("success") is not True and "code" not in payload:
            raise InteractionAdapterError("invalid_response", "小红书没有返回明确的读取回执")
        if payload.get("success") is False or ("code" in payload and business_code(payload["code"], "小红书") != 0):
            raise InteractionAdapterError("platform_rejected", "小红书拒绝读取私信，请检查账号权限和登录状态")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InteractionAdapterError("invalid_response", "小红书私信响应格式发生变化")
        return data

    @staticmethod
    def _text(content):
        """文字和图片卡片明确区分，不把未知对象转成可自动回复的文字。"""
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                return content
        if not isinstance(content, dict):
            return ""
        inner = content.get("content")
        if isinstance(inner, dict):
            return str(inner.get("text") or inner.get("content") or "")
        return str(inner or content.get("text") or "")

    @staticmethod
    def _chats(data):
        """字段缺失是接口变化，不能当成没有私信。"""
        rows = data.get("chats")
        if not isinstance(rows, list):
            raise InteractionAdapterError("invalid_response", "小红书会话列表格式发生变化")
        return rows

    def _history(self, page, chat, last_id, size):
        """保留用户与会话对应关系，ID 始终作为字符串存储。"""
        peer = str(chat.get("chat_user_id") or chat.get("peer_user_id") or "")
        owner = str(chat.get("user_id") or "")
        thread = str(chat.get("chat_id") or chat.get("conversation_id") or peer)
        if not peer or not owner or chat.get("group_chat") or chat.get("is_group_chat"):
            raise InteractionAdapterError("unsupported", "小红书当前只支持具有明确双方身份的单人私信")
        data = self._get(page, "/api/im/web/messages/history?chat_user_id=" + quote(peer, safe="") +
                         f"&last_id={max(0, int(last_id))}&start_id=0&limit={size}")
        rows = data.get("out_message_list") if "out_message_list" in data else data.get("message_list")
        if not isinstance(rows, list):
            raise InteractionAdapterError("invalid_response", "小红书消息历史格式发生变化")
        result, stores = [], []
        info = chat.get("info") or {}
        for row in rows:
            sender = str(row.get("sender_id") or row.get("sender_uid") or "")
            receiver = str(row.get("receiver_id") or row.get("receiver_uid") or "")
            if sender not in (peer, owner) or receiver not in (peer, owner):
                raise InteractionAdapterError("invalid_target", "小红书返回了其他会话消息，已停止同步")
            mid = row.get("id") or row.get("uuid") or row.get("store_id")
            text = self._text(row.get("content"))
            if row.get("store_id"):
                stores.append(int(row["store_id"]))
            if not mid or not text:
                continue
            result.append({"platformMessageId": str(mid), "kind": "private", "threadId": thread, "parentId": None,
                "itemId": None, "itemTitle": "", "authorId": sender, "authorName": str(info.get("nickname") or info.get("name") or peer) if sender == peer else "我",
                "authorAvatar": str(info.get("avatar") or info.get("image") or "") if sender == peer else "", "text": text,
                "createdAt": timestamp(row.get("created_at") or row.get("create_time")), "direction": "inbound" if sender == peer else "outbound",
                "raw": {"peerId": peer, "ownerId": owner, "storeId": str(row.get("store_id") or "")}})
        return result, min(stores) if stores else None, len(rows) >= size

    def fetch(self, account, cursor=None, kind="comment", item_id=None, limit=50):
        """每次读取一个真实会话，避免大量打开网页或漏掉分页消息。"""
        require_kind(kind, ("private",))
        state, size = decode_cursor(cursor), max(1, min(int(limit), 50))
        page_number, index = max(0, int(state.get("page", 0))), max(0, int(state.get("chatIndex", 0)))
        with browser_page(account, CHAT_URL) as page:
            chats = self._chats(self._get(page, f"/api/im/web/v3/chats?limit=100&complete=true&page={page_number}&source=pc"))
            if state.get("peerId"):
                matches = [(i, row) for i, row in enumerate(chats) if str(row.get("chat_user_id") or row.get("peer_user_id")) == str(state["peerId"])
                           and str(row.get("user_id")) == str(state.get("ownerId"))]
                if len(matches) != 1:
                    raise InteractionAdapterError("invalid_cursor", "小红书会话排序或账号身份已变化，请重新同步")
                index = matches[0][0]
            if item_id:
                chats = [row for row in chats if str(row.get("chat_id") or row.get("conversation_id") or row.get("chat_user_id")) == str(item_id)]
                index = 0
                if not chats:
                    raise InteractionAdapterError("invalid_target", "当前私信列表中找不到该会话，请重新同步")
            if index >= len(chats):
                return {"items": [], "cursor": None, "hasMore": False}
            chat = chats[index]
            if chat.get("group_chat") or chat.get("is_group_chat"):
                items, next_id, history_more = [], None, False
            else:
                items, next_id, history_more = self._history(page, chat, state.get("lastId", 0), size)
            next_state = None
            if history_more and next_id and next_id != state.get("lastId"):
                next_state = {"page": page_number, "chatIndex": index, "lastId": next_id,
                              "peerId": str(chat.get("chat_user_id") or chat.get("peer_user_id")), "ownerId": str(chat.get("user_id"))}
            elif not item_id and index + 1 < len(chats):
                next_state = {"page": page_number, "chatIndex": index + 1}
            elif not item_id and len(chats) == 100:
                next_state = {"page": page_number + 1, "chatIndex": 0}
            return {"items": items, "cursor": encode_cursor(next_state) if next_state else None, "hasMore": bool(next_state)}

    def send_reply(self, account, message, text, reply_key):
        """仅在已有会话输入框提交一次，以新增的平台消息 ID 确认结果。"""
        text = validate_reply(message, text, reply_key)
        require_kind(message["kind"], ("private",))
        raw = message.get("raw") or {}
        peer, owner = str(raw.get("peerId") or ""), str(raw.get("ownerId") or "")
        if not peer or not owner:
            raise InteractionAdapterError("invalid_target", "小红书会话身份缺失，请重新同步")
        with browser_page(account, CHAT_URL + "/" + quote(peer, safe="")) as page:
            matches = []
            for number in range(50):
                chats = self._chats(self._get(page, f"/api/im/web/v3/chats?limit=100&complete=true&page={number}&source=pc"))
                matches = [row for row in chats if str(row.get("chat_user_id") or row.get("peer_user_id")) == peer
                           and str(row.get("user_id")) == owner and str(row.get("chat_id") or row.get("conversation_id") or peer) == str(message["threadId"])]
                if matches or len(chats) < 100:
                    break
            if len(matches) != 1:
                raise InteractionAdapterError("invalid_target", "小红书会话不属于当前登录账号或已变更，请重新同步")
            before, next_id, more = self._history(page, matches[0], 0, 50)
            history, visited = before, set()
            for _ in range(50):
                if str(message["platformMessageId"]) in {row["platformMessageId"] for row in history}:
                    break
                if not more or not next_id or next_id in visited:
                    raise InteractionAdapterError("invalid_target", "目标消息未在会话历史中找到，请重新同步或到平台核对")
                visited.add(next_id)
                history, next_id, more = self._history(page, matches[0], next_id, 50)
            else:
                raise InteractionAdapterError("invalid_target", "目标消息超出单次历史查找范围，请到平台核对")
            editor = page.locator('.xhs-im-input-bar-editor[contenteditable="true"]')
            try:
                editor.wait_for(state="visible", timeout=10000)
                if editor.count() != 1:
                    raise InteractionAdapterError("invalid_target", "小红书页面存在多个私信输入框，无法精确定位")
                editor.fill(text)
            except InteractionAdapterError:
                raise
            except Exception as exc:
                raise InteractionAdapterError("not_sent", "无法找到小红书私信输入框，页面可能改版") from exc
            submitted = False
            try:
                # Enter 为已核对原作者源码的提交方式，没有任何后备二次点击。
                submitted = True
                editor.press("Enter")
                before_ids = {row["platformMessageId"] for row in before}
                for _ in range(6):
                    page.wait_for_timeout(1000)
                    history, _, _ = self._history(page, matches[0], 0, 50)
                    confirmed = [row for row in history if row["direction"] == "outbound" and row["text"] == text and row["platformMessageId"] not in before_ids]
                    if len(confirmed) == 1:
                        return {"platformReplyId": confirmed[0]["platformMessageId"], "text": text, "confirmed": True}
            except Exception as exc:
                if submitted:
                    raise InteractionAdapterError("send_unknown", "小红书私信已提交，结果待确认，请到平台核对") from exc
                raise
            raise InteractionAdapterError("send_unknown", "小红书私信已提交，但未确认新增消息，请到平台核对")
