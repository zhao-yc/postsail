"""互动适配器的认证隔离、目标定位、分页和发送不确定性测试。"""
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from utils.interactions.adapters import get_adapter, list_capabilities
from utils.interactions.adapters.base import InteractionAdapterError, decode_cursor, encode_cursor, load_cookies, request_json
from utils.interactions.adapters.bilibili import BilibiliAdapter
from utils.interactions.adapters.channels import ChannelsAdapter
from utils.interactions.adapters.douyin import DouyinAdapter
from utils.interactions.adapters.douyin_openapi import parse_webhook, send_private_reply
from utils.interactions.adapters.xiaohongshu import XiaohongshuAdapter
from utils.interactions.service import InteractionService


class InteractionAdapterTests(unittest.TestCase):
    """所有发送测试使用隔离对象；从不连接外部平台。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cookie = Path(self.tmp.name) / "account.json"
        self.cookie.write_text(json.dumps({"cookies": [
            {"name": "SESSDATA", "value": "示例登录态", "domain": ".bilibili.com"},
            {"name": "bili_jct", "value": "示例校验值", "domain": ".bilibili.com"},
            {"name": "private_cookie", "value": "其他平台示例", "domain": ".example.com"},
            {"name": "session", "value": "示例微信会话", "domain": ".weixin.qq.com"},
        ]}), encoding="utf-8")
        self.account = {"id": 1, "platform": "bilibili", "name": "测试账号", "cookie_path": self.cookie}

    def tearDown(self):
        self.tmp.cleanup()

    def _persist(self, platform, platform_type, adapter, item):
        """走真实入库、公共详情和回复读取链路；平台网络在更低层被替身截获。"""
        service = InteractionService(Path(self.tmp.name) / f"{platform}.db", self.cookie.parent,
                                     adapter_factory=lambda _: adapter)
        with service.store.connect() as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,userName TEXT,filePath TEXT,status INTEGER)")
            conn.execute("INSERT INTO user_info VALUES(1,?,?,?,1)", (platform_type, "测试账号", self.cookie.name))
        account = service._account(1)
        item["raw"]["business_token"] = "不应入库的示例令牌"
        ids = service.ingest(account, item["kind"], [item], baseline=True)
        self.assertNotIn("raw", service.message(ids[0])["message"])
        with service.store.connect() as conn:
            persisted = json.loads(conn.execute("SELECT raw_json FROM interaction_messages WHERE id=?", (ids[0],)).fetchone()[0])
        self.assertNotIn("business_token", persisted)
        return service, ids[0], persisted

    def test_cookie_domain_isolation(self):
        cookies = load_cookies(self.account, "api.bilibili.com", ("SESSDATA",))
        self.assertIn("SESSDATA", cookies)
        self.assertNotIn("private_cookie", cookies)
        with self.assertRaises(InteractionAdapterError):
            load_cookies(self.account, "api.vc.bilibili.com.evil.example", ("SESSDATA",))

    def test_cursor_rejects_corruption_instead_of_restarting(self):
        self.assertEqual(decode_cursor(encode_cursor({"page": 2})), {"page": 2})
        for invalid in ("不是游标", "x" * 4100, encode_cursor({})[:-1]):
            with self.assertRaises(InteractionAdapterError):
                decode_cursor(invalid)

    @patch("utils.interactions.adapters.base.requests.request", side_effect=requests.Timeout("示例超时"))
    def test_send_timeout_is_unknown_and_has_no_retry(self, request):
        with self.assertRaises(InteractionAdapterError) as error:
            request_json("POST", "https://api.bilibili.com/x/v2/reply/add", sending=True)
        self.assertEqual(error.exception.code, "send_unknown")
        self.assertFalse(error.exception.retryable)
        self.assertEqual(request.call_count, 1)

    @patch("utils.interactions.adapters.base.requests.request")
    def test_requests_keep_tls_and_reject_redirects(self, request):
        request.return_value.status_code = 200
        request.return_value.json.return_value = {"code": 0}
        request_json("GET", "https://api.bilibili.com/x/web-interface/nav")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
        self.assertNotEqual(request.call_args.kwargs.get("verify"), False)

    def test_capabilities_do_not_infer_interactions_from_publish(self):
        capabilities = {row["platform"]: row for row in list_capabilities()}
        self.assertEqual(capabilities["xiaohongshu"]["kinds"], ["private"])
        self.assertEqual(capabilities["douyin"]["fetchableKinds"], ["comment"])
        self.assertEqual(capabilities["douyin"]["operations"]["private"]["transport"], "webhook")
        self.assertEqual(capabilities["kuaishou"]["status"], "unsupported")
        with self.assertRaises(InteractionAdapterError):
            get_adapter("kuaishou")
        for row in capabilities.values():
            for operation in row["operations"].values():
                self.assertNotEqual(operation.get("reply"), "available")

    def test_douyin_account_capability_requires_separate_official_authorization(self):
        account = {**self.account, "platform": "douyin"}
        row = next(row for row in list_capabilities(account) if row["platform"] == "douyin")
        self.assertEqual(row["operations"]["welcome"]["reply"], "needs_login")
        self.assertEqual(row["operations"]["private"]["reply"], "needs_login")
        self._write_open_config()
        row = next(row for row in list_capabilities(account) if row["platform"] == "douyin")
        self.assertEqual(row["operations"]["welcome"]["reply"], "unverified")

    def test_absent_or_boolean_business_codes_never_confirm_or_allow_retry(self):
        for adapter, module, payload_key in ((BilibiliAdapter(), "bilibili", "code"), (ChannelsAdapter(), "channels", "errCode")):
            for value in (None, False, True, {}, "未知"):
                with self.subTest(platform=adapter.platform, value=value):
                    with patch(f"utils.interactions.adapters.{module}.request_json", return_value={payload_key: value, "data": {}}):
                        with self.assertRaises(InteractionAdapterError) as error:
                            adapter._request(self.account, "/模拟发送", sending=True)
                    self.assertEqual(error.exception.code, "send_unknown")
                    self.assertFalse(error.exception.retryable)

    def test_bilibili_comment_tree_keeps_parent_and_direction(self):
        item = BilibiliAdapter._comment({"rpid_str": "9", "root_str": "7", "parent_str": "8",
            "ctime": 1700000000, "member": {"mid": "2", "uname": "作者"},
            "content": {"message": "子回复"}, "sensitive_debug": "不应存储"}, {"aid": 10, "title": "作品"}, "2")
        self.assertEqual((item["threadId"], item["parentId"], item["direction"]), ("7", "8", "outbound"))
        self.assertNotIn("sensitive_debug", item["raw"])

    def test_bilibili_retracted_and_media_messages_are_not_automatic_targets(self):
        self.assertIsNone(BilibiliAdapter._private({"msg_status": 1, "msg_type": 1, "content": '{"content":"撤回文本"}'}, "3", "2"))
        self.assertIsNone(BilibiliAdapter._private({"msg_status": 0, "msg_type": 2}, "3", "2"))

    def test_bilibili_history_cursor_pins_original_peer(self):
        adapter = BilibiliAdapter()
        adapter._identity = MagicMock(return_value="2")
        adapter._request = MagicMock(return_value={"messages": [{"msg_status": 0, "msg_type": 1,
            "sender_uid": 3, "msg_key": 8, "content": '{"content":"第二页"}', "timestamp": 1700000000}], "has_more": False})
        result = adapter.fetch(self.account, cursor=encode_cursor({"peerId": "3", "endSeq": 100, "sessionTs": 200, "moreSessions": True}), kind="private")
        self.assertEqual(result["items"][0]["threadId"], "3")
        self.assertEqual(adapter._request.call_args.args[2]["end_seqno"], 100)
        self.assertEqual(decode_cursor(result["cursor"]), {"endTs": 200})

    def test_bilibili_full_children_page_not_preview(self):
        adapter = BilibiliAdapter()
        adapter._identity = MagicMock(return_value="2")
        root = {"rpid": 7, "rcount": 5, "member": {}, "content": {"message": "主楼"}, "replies": [{"rpid": 8}]}
        adapter._request = MagicMock(side_effect=[{"aid": 1, "owner": {"mid": 2}},
            {"replies": [root], "page": {"size": 20, "count": 1}},
            {"replies": [{"rpid": 9, "root": 7, "parent": 7, "member": {}, "content": {"message": "完整回复"}}], "page": {"size": 20, "count": 5}}])
        result = adapter.fetch(self.account, item_id="1", kind="comment", cursor=encode_cursor({"childIndex": 0, "childPage": 1}))
        self.assertEqual([row["platformMessageId"] for row in result["items"]], ["9"])
        self.assertIn("/x/v2/reply/reply", adapter._request.call_args.args)

    def test_bilibili_success_without_reply_id_is_unknown(self):
        adapter = BilibiliAdapter()
        adapter._request = MagicMock(return_value={})
        with self.assertRaises(InteractionAdapterError) as error:
            adapter.send_reply(self.account, {"platformMessageId": "7", "kind": "comment", "itemId": "10", "raw": {"root": "7"}}, "谢谢", "唯一键")
        self.assertEqual(error.exception.code, "send_unknown")
        self.assertEqual(adapter._request.call_count, 1)

    def test_channels_identity_and_idempotency_key(self):
        adapter = ChannelsAdapter()
        adapter._auth = MagicMock(return_value={"finderUsername": "owner"})
        adapter._request = MagicMock(return_value={})
        message = {"platformMessageId": "7", "kind": "private", "threadId": "session",
                   "raw": {"ownerId": "owner", "peerId": "peer", "sessionId": "session"}}
        adapter.send_reply(self.account, message, "谢谢", "唯一键")
        pack = adapter._request.call_args.args[2]["msgPack"]
        self.assertEqual(pack["fromUsername"], "owner")
        self.assertEqual(pack["toUsername"], "peer")
        client_id = pack["cliMsgId"]
        adapter.send_reply(self.account, message, "谢谢", "唯一键")
        self.assertEqual(adapter._request.call_args.args[2]["msgPack"]["cliMsgId"], client_id)
        message["raw"]["ownerId"] = "另一个账号"
        with self.assertRaises(InteractionAdapterError):
            adapter.send_reply(self.account, message, "谢谢", "另一个键")
        self.assertEqual(adapter._request.call_count, 2)

    def test_channels_private_message_of_another_account_is_rejected(self):
        with self.assertRaises(InteractionAdapterError):
            ChannelsAdapter._private({"fromUsername": "a", "toUsername": "b", "sessionId": "s", "rawContent": "消息"}, "c")

    def test_channels_expanded_comment_snapshot_keeps_limit_and_detects_changes(self):
        adapter = ChannelsAdapter()
        adapter._auth = MagicMock(return_value={"finderUsername": "owner"})
        rows = [{"commentId": "root", "commentContent": "主楼", "levelTwoComment": [
                    {"commentId": "child-1", "commentContent": "子楼一"}, {"commentId": "child-2", "commentContent": "子楼二"}]}]
        adapter._request = MagicMock(return_value={"comment": rows})
        first = adapter.fetch(self.account, item_id="work", limit=2)
        self.assertEqual([row["platformMessageId"] for row in first["items"]], ["root", "child-1"])
        second = adapter.fetch(self.account, item_id="work", limit=2, cursor=first["cursor"])
        self.assertEqual([row["platformMessageId"] for row in second["items"]], ["child-2"])
        self.assertFalse(second["hasMore"])
        rows[0]["levelTwoComment"].append({"commentId": "child-3", "commentContent": "同步中新增"})
        with self.assertRaises(InteractionAdapterError) as error:
            adapter.fetch(self.account, item_id="work", limit=2, cursor=first["cursor"])
        self.assertEqual(error.exception.code, "invalid_cursor")

    def _write_open_config(self):
        config = {"client_key": "示例应用", "client_secret": "示例密钥", "open_id": "owner", "business_token": "示例授权"}
        self.cookie.with_suffix(".interactions.json").write_text(json.dumps(config), encoding="utf-8")
        return config

    def test_douyin_webhook_requires_signature_and_account_ownership(self):
        config = self._write_open_config()
        payload = {"client_key": config["client_key"], "event": "im_receive_msg", "from_user_id": "peer", "to_user_id": "owner",
            "content": {"conversation_type": 1, "message_type": "text", "conversation_short_id": "thread", "server_message_id": "message", "text": "你好", "create_time": 1700000000000}}
        body = json.dumps(payload).encode()
        signature = hashlib.sha1(config["client_secret"].encode() + body).hexdigest()
        result = parse_webhook(self.account, body, signature)
        self.assertEqual(result["items"][0]["raw"]["peerId"], "peer")
        self.assertNotIn(config["client_secret"], json.dumps(result))
        with self.assertRaises(InteractionAdapterError):
            parse_webhook(self.account, body, "错误签名")
        payload["to_user_id"] = "另一个账号"
        body = json.dumps(payload).encode()
        with self.assertRaises(InteractionAdapterError):
            parse_webhook(self.account, body, hashlib.sha1(config["client_secret"].encode() + body).hexdigest())

    def test_douyin_signed_challenge(self):
        config = self._write_open_config()
        body = json.dumps({"client_key": config["client_key"], "event": "verify_webhook", "content": {"challenge": 123}}).encode()
        result = parse_webhook(self.account, body, hashlib.sha1(config["client_secret"].encode() + body).hexdigest())
        self.assertEqual(result, {"challenge": 123})

    @patch("utils.interactions.adapters.douyin_openapi.request_json")
    def test_douyin_welcome_requires_official_entry_event_and_30_second_window(self, request):
        config = self._write_open_config()
        payload = {"event": "im_enter_direct_msg", "client_key": config["client_key"], "from_user_id": "peer", "to_user_id": "owner",
                   "content": json.dumps({"conversation_type": 1, "conversation_short_id": "thread", "server_message_id": "entry-id",
                                          "create_time": int(datetime.now(timezone.utc).timestamp() * 1000)})}
        body = json.dumps(payload).encode()
        message = parse_webhook(self.account, body, hashlib.sha1(config["client_secret"].encode() + body).hexdigest())["items"][0]
        self.assertEqual((message["kind"], message["direction"]), ("welcome", "inbound"))
        request.return_value = {"data": {"error_code": 0, "msg_id": "welcome-id"}}
        service, message_id, raw = self._persist("douyin", 3, DouyinAdapter(), message)
        service.store.save_record("interaction_rules", {"id": "welcome-rule", "enabled": True, "text": "欢迎咨询",
                                  "accountIds": [1], "platform": "douyin", "kinds": ["welcome"], "trigger": "welcome",
                                  "enabledAt": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()})
        result = service.reply(message_id, {"text": "欢迎咨询", "idempotencyKey": "欢迎键"}, source="automatic", rule_id="welcome-rule")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(raw["event"], "im_enter_direct_msg")
        data = request.call_args.kwargs["json"]
        self.assertEqual((data["scene"], data["msg_id"], data["to_user_id"], data["conversation_id"]),
                         ("im_enter_direct_msg", "entry-id", "peer", "thread"))
        message["createdAt"] = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
        with self.assertRaises(InteractionAdapterError):
            send_private_reply(self.account, message, "欢迎", "过期键")
        message["createdAt"] = datetime.now(timezone.utc).isoformat()
        message["raw"]["event"] = "new_follow_action"
        with self.assertRaises(InteractionAdapterError):
            send_private_reply(self.account, message, "欢迎", "伪事件键")
        self.assertEqual(request.call_count, 1)

    def test_douyin_follow_is_never_transformed_into_private_welcome(self):
        config = self._write_open_config()
        body = json.dumps({"event": "new_follow_action", "client_key": config["client_key"], "content": '{"action_type":1}'}).encode()
        result = parse_webhook(self.account, body, hashlib.sha1(config["client_secret"].encode() + body).hexdigest())
        self.assertEqual(result, {"items": []})

    @patch("utils.interactions.adapters.douyin_openapi.request_json")
    def test_douyin_private_send_uses_exact_inbound_target(self, request):
        self._write_open_config()
        message = {"platformMessageId": "inbound-id", "kind": "private", "threadId": "thread", "createdAt": datetime.now(timezone.utc).isoformat(),
            "raw": {"provider": "douyin_openapi", "ownerId": "owner", "peerId": "peer", "conversationId": "thread"}}
        request.return_value = {"data": {"error_code": 0}, "extra": {"error_code": 0}, "msg_id": "outbound-id"}
        result = send_private_reply(self.account, message, "谢谢", "唯一键")
        self.assertEqual(result["platformReplyId"], "outbound-id")
        self.assertEqual(request.call_args.kwargs["json"]["msg_id"], "inbound-id")
        self.assertEqual(request.call_args.kwargs["json"]["to_user_id"], "peer")
        message["createdAt"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaises(InteractionAdapterError):
            send_private_reply(self.account, message, "谢谢", "另一个键")
        self.assertEqual(request.call_count, 1)

    def test_douyin_private_poll_does_not_fake_empty_success(self):
        with self.assertRaises(InteractionAdapterError) as error:
            get_adapter("douyin").fetch(self.account, kind="private")
        self.assertEqual(error.exception.code, "webhook_only")

    def test_douyin_duplicate_visible_comments_are_never_sent(self):
        adapter = DouyinAdapter()
        source = {"comment_id": "encrypted-id", "text": "原评论", "create_time": 1700000000,
                  "user_info": {"screen_name": "作者", "user_id": "peer"}}
        normalized = adapter._comment(source, "123")
        page = MagicMock()
        page.locator.return_value.evaluate_all.return_value = [
            {"index": 0, "author": "作者", "date": normalized["raw"]["displayDate"], "text": "原评论", "images": 0},
            {"index": 1, "author": "作者", "date": normalized["raw"]["displayDate"], "text": "原评论", "images": 0}]
        @contextmanager
        def fake_page(*_):
            yield page
        adapter._capture = MagicMock(return_value={"payload": {"status_code": 0, "comment_info_list": [source]}})
        with patch("utils.interactions.adapters.douyin.browser_page", fake_page):
            with self.assertRaises(InteractionAdapterError):
                adapter.send_reply(self.account, normalized, "谢谢", "唯一键")
        page.get_by_role.assert_not_called()

    def test_xiaohongshu_send_unknown_never_presses_enter_twice(self):
        adapter = XiaohongshuAdapter()
        page = MagicMock()
        page.locator.return_value.count.return_value = 1
        chat = {"chat_user_id": "peer", "user_id": "owner", "chat_id": "thread"}
        before = [{"platformMessageId": "inbound"}]
        adapter._get = MagicMock(return_value={"chats": [chat]})
        adapter._history = MagicMock(side_effect=[(before, None, False), RuntimeError("连接断开")])
        @contextmanager
        def fake_page(*_):
            yield page
        message = {"platformMessageId": "inbound", "kind": "private", "threadId": "thread", "raw": {"peerId": "peer", "ownerId": "owner"}}
        with patch("utils.interactions.adapters.xiaohongshu.browser_page", fake_page):
            with self.assertRaises(InteractionAdapterError) as error:
                adapter.send_reply(self.account, message, "谢谢", "唯一键")
        self.assertEqual(error.exception.code, "send_unknown")
        page.locator.return_value.press.assert_called_once_with("Enter")

    @patch("utils.interactions.adapters.bilibili.request_json")
    def test_bilibili_persisted_comment_and_private_targets_reach_transport(self, request):
        adapter = BilibiliAdapter()
        comment = adapter._comment({"rpid": 9, "root": 7, "parent": 8, "member": {"mid": 3},
                                    "content": {"message": "子评论"}}, {"aid": 10}, "2")
        service, message_id, raw = self._persist("bilibili", 6, adapter, comment)
        request.return_value = {"code": 0, "data": {"rpid": 11}}
        result = service.reply(message_id, {"text": "谢谢", "idempotencyKey": "评论键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual((request.call_args.kwargs["data"]["root"], request.call_args.kwargs["data"]["parent"]), ("7", "9"))
        private = adapter._private({"msg_status": 0, "msg_type": 1, "msg_key": 12, "sender_uid": 3,
                                    "content": '{"content":"咨询"}'}, "3", "2")
        ids = service.ingest(service._account(1), "private", [private], baseline=True)
        request.side_effect = [{"code": 0, "data": {"isLogin": True, "mid": 2}}, {"code": 0, "data": {"msg_key": 13}}]
        result = service.reply(ids[0], {"text": "您好", "idempotencyKey": "私信键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual((request.call_args.kwargs["data"]["msg[sender_uid]"], request.call_args.kwargs["data"]["msg[receiver_id]"]), ("2", "3"))

    @patch("utils.interactions.adapters.channels.request_json")
    def test_channels_persisted_comment_and_private_targets_reach_transport(self, request):
        adapter = ChannelsAdapter()
        adapter._auth = MagicMock(return_value={"finderUsername": "owner"})
        request.return_value = {"errCode": 0, "data": {}}
        comment = adapter._comment({"commentId": "child", "commentContent": "子评论", "commentUsername": "peer"}, "work", "owner", root_id="root")
        service, message_id, raw = self._persist("tencent", 2, adapter, comment)
        result = service.reply(message_id, {"text": "谢谢", "idempotencyKey": "评论键"})
        self.assertEqual(result["status"], "sent")
        data = request.call_args.kwargs["json"]
        self.assertEqual((data["replyCommentId"], data["rootCommentId"], data["comment"]["commentId"], data["exportId"]), ("child", "root", "child", "work"))
        private = adapter._private({"msgId": "private", "fromUsername": "peer", "toUsername": "owner", "sessionId": "session", "rawContent": "咨询"}, "owner")
        ids = service.ingest(service._account(1), "private", [private], baseline=True)
        result = service.reply(ids[0], {"text": "您好", "idempotencyKey": "私信键"})
        self.assertEqual(result["status"], "sent")
        pack = request.call_args.kwargs["json"]["msgPack"]
        self.assertEqual((pack["fromUsername"], pack["toUsername"], pack["sessionId"]), ("owner", "peer", "session"))

    @patch("utils.interactions.adapters.douyin_openapi.request_json")
    def test_douyin_persisted_private_target_reaches_transport(self, request):
        config = self._write_open_config()
        body = json.dumps({"event": "im_receive_msg", "client_key": config["client_key"], "from_user_id": "peer", "to_user_id": "owner",
                           "content": {"conversation_type": 1, "message_type": "text", "server_message_id": "incoming", "conversation_short_id": "session",
                                       "text": "咨询", "create_time": int(datetime.now(timezone.utc).timestamp() * 1000)}}).encode()
        item = parse_webhook(self.account, body, hashlib.sha1(config["client_secret"].encode() + body).hexdigest())["items"][0]
        service, message_id, raw = self._persist("douyin", 3, DouyinAdapter(), item)
        request.return_value = {"data": {"error_code": 0, "msg_id": "outgoing"}}
        result = service.reply(message_id, {"text": "您好", "idempotencyKey": "私信键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual((request.call_args.kwargs["json"]["msg_id"], request.call_args.kwargs["json"]["to_user_id"]), ("incoming", "peer"))

    def test_xiaohongshu_persisted_target_reaches_unique_existing_conversation(self):
        adapter, page = XiaohongshuAdapter(), MagicMock()
        chat = {"chat_user_id": "peer", "user_id": "owner", "chat_id": "thread"}
        rows = [{"id": "incoming", "store_id": 1, "sender_id": "peer", "receiver_id": "owner", "content": "咨询"}]
        def data(_, path):
            return {"chats": [chat]} if "/chats?" in path else {"out_message_list": list(rows)}
        adapter._get = MagicMock(side_effect=data)
        item = adapter._history(page, chat, 0, 50)[0][0]
        service, message_id, raw = self._persist("xiaohongshu", 1, adapter, item)
        page.locator.return_value.count.return_value = 1
        def submit(_):
            rows.append({"id": "outgoing", "store_id": 2, "sender_id": "owner", "receiver_id": "peer", "content": "您好"})
        page.locator.return_value.press.side_effect = submit
        entered = []
        @contextmanager
        def fake_page(account, url):
            entered.append(url)
            yield page
        with patch("utils.interactions.adapters.xiaohongshu.browser_page", fake_page):
            result = service.reply(message_id, {"text": "您好", "idempotencyKey": "私信键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual(entered, ["https://www.xiaohongshu.com/chat/peer"])
        page.locator.return_value.press.assert_called_once_with("Enter")

    def _douyin_send_page(self, source, *, child=False, receipt=None):
        """替身仅模拟本行按钮和绑定目标 ID 的平台回执，不连接真实 Chrome。"""
        page, row, operations, editor, submit = (MagicMock() for _ in range(5))
        target = DouyinAdapter._comment(source, "123", root_id="root" if child else None)
        page.locator.return_value.evaluate_all.return_value = [{"index": 0, "author": target["authorName"],
            "date": target["raw"]["displayDate"], "text": target["raw"]["sourceText"], "images": 0, "isReply": child}]
        page.locator.return_value.nth.return_value = row
        row.locator.return_value = operations
        operations.locator.return_value = editor
        editor.count.return_value = 1
        operations.get_by_role.side_effect = lambda role, name, exact: submit if name == "发送" else MagicMock()
        submit.count.return_value, submit.is_enabled.return_value = 1, True
        listeners = {}
        page.on.side_effect = lambda event, callback: listeners.update({event: callback})
        response = MagicMock()
        response.url = "https://creator.douyin.com/aweme/v1/creator/comment/reply/"
        response.request.method = "POST"
        response.request.post_data = json.dumps({"comment_id": source["comment_id"], "text": "谢谢"})
        response.request.url = response.url
        response.json.return_value = {"status_code": 0} if receipt is None else receipt
        submit.click.side_effect = lambda: listeners["response"](response)
        return page, submit, target

    def test_douyin_persisted_historical_comment_target_uses_native_cursor(self):
        adapter = DouyinAdapter()
        source = {"comment_id": "target", "text": "历史评论", "create_time": 1700000000,
                  "user_info": {"screen_name": "作者", "user_id": "peer"}}
        page, submit, item = self._douyin_send_page(source)
        item["raw"]["commentCursor"] = "20"
        service, message_id, raw = self._persist("douyin", 3, adapter, item)
        adapter._capture = MagicMock(return_value={"requestCursor": "20", "payload": {"status_code": 0, "comment_info_list": [source], "has_more": False}})
        @contextmanager
        def fake_page(*_):
            yield page
        with patch("utils.interactions.adapters.douyin.browser_page", fake_page):
            result = service.reply(message_id, {"text": "谢谢", "idempotencyKey": "评论键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual(adapter._capture.call_args.kwargs["cursor"], "20")
        submit.click.assert_called_once()

    def test_douyin_persisted_child_target_keeps_root_and_reply_page(self):
        adapter = DouyinAdapter()
        root = {"comment_id": "root", "text": "主楼", "create_time": 1700000000, "reply_count": 25, "user_info": {"screen_name": "楼主"}}
        source = {"comment_id": "child", "text": "子评论", "create_time": 1700000100, "user_info": {"screen_name": "回复者", "user_id": "peer"}}
        page, submit, item = self._douyin_send_page(source, child=True)
        item["raw"]["commentCursor"], item["raw"]["replyCursor"] = "10", "20"
        service, message_id, raw = self._persist("douyin", 3, adapter, item)
        adapter._capture = MagicMock(return_value={"requestCursor": "10", "payload": {"status_code": 0, "comment_info_list": [root], "has_more": False}})
        adapter._children = MagicMock(return_value={"requestCursor": "20", "payload": {"status_code": 0, "comment_info_list": [source], "has_more": False}})
        @contextmanager
        def fake_page(*_):
            yield page
        with patch("utils.interactions.adapters.douyin.browser_page", fake_page):
            result = service.reply(message_id, {"text": "谢谢", "idempotencyKey": "子评论键"})
        self.assertEqual(result["status"], "sent")
        self.assertEqual(adapter._children.call_args.args[1]["comment_id"], "root")
        self.assertEqual(adapter._children.call_args.args[3], "20")
        submit.click.assert_called_once()

    def test_douyin_matching_receipt_without_valid_business_code_is_unknown(self):
        for payload in ({}, {"status_code": False}):
            with self.subTest(payload=payload):
                adapter = DouyinAdapter()
                source = {"comment_id": "target", "text": "评论", "create_time": 1700000000, "user_info": {"screen_name": "作者"}}
                page, submit, item = self._douyin_send_page(source, receipt=payload)
                adapter._capture = MagicMock(return_value={"payload": {"status_code": 0, "comment_info_list": [source]}})
                @contextmanager
                def fake_page(*_):
                    yield page
                with patch("utils.interactions.adapters.douyin.browser_page", fake_page):
                    with self.assertRaises(InteractionAdapterError) as error:
                        adapter.send_reply(self.account, item, "谢谢", "评论键")
                self.assertEqual(error.exception.code, "send_unknown")
                submit.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
