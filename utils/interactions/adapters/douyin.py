"""抖音新版创作者助手评论：原生请求采集，准确行内回复。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from .base import InteractionAdapterError, browser_page, business_code, decode_cursor, encode_cursor, require_kind, timestamp, validate_reply
from .douyin_openapi import parse_webhook, send_private_reply

MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
DETAIL_URL = "https://creator.douyin.com/creator-micro/work-management/work-detail/{item_id}?enter_from=content&tabKey=commentManagement"
WORK_PATH = "/janus/douyin/creator/pc/work_list"
COMMENT_PATH = "/aweme/v1/creator/comment/list/"
CHILD_PATH = "/aweme/v1/creator/comment/reply/list/"
ROW_SELECTOR = 'div[class^="comment-main-"]'


class DouyinAdapter:
    """评论复用账号网页登录态；私信使用单独授权的官方回调。"""

    platform = "douyin"
    parse_webhook = staticmethod(parse_webhook)

    @staticmethod
    def _check(payload):
        """平台业务状态必须明确成功，格式变化不得误认为空列表。"""
        if not isinstance(payload, dict) or "status_code" not in payload:
            raise InteractionAdapterError("invalid_response", "抖音创作者接口格式发生变化")
        if business_code(payload["status_code"], "抖音") != 0:
            raise InteractionAdapterError("platform_rejected", "抖音拒绝读取评论，请检查登录态、作品归属或安全验证")
        return payload

    @staticmethod
    def _capture(page, path, url, cursor=None):
        """先监听再导航，仅接收固定 creator 域名的指定只读接口。"""
        return DouyinAdapter._observe(page, path, lambda: page.goto(url, wait_until="domcontentloaded", timeout=30000), cursor)

    @staticmethod
    def _scroll(page):
        """滚动真实列表触发网页自身签名请求，不改写评论接口签名。"""
        page.evaluate("""() => {
            const rows = document.querySelectorAll('div[class^="comment-item-"]');
            let node = rows[rows.length-1];
            while (node) {
                if (node.scrollHeight > node.clientHeight && /auto|scroll/.test(getComputedStyle(node).overflowY)) {
                    node.scrollTop=node.scrollHeight; return;
                }
                node=node.parentElement;
            }
            window.scrollTo(0,document.body.scrollHeight);
        }""")

    @staticmethod
    def _observe(page, path, action, cursor=None, parent_id=None, more_action=None):
        """监听页面原生 GET，按请求游标和主楼 ID 绑定返回数据。"""
        captures = []
        def listener(response):
            parsed = urlsplit(response.url)
            if parsed.hostname == "creator.douyin.com" and parsed.path == path and response.request.method == "GET":
                try:
                    query = parse_qs(parsed.query)
                    if parent_id is None or query.get("comment_id", [""])[0] == str(parent_id):
                        captures.append({"url": response.url, "payload": response.json(), "requestCursor": query.get("cursor", ["0"])[0]})
                except Exception:
                    pass
        page.on("response", listener)
        try:
            action()
            for _ in range(30):
                page.wait_for_timeout(500)
                matches = [entry for entry in captures if cursor is None or str(entry["requestCursor"]) == str(cursor)]
                if matches:
                    # 等待初始化筛选状态稳定，防止读到页面先发出的默认查询。
                    page.wait_for_timeout(600)
                    return matches[-1]
                if captures and path == COMMENT_PATH:
                    DouyinAdapter._scroll(page)
                elif captures and more_action:
                    more_action()
            if page.get_by_text("扫码登录", exact=True).count():
                raise InteractionAdapterError("needs_login", "抖音网页登录态已失效，请重新登录")
            raise InteractionAdapterError("platform_error", "没有观察到抖音评论接口，请检查作品归属、页面状态或安全验证")
        finally:
            page.remove_listener("response", listener)

    @staticmethod
    def _find_row(page, target):
        """作者、完整文本、时间、图片数和层级共同唯一定位；表情使用 img alt。"""
        snapshots = page.locator(ROW_SELECTOR).evaluate_all("""nodes => nodes.map((node,index) => {
            const author=node.querySelector(':scope > [class^="username-"]');
            const date=node.querySelector(':scope > [class^="time-"]');
            const text=node.querySelector(':scope > [class^="text-"]')?.cloneNode(true);
            text?.querySelectorAll('[class^="reply-to-"]').forEach(n=>n.remove());
            text?.querySelectorAll('img').forEach(img=>img.replaceWith(document.createTextNode(img.alt||'')));
            const isReply=Array.from(node.parentElement?.classList||[]).some(c=>c.startsWith('reply-'));
            return {index,author:author?.innerText.trim()||'',date:date?.innerText.trim()||'',
                    text:text?.textContent.trim()||'',images:node.querySelector(':scope > [class^="images-"]')?.querySelectorAll('img').length||0,isReply};
        })""")
        raw = target.get("raw") or {}
        matches = [row for row in snapshots if row["author"] == target["authorName"] and raw["displayDate"] in row["date"]
                   and row["text"] == raw["sourceText"].strip() and row["images"] == raw["imageCount"]
                   and bool(row.get("isReply")) == bool(target.get("parentId"))]
        if len(matches) != 1:
            raise InteractionAdapterError("invalid_target", "无法唯一确定目标评论，未发送；请到平台处理或更新适配器")
        return page.locator(ROW_SELECTOR).nth(matches[0]["index"])

    def _children(self, page, root, item_id, cursor=0):
        """真实展开主楼回复，使用原生子评论分页接口，不把预览当完整列表。"""
        root_row = self._find_row(page, self._comment(root, item_id))
        def expand():
            button = root_row.locator('button[class^="load-reply-"]')
            if button.count() != 1 or "收起" in button.inner_text():
                raise InteractionAdapterError("invalid_cursor", "抖音子评论分页入口不可用，请重新同步")
            button.click()
        return self._observe(page, CHILD_PATH, expand, cursor, str(root["comment_id"]), expand)

    def _read_page(self, page, captured, changes=None):
        """仅复用网页已发出的真实 GET 地址，修改已确认的翻页字段。"""
        if not changes:
            return self._check(captured["payload"])
        parsed = urlsplit(captured["url"])
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update({key: str(value) for key, value in changes.items()})
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        result = page.evaluate("""async url => {
            const r = await fetch(url, {credentials:'include', cache:'no-store'});
            let body = null; try {body = await r.json()} catch (_) {}
            return {status:r.status, body};
        }""", url)
        if result.get("status") != 200:
            raise InteractionAdapterError("platform_error", "抖音评论翻页请求失败，请核对平台状态")
        return self._check(result.get("body"))

    @staticmethod
    def _comment(row, item_id, title="", root_id=None, comment_cursor=0, reply_cursor=0):
        """加密平台 ID 保留原样，只存回复和显示必需的字段。"""
        cid, info = str(row.get("comment_id") or ""), row.get("user_info") or {}
        if not cid:
            raise InteractionAdapterError("invalid_response", "抖音评论缺少唯一标识")
        source_text = str(row.get("text") or "")
        images = row.get("image_list") or []
        parent = str(row.get("reply_comment_id") or row.get("parent_comment_id") or root_id or "") or None
        date = timestamp(row.get("create_time"))
        display_date = datetime.fromisoformat(date).astimezone(timezone(timedelta(hours=8))).strftime("%m月%d日 %H:%M") if date else ""
        return {"platformMessageId": cid, "kind": "comment", "threadId": str(root_id or row.get("root_comment_id") or parent or cid),
                "parentId": parent, "itemId": str(item_id), "itemTitle": title, "authorId": str(info.get("user_id") or ""),
                "authorName": str(info.get("screen_name") or ""), "authorAvatar": str(info.get("avatar_url") or ""),
                "text": source_text or ("[图片评论]" if images else "[非文本评论]"), "createdAt": date,
                "direction": "outbound" if row.get("is_author") else "inbound",
                "raw": {"provider": "douyin_creator", "sourceText": source_text, "displayDate": display_date, "imageCount": len(images),
                        "replyCount": row.get("reply_count", "0"), "isAuthor": bool(row.get("is_author")),
                        "rootCommentId": str(root_id or cid), "commentCursor": str(comment_cursor), "replyCursor": str(reply_cursor)}}

    def fetch(self, account, cursor=None, kind="comment", item_id=None, limit=50):
        """逐作品翻页采集，支持视频与图文共用的评论管理页。"""
        if kind in ("private", "welcome"):
            raise InteractionAdapterError("webhook_only", "抖音私信通过开放平台回调接收，请配置官方授权和回调地址")
        require_kind(kind, ("comment",))
        state, size = decode_cursor(cursor), max(1, min(int(limit), 50))
        with browser_page(account, "about:blank") as page:
            title, next_work_state = "", None
            if item_id:
                work_id = str(item_id)
            else:
                captured = self._capture(page, WORK_PATH, MANAGE_URL)
                work_data = self._read_page(page, captured, {"count": 12, "max_cursor": state.get("workCursor", 0)})
                works = work_data.get("aweme_list")
                if not isinstance(works, list):
                    raise InteractionAdapterError("invalid_response", "抖音作品列表格式发生变化")
                index = max(0, int(state.get("workIndex", 0)))
                if index >= len(works):
                    return {"items": [], "cursor": None, "hasMore": False}
                work = works[index]
                work_id, title = str(work.get("aweme_id") or work.get("item_id") or ""), str(work.get("desc") or work.get("item_title") or "")
                if index + 1 < len(works):
                    next_work_state = {"workCursor": state.get("workCursor", 0), "workIndex": index + 1}
                elif work_data.get("has_more"):
                    next_work_state = {"workCursor": work_data.get("max_cursor"), "workIndex": 0}
                if not work_id:
                    raise InteractionAdapterError("invalid_response", "抖音作品缺少 ID")
            if not work_id.isdigit():
                raise InteractionAdapterError("invalid_target", "抖音作品 ID 无效")
            captured = self._capture(page, COMMENT_PATH, DETAIL_URL.format(item_id=work_id), cursor=state.get("commentCursor"))
            data = self._read_page(page, captured)
            rows = data.get("comment_info_list")
            if not isinstance(rows, list):
                raise InteractionAdapterError("invalid_response", "抖音评论列表格式发生变化")
            base_state = {key: state[key] for key in ("workCursor", "workIndex") if key in state}
            current_cursor = str(captured.get("requestCursor") or 0)
            main_next = {**base_state, "commentCursor": data["cursor"]} if data.get("has_more") and "cursor" in data else next_work_state
            children = [index for index, row in enumerate(rows) if int(row.get("reply_count") or 0) > 0]
            child_index = int(state.get("childIndex", -1))
            offset = max(0, int(state.get("offset", 0)))
            if child_index >= 0:
                if child_index >= len(rows):
                    raise InteractionAdapterError("invalid_cursor", "抖音主评论列表已变更，请重新同步")
                root = rows[child_index]
                if state.get("childRootId") and str(root.get("comment_id")) != str(state["childRootId"]):
                    raise InteractionAdapterError("invalid_cursor", "抖音主评论顺序已变更，请重新同步")
                reply = self._children(page, root, work_id, state.get("replyCursor", 0))
                reply_data = self._check(reply["payload"])
                reply_rows = reply_data.get("comment_info_list")
                if not isinstance(reply_rows, list):
                    raise InteractionAdapterError("invalid_response", "抖音子评论格式发生变化")
                items = [self._comment(row, work_id, title, root["comment_id"], current_cursor,
                                       reply.get("requestCursor", 0)) for row in reply_rows][offset:offset + size]
                child_state = {**base_state, "commentCursor": current_cursor, "childIndex": child_index, "childRootId": str(root["comment_id"])}
                if offset + size < len(reply_rows):
                    next_state = {**child_state, "replyCursor": state.get("replyCursor", 0), "offset": offset + size}
                elif reply_data.get("has_more"):
                    next_state = {**child_state, "replyCursor": reply_data["cursor"]}
                else:
                    following = next((index for index in children if index > child_index), None)
                    next_state = {**base_state, "commentCursor": current_cursor, "childIndex": following,
                                  "childRootId": str(rows[following]["comment_id"])} if following is not None else main_next
            else:
                items = [self._comment(row, work_id, title, comment_cursor=current_cursor) for row in rows][offset:offset + size]
                if offset + size < len(rows):
                    next_state = {**base_state, "commentCursor": current_cursor, "offset": offset + size}
                elif children:
                    next_state = {**base_state, "commentCursor": current_cursor, "childIndex": children[0],
                                  "childRootId": str(rows[children[0]]["comment_id"])}
                else:
                    next_state = main_next
            return {"items": items, "cursor": encode_cursor(next_state) if next_state else None, "hasMore": bool(next_state)}

    @staticmethod
    def _request_values(request):
        """把浏览器真实请求中的字段值展开，用目标 ID 与回复文案绑定回执。"""
        values = []
        def visit(value):
            if isinstance(value, dict):
                for inner in value.values():
                    visit(inner)
            elif isinstance(value, list):
                for inner in value:
                    visit(inner)
            else:
                values.append(str(value))
        body = request.post_data or ""
        try:
            visit(json.loads(body))
        except ValueError:
            visit(parse_qs(body))
        visit(parse_qs(urlsplit(request.url).query))
        return values

    def send_reply(self, account, message, text, reply_key):
        """原生回复按钮限定在唯一目标行内，绝不回退到顶层发表评论。"""
        if message.get("kind") in ("private", "welcome"):
            return send_private_reply(account, message, text, reply_key)
        text = validate_reply(message, text, reply_key)
        require_kind(message["kind"], ("comment",))
        item_id = str(message.get("itemId") or "")
        if not item_id.isdigit():
            raise InteractionAdapterError("invalid_target", "抖音作品 ID 无效")
        with browser_page(account, "about:blank") as page:
            raw = message.get("raw") or {}
            captured = self._capture(page, COMMENT_PATH, DETAIL_URL.format(item_id=item_id), cursor=raw.get("commentCursor", 0))
            rows = self._check(captured["payload"]).get("comment_info_list")
            if not isinstance(rows, list):
                raise InteractionAdapterError("invalid_response", "抖音评论列表格式发生变化")
            target_id = str(message["platformMessageId"])
            root_id = str(raw.get("rootCommentId") or target_id)
            source = next((row for row in rows if str(row.get("comment_id")) == root_id), None)
            # 老版本缺游标的持久化消息可逐原生页查找，后页消息不会固定只查第一页。
            seen = {str(captured.get("requestCursor", 0))}
            for _ in range(50):
                if source or not captured["payload"].get("has_more"):
                    break
                next_cursor = str(captured["payload"].get("cursor", ""))
                if not next_cursor or next_cursor in seen:
                    break
                seen.add(next_cursor)
                captured = self._capture(page, COMMENT_PATH, DETAIL_URL.format(item_id=item_id), cursor=next_cursor)
                rows = self._check(captured["payload"]).get("comment_info_list") or []
                source = next((row for row in rows if str(row.get("comment_id")) == root_id), None)
            if not source:
                raise InteractionAdapterError("invalid_target", "目标评论未在当前页面出现，请重新同步或到平台定位")
            if root_id != target_id:
                children = self._children(page, source, item_id, raw.get("replyCursor", 0))
                child_data = self._check(children["payload"])
                source = next((row for row in child_data.get("comment_info_list") or [] if str(row.get("comment_id")) == target_id), None)
                if not source:
                    raise InteractionAdapterError("invalid_target", "目标子评论未在指定回复页出现，请重新同步")
            target = self._comment(source, item_id, root_id=root_id if root_id != target_id else None)
            if not target["authorName"] or not target["raw"]["displayDate"]:
                raise InteractionAdapterError("invalid_target", "抖音目标评论缺少精确定位所需的作者或时间")
            row = self._find_row(page, target)
            operations = row.locator(':scope > div[class^="comment-operation-wrap-"]')
            operations.get_by_role("button", name="回复", exact=True).click()
            editor = operations.locator('div[class^="editable-input-"][contenteditable="true"]')
            if editor.count() != 1:
                raise InteractionAdapterError("not_sent", "目标评论行没有唯一回复输入框，未发送")
            editor.fill(text)
            submit = operations.get_by_role("button", name="发送", exact=True)
            if submit.count() != 1 or not submit.is_enabled():
                raise InteractionAdapterError("not_sent", "目标评论的发送按钮不可用，未发送")
            evidence = []
            def listener(response):
                parsed = urlsplit(response.url)
                if parsed.hostname != "creator.douyin.com" or "/comment/" not in parsed.path or response.request.method != "POST":
                    return
                values = self._request_values(response.request)
                if str(message["platformMessageId"]) not in values or text not in values:
                    return
                try:
                    evidence.append(response.json())
                except Exception:
                    pass
            page.on("response", listener)
            try:
                # 从此刻开始，即使点击抛异常，也不能假定未发送或改点另一个按钮。
                submit.click()
                for _ in range(15):
                    page.wait_for_timeout(500)
                    if evidence:
                        payload = evidence[0]
                        if business_code(payload.get("status_code"), "抖音", sending=True) != 0:
                            raise InteractionAdapterError("platform_rejected", "抖音拒绝回复评论，请核对平台权限或验证码")
                        return {"text": text, "confirmed": True}
            except InteractionAdapterError:
                raise
            except Exception as exc:
                raise InteractionAdapterError("send_unknown", "抖音评论已提交，结果待确认，请到平台核对") from exc
            finally:
                page.remove_listener("response", listener)
            raise InteractionAdapterError("send_unknown", "未观察到与目标评论匹配的抖音回执，请到平台核对")
