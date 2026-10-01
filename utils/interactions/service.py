"""互动采集、人工回复和自动回复策略的业务约束。"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from inspect import signature
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import InteractionStore, encode, now

PLATFORM_TYPES = {1: "xiaohongshu", 2: "tencent", 3: "douyin", 4: "kuaishou", 5: "baijiahao",
                  6: "bilibili", 7: "toutiao", 8: "sohu", 9: "zhihu"}


class InteractionError(ValueError):
    """前端可操作的业务错误，不泄露 Cookie 或平台请求细节。"""
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status, self.code = status, code


def text_value(value, label, maximum=2000, allow_empty=False):
    """文本参数拒绝隐式类型转换和超长内容。"""
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise InteractionError(f"{label}必须为{'不超过' + str(maximum) + '字的' if maximum else ''}文本")
    return value.strip()


def instant(value):
    """解析平台时间；无法确认时间的消息不参与自动回复。"""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def routing_metadata(raw):
    """仅保存适配器回复必需的路由字段，不把 Cookie、令牌和签名写入消息。"""
    if not isinstance(raw, dict):
        return {}
    keys = {"provider", "ownerId", "peerId", "talkerId", "sessionId", "conversationId", "root", "rootCommentId", "oid",
            "sourceText", "displayDate", "imageCount", "replyCount", "isAuthor", "event", "seqno", "storeId",
            "commentCursor", "replyCursor", "replyToName"}
    result = {k: v for k, v in raw.items() if k in keys and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 5000}
    comment_keys = {"commentId", "commentContent", "commentNickname", "commentCreatetime", "commentUsername",
                    "commentHeadUrl", "replyCommentId", "rootCommentId"}
    if isinstance(raw.get("comment"), dict):
        result["comment"] = {k: v for k, v in raw["comment"].items() if k in comment_keys and
                             isinstance(v, (str, int, float, bool)) and len(str(v)) <= 5000}
    return result


class InteractionService:
    """平台 adapter 可注入，隔离测试无需账号和外网。"""

    def __init__(self, db_path, cookie_dir, adapter_factory=None, capability_provider=None):
        self.store = InteractionStore(db_path)
        self.cookie_dir = Path(cookie_dir)
        if adapter_factory is None or capability_provider is None:
            from .adapters import get_adapter, list_capabilities
            adapter_factory = adapter_factory or get_adapter
            capability_provider = capability_provider or list_capabilities
        self.adapter_factory = adapter_factory
        self.capability_provider = capability_provider
        self._account_locks, self._locks_guard = {}, threading.Lock()
        self._stop, self._worker = threading.Event(), None
        self._worker_guard = threading.Lock()

    def _lock(self, account_id):
        """一个服务实例内同账号采集和发送串行，减少浏览器并发冲突。"""
        with self._locks_guard:
            return self._account_locks.setdefault(account_id, threading.RLock())

    def capabilities(self):
        """能力表来自实际适配器，不由发布支持范围推断。"""
        return {"platforms": self.capability_provider()}

    def _capability(self, account):
        """账号级能力检查官方授权；保持无参数的测试或第三方 provider 兼容。"""
        try:
            signature(self.capability_provider).bind(account=account)
        except TypeError:
            capabilities = self.capability_provider()
        else:
            capabilities = self.capability_provider(account=account)
        return next((cap for cap in capabilities if cap["platform"] == account["platform"]), None)

    def _account(self, account_id):
        """账号必须来自现有账号管理，Cookie 必须位于配置目录。"""
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
            raise InteractionError("账号 ID 无效")
        with self.store.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
                raise InteractionError("请先在账号管理中登录平台账号", 404)
            row = conn.execute("SELECT * FROM user_info WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise InteractionError("账号不存在", 404)
        platform = PLATFORM_TYPES.get(row["type"])
        if not platform:
            raise InteractionError("不支持的账号平台")
        cookie = (self.cookie_dir / str(row["filePath"])).resolve()
        if not cookie.is_relative_to(self.cookie_dir.resolve()):
            raise InteractionError("账号会话文件路径无效")
        return {"id": row["id"], "platform": platform, "name": row["userName"], "status": row["status"],
                "cookie_path": cookie}

    def accounts(self):
        """账号响应不包含会话文件地址或敏感认证数据。"""
        with self.store.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
                return {"items": []}
            ids = [r[0] for r in conn.execute("SELECT id FROM user_info ORDER BY id")]
            states = [dict(r) for r in conn.execute("SELECT * FROM interaction_sync_state")]
        settings = self.store.settings()
        items = []
        for account_id in ids:
            account = self._account(account_id)
            matching = [s for s in states if s["account_id"] == account_id]
            items.append({"id": account_id, "platform": account["platform"], "name": account["name"],
                          "status": account["status"], "cookieAvailable": account["cookie_path"].is_file(),
                          "capabilities": self._capability(account),
                          "enabled": account_id in settings["accountIds"],
                          "lastSyncedAt": max((s["last_synced_at"] for s in matching if s["last_synced_at"]), default=None),
                          "syncState": "syncing" if any(s["state"] == "syncing" for s in matching) else "idle",
                          "error": next((s["error"] for s in matching if s["error"]), None)})
        return {"items": items}

    def _serialize_message(self, row, conn=None):
        """规范化持久化字段，回复状态始终来自真正的发送记录。"""
        names = {"account_id": "accountId", "platform_message_id": "platformMessageId", "thread_id": "threadId",
                 "parent_id": "parentId", "item_id": "itemId", "item_title": "itemTitle", "author_id": "authorId",
                 "author_name": "authorName", "author_avatar": "authorAvatar", "created_at": "createdAt",
                 "first_seen_at": "firstSeenAt"}
        result = {names.get(k, k): v for k, v in dict(row).items() if k != "raw_json"}
        result["read"], result["handled"] = bool(result["read"]), bool(result["handled"])
        if conn:
            reply = conn.execute("SELECT status FROM interaction_replies WHERE message_id=? "
                                 "ORDER BY created_at DESC,rowid DESC LIMIT 1", (row["id"],)).fetchone()
            result["replyStatus"] = reply[0] if reply else None
        return result

    def messages(self, query):
        """按账号、平台、消息类型、处理状态和正文搜索，所有条件参数化。"""
        try:
            page, size = int(query.get("page", 1)), int(query.get("pageSize", 30))
        except (ValueError, TypeError):
            raise InteractionError("分页参数无效")
        if page < 1 or not 1 <= size <= 100:
            raise InteractionError("页码需大于0，每页数量需在1至100之间")
        conditions, values = ["direction='inbound'"], []
        for key, column in (("accountId", "account_id"), ("platform", "platform"), ("kind", "kind")):
            if query.get(key) and query[key] != "all":
                conditions.append(f"{column}=?")
                values.append(query[key])
        state = query.get("state", "all")
        if state not in {"all", "unread", "unhandled", "handled"}:
            raise InteractionError("消息状态筛选无效")
        if state == "unread":
            conditions.append("read=0")
        if state in {"unhandled", "handled"}:
            conditions.append("handled=?")
            values.append(int(state == "handled"))
        if query.get("q"):
            conditions.append("(text LIKE ? ESCAPE '\\' OR author_name LIKE ? ESCAPE '\\' OR item_title LIKE ? ESCAPE '\\')")
            value = "%" + str(query["q"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            values.extend([value] * 3)
        where = " AND ".join(conditions)
        with self.store.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM interaction_messages WHERE {where}", values).fetchone()[0]
            rows = conn.execute(f"SELECT * FROM interaction_messages WHERE {where} "
                                "ORDER BY COALESCE(created_at,first_seen_at) DESC,id DESC LIMIT ? OFFSET ?",
                                [*values, size, (page - 1) * size]).fetchall()
            items = [self._serialize_message(r, conn) for r in rows]
            counts = conn.execute("SELECT SUM(read=0),SUM(handled=0) FROM interaction_messages WHERE direction='inbound'").fetchone()
        return {"items": items, "total": total, "page": page, "pageSize": size,
                "unreadCount": counts[0] or 0, "unhandledCount": counts[1] or 0}

    def message(self, message_id):
        """详情包括发送记录；读取本身不会修改已读状态。"""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM interaction_messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                raise InteractionError("消息不存在", 404)
            return {"message": self._serialize_message(row, conn),
                    "replies": [self._serialize_reply(r) for r in conn.execute(
                        "SELECT * FROM interaction_replies WHERE message_id=? ORDER BY created_at,rowid", (message_id,))]}

    def mark(self, message_id, data):
        """已读和已处理是本地工作状态，不冒充平台的已读回执。"""
        self.message(message_id)
        fields, values = [], []
        for key in ("read", "handled"):
            if key in data:
                if not isinstance(data[key], bool):
                    raise InteractionError(f"{key}必须为布尔值")
                fields.append(f"{key}=?")
                values.append(int(data[key]))
        if not fields:
            raise InteractionError("请提供已读或处理状态")
        with self.store.connect() as conn:
            conn.execute(f"UPDATE interaction_messages SET {','.join(fields)} WHERE id=?", [*values, message_id])
        return self.message(message_id)["message"]

    @staticmethod
    def _serialize_reply(row):
        """只返回运营信息，不暴露内部请求散列和幂等令牌。"""
        return {"id": row["id"], "messageId": row["message_id"], "text": row["text"], "status": row["status"],
                "source": row["source"], "ruleId": row["rule_id"], "platformReplyId": row["platform_reply_id"],
                "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    def reply(self, message_id, data, source="manual", rule_id=None):
        """先原子登记发送意图再调用平台；同一幂等键绝不二次发送。"""
        content = text_value(data.get("text"), "回复内容", 1000)
        key = text_value(data.get("idempotencyKey"), "幂等键", 200)
        message = self.message(message_id)["message"]
        with self.store.connect() as conn:
            internal = conn.execute("SELECT raw_json FROM interaction_messages WHERE id=?", (message_id,)).fetchone()
        message["raw"] = json.loads(internal[0])
        if message["direction"] != "inbound" or message["kind"] in {"welcome", "follow"} and source == "manual":
            raise InteractionError("该消息不支持人工回复")
        account = self._account(message["accountId"])
        adapter = self.adapter_factory(account["platform"])
        digest = hashlib.sha256(encode({"messageId": message_id, "text": content}).encode()).hexdigest()
        with self._lock(account["id"]):
            with self.store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                previous = conn.execute("SELECT * FROM interaction_replies WHERE idempotency_key=?", (key,)).fetchone()
                if previous:
                    if previous["request_hash"] != digest:
                        raise InteractionError("此幂等键已用于不同的回复", 409)
                    return self._serialize_reply(previous)
                pending = conn.execute("SELECT 1 FROM interaction_replies WHERE message_id=? AND status IN ('sending','unknown')",
                                       (message_id,)).fetchone()
                if pending:
                    raise InteractionError("该消息有发送中或待核查的回复，请先核查平台结果", 409)
                if source == "automatic":
                    # 认领前重新核验策略，停用、删除或改写后不提交旧话术。
                    current = conn.execute("SELECT data_json FROM interaction_rules WHERE id=?", (rule_id,)).fetchone()
                    rule = json.loads(current[0]) if current else None
                    if not rule or not rule["enabled"] or rule["text"] != content or message["accountId"] not in rule["accountIds"] or \
                            message["platform"] != rule["platform"] or message["kind"] not in rule["kinds"]:
                        return None
                    activated = instant(rule.get("enabledAt"))
                    created = instant(message.get("createdAt"))
                    if not activated or not created or created <= activated:
                        return None
                    if rule["trigger"] == "keyword":
                        body, words = message["text"].casefold(), [word.casefold() for word in rule["keywords"]]
                        matches = any(word in body for word in words) if rule["matchMode"] == "any" else \
                            all(word in body for word in words) if rule["matchMode"] == "all" else body in words
                        if not matches:
                            return None
                    settings = self.store.settings()
                    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
                    sent_count = conn.execute("SELECT COUNT(*) FROM interaction_replies r JOIN interaction_messages m ON m.id=r.message_id "
                                              "WHERE m.account_id=? AND r.source='automatic' AND r.created_at>=?", (account["id"], cutoff)).fetchone()[0]
                    if sent_count >= settings["rateLimitPerHour"]:
                        raise InteractionError("已达到该账号每小时自动回复上限", 429)
                reply_id, stamp = uuid.uuid4().hex, now()
                conn.execute("INSERT INTO interaction_replies(id,message_id,text,idempotency_key,request_hash,source,rule_id,status,created_at,updated_at) "
                             "VALUES(?,?,?,?,?,?,?,'sending',?,?)", (reply_id, message_id, content, key, digest, source, rule_id, stamp, stamp))
            status, error, platform_id = "unknown", "平台未明确确认发送结果，请核查后再操作", None
            try:
                result = adapter.send_reply(account, message, content, key)
                if result.get("confirmed") is True:
                    status, error, platform_id = "sent", None, result.get("platformReplyId")
            except Exception as exc:
                # 只有适配器明确保证未提交的错误才可标记失败；网络中断保持未知。
                code = getattr(exc, "code", "send_unknown")
                if code in {"unsupported", "needs_login", "invalid_request", "not_sent", "rate_limited", "permission_denied",
                            "invalid_reply", "invalid_target", "invalid_cursor", "browser_unavailable", "platform_rejected"}:
                    status = "failed"
                error = str(exc) if hasattr(exc, "code") else "发送过程异常，平台结果需要人工核查"
            with self.store.connect() as conn:
                conn.execute("UPDATE interaction_replies SET status=?,error=?,platform_reply_id=?,updated_at=? WHERE id=?",
                             (status, error, platform_id, now(), reply_id))
                if status == "sent":
                    conn.execute("UPDATE interaction_messages SET handled=1,read=1 WHERE id=?", (message_id,))
                row = conn.execute("SELECT * FROM interaction_replies WHERE id=?", (reply_id,)).fetchone()
                return self._serialize_reply(row)

    def resolve(self, reply_id, data):
        """人工在平台核查后登记结果，不触发第二次发送。"""
        outcome = data.get("outcome")
        if outcome not in {"sent", "not_sent"}:
            raise InteractionError("核查结果必须为已发送或未发送")
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM interaction_replies WHERE id=?", (reply_id,)).fetchone()
            if not row:
                raise InteractionError("回复记录不存在", 404)
            if row["status"] != "unknown":
                raise InteractionError("仅待核查回复可登记平台结果", 409)
            conn.execute("UPDATE interaction_replies SET status=?,platform_reply_id=?,error=NULL,updated_at=? WHERE id=?",
                         ("sent" if outcome == "sent" else "failed", data.get("platformReplyId"), now(), reply_id))
            if outcome == "sent":
                conn.execute("UPDATE interaction_messages SET handled=1,read=1 WHERE id=?", (row["message_id"],))
            return self._serialize_reply(conn.execute("SELECT * FROM interaction_replies WHERE id=?", (reply_id,)).fetchone())

    def ingest(self, account, kind, items, baseline=False):
        """按平台消息 ID 去重，只把后续新到达的入站消息交给策略。"""
        fresh = []
        with self.store.connect() as conn:
            for item in items:
                platform_id = str(item.get("platformMessageId") or "")
                if not platform_id or item.get("kind", kind) not in {"comment", "private", "welcome", "follow"}:
                    raise InteractionError("平台返回的消息标识或类型无效", 502)
                actual_kind = item.get("kind", kind)
                message_id = hashlib.sha256(f"{account['id']}:{account['platform']}:{actual_kind}:{platform_id}".encode()).hexdigest()[:32]
                created = instant(item.get("createdAt"))
                values = (message_id, account["id"], account["platform"], platform_id, actual_kind,
                          item.get("threadId"), item.get("parentId"), item.get("itemId"), item.get("itemTitle"),
                          item.get("authorId"), item.get("authorName") or "未知用户", item.get("authorAvatar"),
                          str(item.get("text") or ""), created.isoformat(timespec="seconds") if created else None,
                          "outbound" if item.get("direction") == "outbound" else "inbound", now(), int(baseline),
                          encode(routing_metadata(item.get("raw"))))
                cursor = conn.execute("INSERT OR IGNORE INTO interaction_messages(id,account_id,platform,platform_message_id,kind,"
                                      "thread_id,parent_id,item_id,item_title,author_id,author_name,author_avatar,text,created_at,direction,first_seen_at,baseline,raw_json) "
                                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                if cursor.rowcount:
                    fresh.append(message_id)
                else:
                    # 已读、处理和首次观测属性不随再次采集回退。
                    conn.execute("UPDATE interaction_messages SET text=?,author_name=?,author_avatar=?,raw_json=? WHERE id=?",
                                 (values[12], values[10], values[11], values[17], message_id))
        return fresh

    def sync_account(self, account_id, kind="all"):
        """采集真实分页，首轮只建立基线，不自动回复历史留言。"""
        account = self._account(account_id)
        cap = next((c for c in self.capability_provider() if c["platform"] == account["platform"]), None)
        # Webhook 接收型私信不能用轮询伪造空列表，能力表单独声明可采集类型。
        kinds = cap.get("fetchableKinds", cap.get("kinds", [])) if cap else []
        if kind != "all":
            kinds = [kind] if kind in kinds else []
        if not kinds:
            raise InteractionError("该平台未接入所选评论或私信采集", 400, "unsupported")
        adapter = self.adapter_factory(account["platform"])
        results = []
        with self._lock(account_id):
            for current_kind in kinds:
                with self.store.connect() as conn:
                    state = conn.execute("SELECT initialized FROM interaction_sync_state WHERE account_id=? AND kind=?",
                                         (account_id, current_kind)).fetchone()
                    baseline = not state or not state[0]
                    conn.execute("INSERT INTO interaction_sync_state(account_id,kind,state,baseline_at) VALUES(?,?,'syncing',?) "
                                 "ON CONFLICT(account_id,kind) DO UPDATE SET state='syncing',error=NULL,"
                                 "baseline_at=COALESCE(baseline_at,excluded.baseline_at)", (account_id, current_kind, now()))
                cursor, seen_cursors, fresh_ids, error, truncated = None, set(), [], None, False
                try:
                    for _ in range(20):
                        page = adapter.fetch(account, cursor=cursor, kind=current_kind, limit=50)
                        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                            raise InteractionError("平台消息响应格式无效", 502)
                        fresh_ids.extend(self.ingest(account, current_kind, page["items"], baseline=baseline))
                        if not page.get("hasMore"):
                            break
                        next_cursor = page.get("cursor")
                        if next_cursor is None or str(next_cursor) in seen_cursors:
                            raise InteractionError("平台分页游标无效，同步已停止", 502)
                        cursor = next_cursor
                        seen_cursors.add(str(cursor))
                    else:
                        truncated = True
                    with self.store.connect() as conn:
                        conn.execute("UPDATE interaction_sync_state SET state='idle',last_synced_at=?,initialized=1,error=NULL "
                                     "WHERE account_id=? AND kind=?", (now(), account_id, current_kind))
                    if not baseline:
                        for message_id in fresh_ids:
                            self.apply_rules(message_id)
                except Exception as exc:
                    error = str(exc) if isinstance(exc, InteractionError) or hasattr(exc, "code") else "平台采集失败，请检查会话或查看平台能力说明"
                    with self.store.connect() as conn:
                        conn.execute("UPDATE interaction_sync_state SET state='idle',error=? WHERE account_id=? AND kind=?",
                                     (error, account_id, current_kind))
                results.append({"accountId": account_id, "kind": current_kind, "status": "failed" if error else "completed",
                                "count": len(fresh_ids), "error": error, "baseline": baseline, "truncated": truncated})
        return results

    def create_sync_job(self, data, background=True):
        """多账号任务持久化并逐个执行，单账号失败不影响其余账号。"""
        ids = self._account_ids(data.get("accountIds"))
        kind = data.get("kind", "all")
        if kind not in {"all", "comment", "private", "welcome", "follow"}:
            raise InteractionError("同步消息类型无效")
        job_id, stamp = uuid.uuid4().hex, now()
        with self.store.connect() as conn:
            conn.execute("INSERT INTO interaction_sync_jobs(id,status,request_json,created_at,updated_at) VALUES(?,'queued',?,?,?)",
                         (job_id, encode({"accountIds": ids, "kind": kind}), stamp, stamp))
        if background:
            threading.Thread(target=self.run_sync_job, args=(job_id,), name="interaction-sync", daemon=True).start()
        else:
            self.run_sync_job(job_id)
        return self.sync_job(job_id)

    def run_sync_job(self, job_id):
        """原子认领队列记录，重复触发执行器也不会重复执行同一任务。"""
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute("UPDATE interaction_sync_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",
                                   (now(), job_id)).rowcount
            if not changed:
                return
            data = json.loads(conn.execute("SELECT request_json FROM interaction_sync_jobs WHERE id=?", (job_id,)).fetchone()[0])
        results = []
        for account_id in data["accountIds"]:
            try:
                results.extend(self.sync_account(account_id, data["kind"]))
            except Exception as exc:
                results.append({"accountId": account_id, "kind": data["kind"], "status": "failed", "count": 0,
                                "error": str(exc) if isinstance(exc, InteractionError) or hasattr(exc, "code") else "账号同步失败"})
            with self.store.connect() as conn:
                conn.execute("UPDATE interaction_sync_jobs SET results_json=?,updated_at=? WHERE id=?", (encode(results), now(), job_id))
        status = "partial" if any(r["status"] == "failed" for r in results) else "completed"
        if results and all(r["status"] == "failed" for r in results):
            status = "failed"
        with self.store.connect() as conn:
            conn.execute("UPDATE interaction_sync_jobs SET status=?,updated_at=? WHERE id=?", (status, now(), job_id))

    def sync_job(self, job_id):
        """轮询结果明确区分受理、执行中和真实采集完成。"""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM interaction_sync_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise InteractionError("同步任务不存在", 404)
        return {"id": row["id"], "status": row["status"], "results": json.loads(row["results_json"]),
                "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    def _account_ids(self, ids, allow_empty=False):
        """账户范围只能是当前管理台已有账号，禁止隐式跨账号操作。"""
        if not isinstance(ids, list) or (not ids and not allow_empty) or len(ids) > 100:
            raise InteractionError("请选择1至100个账号")
        unique = []
        for account_id in ids:
            self._account(account_id)
            if account_id not in unique:
                unique.append(account_id)
        return unique

    def rules(self):
        """按优先级显示规则，一个入站消息最多触发一条回复。"""
        return {"items": sorted(self.store.records("interaction_rules"), key=lambda r: (-r["priority"], r["id"]))}

    def save_rule(self, data, rule_id=None):
        """新建规则默认停用；启用时间是历史消息自动回复的边界。"""
        old = next((r for r in self.rules()["items"] if r["id"] == rule_id), None) if rule_id else None
        if rule_id and not old:
            raise InteractionError("策略不存在", 404)
        merged = {"accountIds": [], "trigger": "keyword", "keywords": [], "matchMode": "any", "priority": 0,
                  "enabled": False, "type": "comment", **(old or {}), **data}
        merged["id"] = rule_id or uuid.uuid4().hex
        merged["name"] = text_value(merged.get("name"), "策略名称", 100)
        merged["text"] = text_value(merged.get("text"), "回复话术", 1000)
        if merged["type"] not in {"comment", "private", "welcome"}:
            raise InteractionError("自动回复类型无效")
        kind = {"comment": "comment", "private": "private", "welcome": "welcome"}[merged["type"]]
        merged["kinds"] = [kind]
        if merged["trigger"] not in {"keyword", "immediate"} or merged["matchMode"] not in {"any", "all", "exact"}:
            raise InteractionError("触发条件或关键词匹配方式无效")
        keywords = merged["keywords"]
        if not isinstance(keywords, list) or len(keywords) > 50:
            raise InteractionError("关键词必须为不超过50项的列表")
        merged["keywords"] = list(dict.fromkeys(text_value(k, "关键词", 100) for k in keywords))
        if merged["trigger"] == "keyword" and not merged["keywords"]:
            raise InteractionError("关键词触发策略至少需要一个关键词")
        if not isinstance(merged["enabled"], bool):
            raise InteractionError("策略启用状态必须为布尔值")
        if isinstance(merged["priority"], bool) or not isinstance(merged["priority"], int) or not -100 <= merged["priority"] <= 100:
            raise InteractionError("策略优先级需在-100至100之间")
        merged["accountIds"] = self._account_ids(merged["accountIds"])
        platforms = {self._account(i)["platform"] for i in merged["accountIds"]}
        if len(platforms) != 1 or merged.get("platform") not in platforms:
            raise InteractionError("策略所选账号必须属于所选平台")
        cap = self._capability(self._account(merged["accountIds"][0]))
        if merged["enabled"] and (not cap or kind not in cap.get("kinds", [])):
            raise InteractionError("该平台未接入此策略需要的消息类型")
        operations = cap.get("operations", {}) if cap else {}
        if merged["enabled"] and isinstance(operations, dict):
            value = operations.get(kind, {}).get("reply") if isinstance(operations.get(kind), dict) else None
            if value not in {True, "available", "unverified"}:
                raise InteractionError("该平台尚未配置此策略需要的回复能力")
        if merged["enabled"]:
            for account_id in merged["accountIds"][1:]:
                other = self._capability(self._account(account_id))
                ops = (other or {}).get("operations", {})
                if isinstance(ops, dict) and ops.get(kind, {}).get("reply") not in {True, "available", "unverified"}:
                    raise InteractionError("所选账号尚未配置此策略需要的回复权限")
        if not old:
            # 创建携带 enabled=true 也只保存停用草稿，启用必须显式后续操作。
            merged["enabled"] = False
        merged["enabledAt"] = now() if merged["enabled"] and (not old or not old["enabled"]) else (old or {}).get("enabledAt")
        merged["updatedAt"] = now()
        return self.store.save_record("interaction_rules", merged)

    def delete_record(self, table, record_id):
        """删除运营配置不会删除消息或发送审计记录。"""
        if table not in {"interaction_rules", "interaction_phrases"}:
            raise InteractionError("无效配置类型")
        with self.store.connect() as conn:
            changed = conn.execute(f"DELETE FROM {table} WHERE id=?", (record_id,)).rowcount
        if not changed:
            raise InteractionError("配置记录不存在", 404)
        return {"id": record_id}

    def save_phrase(self, data, phrase_id=None):
        """话术库只保存文本，复用时仍需人工点击发送或启用策略。"""
        old = next((r for r in self.store.records("interaction_phrases") if r["id"] == phrase_id), None) if phrase_id else None
        if phrase_id and not old:
            raise InteractionError("话术不存在", 404)
        merged = {**(old or {}), **data, "id": phrase_id or uuid.uuid4().hex}
        merged = {"id": merged["id"], "name": text_value(merged.get("name"), "话术名称", 100),
                  "text": text_value(merged.get("text"), "话术内容"),
                  "category": text_value(merged.get("category", "常用话术"), "话术分类", 50)}
        return self.store.save_record("interaction_phrases", merged)

    def _validated_settings(self, data, current):
        """在配置事务内验证字段，保留并发提交的运行状态。"""
        allowed = {"enabled", "intervalSeconds", "accountIds", "rateLimitPerHour", "notifications"}
        if set(data) - allowed:
            raise InteractionError("包含未知的消息设置字段")
        merged = {**current, **data}
        if not isinstance(merged["enabled"], bool):
            raise InteractionError("后台采集状态必须为布尔值")
        for key, minimum, maximum in (("intervalSeconds", 60, 86400), ("rateLimitPerHour", 1, 100)):
            if isinstance(merged[key], bool) or not isinstance(merged[key], int) or not minimum <= merged[key] <= maximum:
                raise InteractionError(f"{key}需在{minimum}至{maximum}之间")
        merged["accountIds"] = self._account_ids(merged["accountIds"], allow_empty=True)
        if merged["enabled"] and not merged["accountIds"]:
            raise InteractionError("启用后台采集前请选择账号")
        notification = merged["notifications"]
        if not isinstance(notification, dict) or any(not isinstance(v, bool) for v in notification.values()) or set(notification) - {"enabled", "browser"}:
            raise InteractionError("提醒配置无效")
        merged["notifications"] = {"enabled": True, "browser": False, **notification}
        return merged

    def update_settings(self, data):
        """后台轮询显式启用，提醒设置只作用于本地工作台。"""
        return self.store.update_settings(lambda current: self._validated_settings(data, current))

    def apply_rules(self, message_id):
        """仅启用后新产生、已确认时间的入站消息可触发一个策略。"""
        message = self.message(message_id)["message"]
        if message["baseline"] or message["direction"] != "inbound" or message["handled"]:
            return None
        timestamp = instant(message.get("createdAt"))
        if not timestamp:
            return None
        with self.store.connect() as conn:
            state = conn.execute("SELECT baseline_at FROM interaction_sync_state WHERE account_id=? AND kind=?",
                                 (message["accountId"], message["kind"])).fetchone()
        # 基线即使因分页截断未扫描完，也不回复首次采集前产生的消息。
        baseline_at = instant(state[0]) if state else None
        if baseline_at and timestamp <= baseline_at:
            return None
        for rule in self.rules()["items"]:
            enabled_at = instant(rule.get("enabledAt"))
            if not rule["enabled"] or not enabled_at or timestamp <= enabled_at:
                continue
            if message["platform"] != rule["platform"] or message["accountId"] not in rule["accountIds"] or message["kind"] not in rule["kinds"]:
                continue
            content = message["text"].casefold()
            words = [word.casefold() for word in rule["keywords"]]
            matched = rule["trigger"] == "immediate"
            if rule["trigger"] == "keyword":
                matched = (any(word in content for word in words) if rule["matchMode"] == "any" else
                           all(word in content for word in words) if rule["matchMode"] == "all" else content in words)
            if matched:
                return self.reply(message_id, {"text": rule["text"], "idempotencyKey": "automatic:" + message_id},
                                  source="automatic", rule_id=rule["id"])
        return None

    def notifications(self):
        """未读/未处理摘要用于页面提醒，不向第三方发送消息。"""
        result = self.messages({"state": "unread", "pageSize": 20})
        return {"items": result["items"], "unreadCount": result["unreadCount"], "unhandledCount": result["unhandledCount"]}

    def webhook(self, account_id, body, signature):
        """平台推送先认证和校验目标账号，去重后才进入消息或策略流程。"""
        if len(body) > 256 * 1024:
            raise InteractionError("平台回调超过大小限制", 413)
        account = self._account(account_id)
        if account["platform"] != "douyin":
            raise InteractionError("平台回调账号不匹配", 400)
        adapter = self.adapter_factory("douyin")
        if not hasattr(adapter, "parse_webhook"):
            raise InteractionError("当前适配器没有启用平台回调", 501)
        result = adapter.parse_webhook(account, body, signature)
        if "challenge" in result:
            return {"challenge": result["challenge"]}
        # 官方回调包含普通私信和进入会话事件，按已验证的事件类型分别入库。
        ids = []
        for kind in ("private", "welcome"):
            items = [item for item in result.get("items", []) if item.get("kind", "private") == kind]
            if items:
                ids.extend(self.ingest(account, kind, items))
        for message_id in ids:
            self.apply_rules(message_id)
        return {"accepted": len(ids)}

    def start(self):
        """执行器可重复启动；只有保存的启用设置才会产生平台采集。"""
        with self._worker_guard:
            if self._worker and self._worker.is_alive():
                return
            self.recover_interrupted()
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, name="interaction-worker", daemon=True)
            self._worker.start()

    def recover_interrupted(self):
        """超时发送转入待核查，不因进程重启重发已可能提交的平台请求。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute("UPDATE interaction_replies SET status='unknown',error='发送执行器中断，请核查平台结果',updated_at=? "
                         "WHERE status='sending' AND updated_at<?", (now(), cutoff))
            conn.execute("UPDATE interaction_sync_jobs SET status='failed',error='采集执行器中断，请重新同步',updated_at=? "
                         "WHERE status IN ('queued','running') AND updated_at<?", (now(), cutoff))

    def stop(self):
        """测试及应用退出时停止后续轮询。"""
        self._stop.set()

    def _run(self):
        """按持久化配置轮询，错误只登记状态，不自动重试未知回复。"""
        next_run = 0.0
        next_recovery = 0.0
        import time
        while not self._stop.wait(2):
            if time.monotonic() >= next_recovery:
                # 刚重启时尚未超时的发送也会在后续转为待核查，避免永远停在发送中。
                self.recover_interrupted()
                next_recovery = time.monotonic() + 60
            settings = self.store.settings()
            if not settings["enabled"] or time.monotonic() < next_run:
                continue
            error = None
            try:
                self.create_sync_job({"accountIds": settings["accountIds"]}, background=False)
            except Exception as exc:
                error = str(exc) if isinstance(exc, InteractionError) else "后台采集执行失败"
            latest = self.store.merge_runtime_state(now(), error)
            next_run = time.monotonic() + latest["intervalSeconds"]
