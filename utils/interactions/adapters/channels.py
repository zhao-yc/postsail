"""视频号创作者助手互动接口；路径与参数取自 wx_video_sdk 原作者源码。"""
from __future__ import annotations

import hashlib
import time
import uuid

from .base import InteractionAdapterError, business_code, decode_cursor, encode_cursor, load_cookies, request_json, require_kind, timestamp, validate_reply

BASE = "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin"


class ChannelsAdapter:
    """复用网页登录态；当前未经真实视频号账号端到端验证。"""

    platform = "tencent"

    def _request(self, account, path, data=None, auth=None, sending=False):
        """保持 TLS 验证和域名固定，不沿用参考源码中关闭证书验证的做法。"""
        payload = {"timestamp": str(int(time.time() * 1000)), "_log_finder_uin": "", "_log_finder_id": (auth or {}).get("finderUsername", ""),
                   "rawKeyBuff": None, "pluginSessionId": None, "scene": 7, "reqScene": 7, **(data or {})}
        response = request_json("POST", BASE + path, json=payload,
                                cookies=load_cookies(account, "channels.weixin.qq.com"),
                                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://channels.weixin.qq.com/platform",
                                         "X-Wechat-Uin": str((auth or {}).get("uin") or "0000000000")}, sending=sending)
        if business_code(response.get("errCode"), "视频号", sending) != 0:
            raise InteractionAdapterError("platform_rejected", "视频号拒绝请求，请检查登录态、互动权限或平台验证")
        body = response.get("data")
        if body is None and sending:
            # 参考 SDK 以 errCode=0 作为业务接受回执，有些发送接口 data 为 null。
            return {}
        if not isinstance(body, dict):
            raise InteractionAdapterError("send_unknown" if sending else "invalid_response", "视频号数据格式异常，请到平台核对结果")
        return body

    def _auth(self, account, private=False):
        """用只读认证接口获取当前视频号 ID，私信专用 cookie 始终只留内存。"""
        profile = self._request(account, "/auth/auth_data")
        finder = profile.get("finderUser") or {}
        if not finder.get("finderUsername"):
            raise InteractionAdapterError("needs_login", "视频号登录态缺少身份信息，请重新登录")
        upload = self._request(account, "/helper/helper_upload_params")
        auth = {"finderUsername": str(finder["finderUsername"]), "nickname": str(finder.get("nickname") or ""), "uin": str(upload.get("uin") or "")}
        if private:
            auth["privateCookie"] = self._request(account, "/private-msg/get-login-cookie", auth=auth).get("cookie")
            if not auth["privateCookie"]:
                raise InteractionAdapterError("needs_login", "视频号私信权限不可用，请在创作者助手核对私信功能")
        return auth

    @staticmethod
    def _comment(row, item_id, own_id, root_id=None, title=""):
        """保留评论树关系及回复接口必需字段。"""
        cid = str(row.get("commentId") or "")
        if not cid:
            raise InteractionAdapterError("invalid_response", "视频号评论缺少唯一标识")
        author = str(row.get("commentUsername") or row.get("username") or "")
        comment = {key: row[key] for key in ("commentId", "commentContent", "commentNickname", "commentCreatetime", "commentUsername", "commentHeadUrl", "replyCommentId", "rootCommentId") if key in row}
        return {"platformMessageId": cid, "kind": "comment", "threadId": str(root_id or cid), "parentId": str(row.get("replyCommentId") or root_id or "") or None,
                "itemId": str(item_id), "itemTitle": title, "authorId": author, "authorName": str(row.get("commentNickname") or ""),
                "authorAvatar": str(row.get("commentHeadUrl") or ""), "text": str(row.get("commentContent") or ""),
                "createdAt": timestamp(row.get("commentCreatetime")), "direction": "outbound" if author and author == own_id else "inbound",
                "raw": {"comment": comment, "rootCommentId": str(root_id or row.get("rootCommentId") or cid)}}

    @staticmethod
    def _private(row, own_id):
        """平台未给出消息 ID 时，用会话、发送者、时间和内容生成稳定本地标识。"""
        peer, session, text = str(row.get("fromUsername") or ""), str(row.get("sessionId") or ""), str(row.get("rawContent") or "")
        if not peer or not session or not text:
            return None
        mid = row.get("srvMsgId") or row.get("msgId") or row.get("cliMsgId")
        if not mid:
            mid = "local:" + hashlib.sha256((session + "\0" + peer + "\0" + str(row.get("ts")) + "\0" + text).encode()).hexdigest()
        receiver = str(row.get("toUsername") or "")
        if own_id not in (peer, receiver):
            raise InteractionAdapterError("invalid_target", "视频号私信不属于当前账号，已停止同步")
        other = receiver if peer == own_id else peer
        return {"platformMessageId": str(mid), "kind": "private", "threadId": session, "parentId": None, "itemId": None, "itemTitle": "",
                "authorId": peer, "authorName": str(row.get("nickname") or row.get("fromNickname") or peer), "authorAvatar": str(row.get("headImgUrl") or ""),
                "text": text, "createdAt": timestamp(row.get("ts")), "direction": "outbound" if peer == own_id else "inbound",
                "raw": {"sessionId": session, "peerId": other, "ownerId": own_id}}

    @staticmethod
    def _slice_snapshot(items, state, size, next_page):
        """展开评论树或私信快照后仍遵守 limit；快照改变时停止续页，避免漏项。"""
        offset = max(0, int(state.get("offset", 0)))
        fingerprint = hashlib.sha256("\0".join(item["platformMessageId"] for item in items).encode()).hexdigest()
        if offset and state.get("snapshot") and state["snapshot"] != fingerprint:
            raise InteractionAdapterError("invalid_cursor", "视频号互动列表已变化，请重新同步")
        if offset + size < len(items):
            next_page = {**state, "offset": offset + size, "snapshot": fingerprint}
        return {"items": items[offset:offset + size], "cursor": encode_cursor(next_page) if next_page else None, "hasMore": bool(next_page)}

    def fetch(self, account, cursor=None, kind="comment", item_id=None, limit=50):
        """逐作品采集评论；私信按平台返回的历史快照分页，不写已读状态。"""
        require_kind(kind, ("comment", "private"))
        state, size = decode_cursor(cursor), max(1, min(int(limit), 50))
        auth = self._auth(account, private=kind == "private")
        if kind == "private":
            history = self._request(account, "/private-msg/get-history-msg", {"cookie": auth["privateCookie"]}, auth=auth)
            if not isinstance(history.get("msg"), list):
                raise InteractionAdapterError("invalid_response", "视频号私信历史格式发生变化")
            rows = [item for row in history["msg"] if (item := self._private(row, auth["finderUsername"]))]
            if item_id:
                rows = [row for row in rows if row["threadId"] == str(item_id)]
            return self._slice_snapshot(rows, state, size, None)
        if item_id:
            works, more_works = [{"exportId": item_id}], False
        else:
            page = max(1, int(state.get("workPage", 1)))
            data = self._request(account, "/post/post_list", {"pageSize": 1, "currentPage": page, "onlyUnread": False,
                "userpageType": 3, "needAllCommentCount": True, "forMcn": False}, auth=auth)
            if not isinstance(data.get("list"), list):
                raise InteractionAdapterError("invalid_response", "视频号作品列表格式发生变化")
            works = data["list"]
            more_works = page < int(data.get("totalCount") or data.get("total") or len(works))
        items, next_state = [], None
        for work in works:
            export = str(work.get("exportId") or "")
            if not export:
                raise InteractionAdapterError("invalid_response", "视频号作品缺少 exportId")
            data = self._request(account, "/comment/comment_list", {"lastBuff": str(state.get("lastBuff") or ""),
                "exportId": export, "commentSelection": False, "forMcn": False}, auth=auth)
            if not isinstance(data.get("comment"), list):
                raise InteractionAdapterError("invalid_response", "视频号评论列表格式发生变化")
            for row in data["comment"]:
                items.append(self._comment(row, export, auth["finderUsername"], title=str(work.get("description") or "")))
                items.extend(self._comment(child, export, auth["finderUsername"], root_id=row["commentId"]) for child in row.get("levelTwoComment") or [])
            if data.get("lastBuff") and data.get("lastBuff") != state.get("lastBuff"):
                next_state = {"workPage": int(state.get("workPage", 1)), "lastBuff": data["lastBuff"]}
            elif more_works:
                next_state = {"workPage": int(state.get("workPage", 1)) + 1}
        return self._slice_snapshot(items, state, size, next_state)

    def send_reply(self, account, message, text, reply_key):
        """稳定 clientId 辅助平台识别重入；服务层日志仍负责跨进程幂等。"""
        text = validate_reply(message, text, reply_key)
        auth = self._auth(account, private=message["kind"] == "private")
        client_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"omnipost:{reply_key}"))
        raw = message.get("raw") or {}
        if message["kind"] == "comment":
            comment = raw.get("comment") or {}
            if str(comment.get("commentId")) != str(message["platformMessageId"]) or not message.get("itemId"):
                raise InteractionAdapterError("invalid_target", "视频号评论定位信息不完整，请重新同步")
            self._request(account, "/comment/create_comment", {"replyCommentId": message["platformMessageId"],
                "content": text, "clientId": client_id, "rootCommentId": raw.get("rootCommentId") or message["platformMessageId"],
                "comment": comment, "exportId": message["itemId"]}, auth=auth, sending=True)
        elif message["kind"] == "private":
            if str(raw.get("ownerId")) != auth["finderUsername"] or not raw.get("peerId") or str(raw.get("sessionId")) != str(message.get("threadId")):
                raise InteractionAdapterError("invalid_target", "视频号私信会话与当前账号不匹配，请重新同步")
            self._request(account, "/private-msg/send-private-msg", {"msgPack": {"sessionId": raw["sessionId"],
                "fromUsername": auth["finderUsername"], "toUsername": raw["peerId"], "msgType": 1,
                "textMsg": {"content": text}, "cliMsgId": client_id}}, auth=auth, sending=True)
        else:
            raise InteractionAdapterError("unsupported", "视频号关注事件尚未接入")
        return {"text": text, "confirmed": True}
