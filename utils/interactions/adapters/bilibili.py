"""B站评论及私信：按现有 cookie 登录，用原项目接口文档核对字段。"""
from __future__ import annotations

import json
import time
import uuid

from .base import InteractionAdapterError, business_code, decode_cursor, encode_cursor, load_cookies, request_json, require_kind, timestamp, validate_reply


class BilibiliAdapter:
    """只发送明确的评论回复或已有会话回复，不新建营销会话。"""

    platform = "bilibili"

    def _request(self, account, path, params=None, data=None, sending=False):
        """统一核对平台业务状态，错误消息不转发可能含凭据的原响应。"""
        host = "api.vc.bilibili.com" if path.startswith("/session_") or path.startswith("/svr_") or path.startswith("/web_im/") else "api.bilibili.com"
        if path == "/x/web/archives":
            host = "member.bilibili.com"
        payload = request_json("POST" if data is not None else "GET", "https://" + host + path,
                               cookies=load_cookies(account, host, ("SESSDATA",)), params=params, data=data,
                               headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}, sending=sending)
        code = business_code(payload.get("code"), "B站", sending)
        if code != 0:
            if code in (-101, -111):
                raise InteractionAdapterError("needs_login", "B站登录凭据已失效，请重新登录")
            raise InteractionAdapterError("platform_rejected", "B站拒绝该操作，请检查评论状态、账号权限或频率限制")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InteractionAdapterError("send_unknown" if sending else "invalid_response", "B站数据响应异常，请核对平台结果")
        return data

    def _identity(self, account):
        """以平台返回的当前登录 UID 识别消息方向，避免把本机账号 ID 当 UID。"""
        nav = self._request(account, "/x/web-interface/nav")
        if not nav.get("isLogin") or not nav.get("mid"):
            raise InteractionAdapterError("needs_login", "B站账号尚未登录")
        return str(nav["mid"])

    @staticmethod
    def _comment(row, item, own_id):
        """只保留回复定位需要的 ID，不保存整个原始接口响应。"""
        member, content = row.get("member") or {}, row.get("content") or {}
        rid = str(row.get("rpid_str") or row.get("rpid") or "")
        if not rid:
            raise InteractionAdapterError("invalid_response", "B站评论缺少唯一标识")
        root = str(row.get("root_str") or row.get("root") or "0")
        parent = str(row.get("parent_str") or row.get("parent") or "0")
        return {"platformMessageId": rid, "kind": "comment", "threadId": root if root != "0" else rid,
                "parentId": parent if parent != "0" else None, "itemId": str(item["aid"]), "itemTitle": item.get("title", ""),
                "authorId": str(member.get("mid") or row.get("mid") or ""), "authorName": member.get("uname", ""),
                "authorAvatar": member.get("avatar", ""), "text": str(content.get("message") or ""),
                "createdAt": timestamp(row.get("ctime")), "direction": "outbound" if str(member.get("mid")) == own_id else "inbound",
                "raw": {"oid": str(item["aid"]), "root": root if root != "0" else rid, "replyCount": row.get("rcount", 0)}}

    @staticmethod
    def _private(row, peer_id, own_id):
        """撤回、系统和媒体消息不进入文本自动回复流程。"""
        if row.get("msg_status", 0) != 0 or row.get("msg_type") != 1:
            return None
        content = row.get("content")
        try:
            content = json.loads(content) if isinstance(content, str) else content
        except ValueError:
            return None
        if not isinstance(content, dict) or not row.get("msg_key"):
            return None
        sender = str(row.get("sender_uid") or "")
        return {"platformMessageId": str(row["msg_key"]), "kind": "private", "threadId": peer_id, "parentId": None,
                "itemId": None, "itemTitle": "", "authorId": sender, "authorName": "用户 " + sender,
                "authorAvatar": "", "text": str(content.get("content") or ""), "createdAt": timestamp(row.get("timestamp")),
                "direction": "outbound" if sender == own_id else "inbound", "raw": {"talkerId": peer_id, "seqno": str(row.get("msg_seqno") or "")}}

    def fetch(self, account, cursor=None, kind="comment", item_id=None, limit=50):
        """逐作品/逐会话翻页；账号范围同步会返回下一批作品游标。"""
        require_kind(kind, ("comment", "private"))
        state = decode_cursor(cursor)
        own_id = self._identity(account)
        size = max(1, min(int(limit), 50))
        if kind == "comment":
            if item_id:
                params = {"bvid": item_id} if str(item_id).startswith("BV") else {"aid": item_id}
                view = self._request(account, "/x/web-interface/view", params)
                if str((view.get("owner") or {}).get("mid")) != own_id:
                    raise InteractionAdapterError("invalid_target", "只能管理当前账号自己作品的评论")
                works, more_works = [view], False
            else:
                archives = self._request(account, "/x/web/archives", {"status": "pubed", "pn": int(state.get("workPage", 1)), "ps": 1})
                if not isinstance(archives.get("arc_audits"), list):
                    raise InteractionAdapterError("invalid_response", "B站作品列表格式发生变化")
                works = [row.get("Archive") or row.get("archive") or row for row in archives["arc_audits"]]
                more_works = int(state.get("workPage", 1)) < int((archives.get("page") or {}).get("count", 0))
            result, next_state = [], None
            for item in works:
                page = int(state.get("page", 1))
                data = self._request(account, "/x/v2/reply", {"oid": item["aid"], "type": 1, "pn": page, "ps": min(size, 20), "sort": 0, "nohot": 1})
                if "replies" not in data:
                    raise InteractionAdapterError("invalid_response", "B站评论列表格式发生变化")
                rows = data.get("replies") or []
                # 列表内的子回复只是预览，不能把预览当成完整评论树。
                # 主楼和每个主楼的完整子回复分别翻页，确保 limit 不被展开树突破。
                child_index = int(state.get("childIndex", -1))
                child_more = False
                if child_index >= 0:
                    if child_index >= len(rows):
                        raise InteractionAdapterError("invalid_cursor", "B站评论列表发生变化，请重新同步")
                    root_id = rows[child_index].get("rpid_str") or rows[child_index].get("rpid")
                    child_page = int(state.get("childPage", 1))
                    children = self._request(account, "/x/v2/reply/reply", {"oid": item["aid"], "type": 1,
                        "root": root_id, "pn": child_page, "ps": min(size, 20)})
                    if "replies" not in children:
                        raise InteractionAdapterError("invalid_response", "B站子回复格式发生变化")
                    result.extend(self._comment(row, item, own_id) for row in children.get("replies") or [])
                    child_info = children.get("page") or {}
                    child_more = child_page * int(child_info.get("size", min(size, 20))) < int(child_info.get("count", 0))
                    if child_more:
                        next_state = {**state, "childIndex": child_index, "childPage": child_page + 1}
                else:
                    result.extend(self._comment(row, item, own_id) for row in rows)
                info = data.get("page") or {}
                if not child_more:
                    following_child = next((index for index in range(child_index + 1, len(rows)) if int(rows[index].get("rcount") or 0) > 0), None)
                    if following_child is not None:
                        next_state = {**state, "childIndex": following_child, "childPage": 1}
                    elif page * int(info.get("size", min(size, 20))) < int(info.get("count", 0)):
                        next_state = {"workPage": int(state.get("workPage", 1)), "page": page + 1}
                    elif more_works:
                        next_state = {"workPage": int(state.get("workPage", 1)) + 1}
            return {"items": result, "cursor": encode_cursor(next_state) if next_state else None, "hasMore": bool(next_state)}
        if item_id or state.get("peerId"):
            peers = [{"talker_id": item_id or state["peerId"], "session_ts": state.get("sessionTs")}]
            more_sessions = bool(state.get("moreSessions")) and not item_id
        else:
            params = {"session_type": 4, "size": 1, "group_fold": 0, "unfollow_fold": 0, "mobi_app": "web"}
            if state.get("endTs"):
                params["end_ts"] = state["endTs"]
            sessions = self._request(account, "/session_svr/v1/session_svr/get_sessions", params)
            if "session_list" not in sessions:
                raise InteractionAdapterError("invalid_response", "B站会话列表格式发生变化")
            peers = sessions.get("session_list") or []
            more_sessions = bool(sessions.get("has_more"))
        result, next_state = [], None
        for peer in peers:
            peer_id = str(peer["talker_id"])
            if peer.get("session_type", 1) != 1 or peer.get("system_msg_type", 0):
                if more_sessions:
                    next_state = {"endTs": peer["session_ts"]}
                continue
            params = {"talker_id": peer_id, "session_type": 1, "size": size, "mobi_app": "web"}
            if state.get("endSeq"):
                params["end_seqno"] = state["endSeq"]
            history = self._request(account, "/svr_sync/v1/svr_sync/fetch_session_msgs", params)
            if "messages" not in history:
                raise InteractionAdapterError("invalid_response", "B站私信历史格式发生变化")
            result.extend(item for row in history.get("messages") or [] if (item := self._private(row, peer_id, own_id)))
            if history.get("has_more"):
                next_state = {**state, "endSeq": history["min_seqno"], "peerId": peer_id,
                              "sessionTs": peer.get("session_ts"), "moreSessions": more_sessions}
            elif more_sessions:
                next_state = {"endTs": peer["session_ts"]}
        return {"items": result, "cursor": encode_cursor(next_state) if next_state else None, "hasMore": bool(next_state)}

    def send_reply(self, account, message, text, reply_key):
        """平台未提供幂等键时依赖服务层发送日志；本方法绝不重试 POST。"""
        text = validate_reply(message, text, reply_key)
        cookies = load_cookies(account, "api.bilibili.com", ("SESSDATA", "bili_jct"))
        raw = message.get("raw") or {}
        if message["kind"] == "comment":
            if not str(message.get("itemId") or "").isdigit() or not str(message["platformMessageId"]).isdigit():
                raise InteractionAdapterError("invalid_target", "B站评论目标标识无效")
            data = self._request(account, "/x/v2/reply/add", data={"type": 1, "oid": message["itemId"],
                "root": raw.get("root") or message["platformMessageId"], "parent": message["platformMessageId"],
                "message": text, "plat": 1, "csrf": cookies["bili_jct"]}, sending=True)
            rid = data.get("rpid_str") or data.get("rpid")
        elif message["kind"] == "private":
            peer = str(message.get("threadId") or "")
            if not peer.isdigit() or not raw.get("talkerId") or str(raw["talkerId"]) != peer:
                raise InteractionAdapterError("invalid_target", "B站私信会话标识无效")
            own_id = self._identity(account)
            data = self._request(account, "/web_im/v1/web_im/send_msg", data={"msg[sender_uid]": own_id,
                "msg[receiver_id]": peer, "msg[receiver_type]": 1, "msg[msg_type]": 1,
                "msg[dev_id]": str(uuid.uuid4()).upper(), "msg[timestamp]": int(time.time()),
                "msg[content]": json.dumps({"content": text}, ensure_ascii=False),
                "csrf": cookies["bili_jct"], "csrf_token": cookies["bili_jct"], "mobi_app": "web"}, sending=True)
            rid = data.get("msg_key")
        else:
            raise InteractionAdapterError("unsupported", "B站关注事件回复尚未接入")
        if not rid:
            raise InteractionAdapterError("send_unknown", "B站已接受请求，但没有返回回复 ID，请到平台核对")
        return {"platformReplyId": str(rid), "text": text, "confirmed": True}
