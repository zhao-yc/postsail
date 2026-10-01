"""分析日报、周报和月报推送；保存配置与外部发送分开执行。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import requests
from flask import Blueprint, jsonify, request

from .service import AnalyticsError, AnalyticsService, Filters, METRIC_LABELS

CHANNELS = {"dingtalk": ("oapi.dingtalk.com", "/robot/send"),
            "feishu": ("open.feishu.cn", "/open-apis/bot/v2/hook/"),
            "wecom": ("qyapi.weixin.qq.com", "/cgi-bin/webhook/send")}


def utc_now():
    """任务审计时间使用 UTC，与报表业务时区分离。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_webhook(channel, url):
    """仅允许官方机器人 HTTPS 入口，禁止任意地址和重定向造成内网请求。"""
    if channel not in CHANNELS or not isinstance(url, str) or len(url) > 2000:
        raise AnalyticsError("推送渠道或机器人地址无效")
    host, path = CHANNELS[channel]
    try:
        parts = urlsplit(url)
        valid_port = parts.port in {None, 443}
    except ValueError:
        raise AnalyticsError("机器人地址格式无效") from None
    if parts.scheme != "https" or parts.hostname != host or not valid_port or parts.username or parts.password or parts.fragment:
        raise AnalyticsError("请使用所选渠道的官方 HTTPS 机器人地址")
    if channel == "feishu":
        if not parts.path.startswith(path) or not re.fullmatch(r"[A-Za-z0-9_-]+", parts.path[len(path):]):
            raise AnalyticsError("飞书机器人地址格式无效")
    else:
        tokens = parse_qs(parts.query).get("access_token" if channel == "dingtalk" else "key", [])
        if parts.path != path or len(tokens) != 1 or not tokens[0].strip():
            raise AnalyticsError("机器人地址需要唯一且非空的授权参数")
    return url


def destination_hash(channel, url):
    """同一机器人按授权标识去重，查询参数排序及无关参数不能绕过待核查锁。"""
    validate_webhook(channel, url)
    parts = urlsplit(url)
    token = parts.path if channel == "feishu" else parse_qs(parts.query)["access_token" if channel == "dingtalk" else "key"][0]
    return hashlib.sha256(json.dumps([channel, parts.hostname, token], ensure_ascii=False).encode()).hexdigest()


def report_range(period, local_today):
    """日报是昨日，周报是前七日，月报是上个完整自然月。"""
    end = local_today - timedelta(days=1)
    if period == "daily":
        return end, end
    if period == "weekly":
        return end - timedelta(days=6), end
    if period == "monthly":
        end = local_today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    raise AnalyticsError("报表类型需为日报、周报或月报")


def deliver_report(channel, url, title, text, secret):
    """一次请求确认机器人响应；连接中断和未知响应绝不自动重发。"""
    validate_webhook(channel, url)
    if channel == "dingtalk":
        from myUtils.dingtalk import build_signed_webhook_url
        url = build_signed_webhook_url(url, secret)
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    elif channel == "wecom":
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
    else:
        payload = {"msg_type": "text", "content": {"text": text}}
        if secret:
            stamp = str(int(time.time()))
            signed = hmac.new(f"{stamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
            payload.update(timestamp=stamp, sign=base64.b64encode(signed).decode())
    try:
        result = requests.post(url, json=payload, timeout=30, allow_redirects=False)
        if not 200 <= result.status_code < 300:
            return "unknown", "机器人未明确确认，请在群内核查报表是否收到"
        body = result.json()
    except (requests.RequestException, ValueError):
        return "unknown", "发送结果待核查，请先检查群内记录，避免重复发送"
    if not isinstance(body, dict):
        return "unknown", "机器人响应格式异常，请核查群内实际结果"
    code = body.get("code", body.get("StatusCode")) if channel == "feishu" else body.get("errcode")
    if isinstance(code, bool) or not isinstance(code, int):
        return "unknown", "机器人没有返回有效确认码，请核查群内实际结果"
    if code == 0:
        return "sent", None
    return "failed", "机器人拒绝报表，请检查机器人关键词、签名及权限配置"


class AnalyticsPushService:
    """按持久化幂等键认领发送任务，默认不进行任何外部通信。"""

    def __init__(self, db_path_provider, configuration, sender=None):
        self.db_path_provider = db_path_provider
        self.configuration = configuration
        self.sender = sender or deliver_report
        self._stop, self._worker = threading.Event(), None
        self._worker_guard = threading.Lock()

    @contextmanager
    def connect(self):
        """推送表独立添加，业务查询继续使用分析服务的快照数据。"""
        conn = sqlite3.connect(self.db_path_provider(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS analytics_push_settings (id INTEGER PRIMARY KEY,value_json TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS analytics_push_records (
            id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
            destination_hash TEXT NOT NULL, channel TEXT NOT NULL, period TEXT NOT NULL,
            status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.commit()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def settings(self, public=True, conn=None):
        """前端只看到脱敏地址；已有服务端钉钉配置可作为默认渠道。"""
        data = {"enabled": False, "channel": "dingtalk", "webhookUrl": "", "secret": "",
                "frequencies": [], "sendTime": "09:00", "utcOffsetMinutes": 480,
                "accountIds": [], "lastRunAt": None, "error": None}
        if conn is None:
            with self.connect() as connection:
                return self.settings(public, connection)
        row = conn.execute("SELECT value_json FROM analytics_push_settings WHERE id=1").fetchone()
        if row:
            data.update(json.loads(row[0]))
        if not data["webhookUrl"]:
            prefix = {"dingtalk": "DINGTALK", "feishu": "FEISHU", "wecom": "WECOM"}[data["channel"]]
            data["webhookUrl"] = getattr(self.configuration, prefix + "_WEBHOOK_URL", "") or ""
            data["secret"] = data["secret"] or (getattr(self.configuration, prefix + "_SECRET", "") or "")
        if not public:
            return data
        try:
            parts = urlsplit(data["webhookUrl"])
        except ValueError:
            parts = urlsplit("")
            data["error"] = "机器人地址格式无效，请重新配置"
        return {key: value for key, value in data.items() if key not in {"webhookUrl", "secret"}} | {
            "hasWebhook": bool(data["webhookUrl"]), "hasSecret": bool(data["secret"]),
            "webhookMasked": f"https://{parts.hostname}/••••" if parts.hostname else ""}

    def _validated_settings(self, data, previous, conn):
        """校验完整配置；调用方持有写事务以防并发配置丢失。"""
        allowed = {"enabled", "channel", "webhookUrl", "secret", "frequencies", "sendTime", "utcOffsetMinutes", "accountIds"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise AnalyticsError("推送设置包含未知字段")
        merged = {**previous, **data}
        # 切换渠道且未提供地址时清空旧渠道授权，不将旧令牌发往另一个服务。
        if merged["channel"] != previous["channel"]:
            merged["webhookUrl"] = data.get("webhookUrl", "")
            merged["secret"] = data.get("secret", "")
        if merged["channel"] not in CHANNELS or not isinstance(merged["enabled"], bool):
            raise AnalyticsError("推送渠道或启用状态无效")
        if merged["webhookUrl"]:
            validate_webhook(merged["channel"], merged["webhookUrl"])
        if not isinstance(merged["secret"], str) or len(merged["secret"]) > 500:
            raise AnalyticsError("机器人签名密钥无效")
        frequencies = merged["frequencies"]
        if not isinstance(frequencies, list) or any(p not in {"daily", "weekly", "monthly"} for p in frequencies):
            raise AnalyticsError("推送频次无效")
        merged["frequencies"] = list(dict.fromkeys(frequencies))
        if not isinstance(merged["sendTime"], str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", merged["sendTime"]):
            raise AnalyticsError("发送时间格式需为 HH:MM")
        offset = merged["utcOffsetMinutes"]
        if isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 840:
            raise AnalyticsError("时区偏移分钟数需在-720至840之间")
        ids = merged["accountIds"]
        if not isinstance(ids, list) or len(ids) > 100:
            raise AnalyticsError("推送账号范围无效")
        for account_id in ids:
            if isinstance(account_id, bool) or not isinstance(account_id, int):
                raise AnalyticsError("推送账号编号无效")
            if not conn.execute("SELECT 1 FROM user_info WHERE id=? AND type BETWEEN 1 AND 9", (account_id,)).fetchone():
                raise AnalyticsError("账号不存在", 404)
        if merged["enabled"] and (not merged["webhookUrl"] or not frequencies or not ids):
            raise AnalyticsError("启用前请配置机器人、推送频次和账号")
        return merged

    def update_settings(self, data):
        """保存不等于测试发送，配置合并与运行状态更新使用同一数据库写锁。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            merged = self._validated_settings(data, self.settings(public=False, conn=conn), conn)
            conn.execute("INSERT INTO analytics_push_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json",
                         (json.dumps(merged, ensure_ascii=False),))
        return self.settings()

    def _report(self, settings, period, account_ids, at):
        """仅汇总被明确选择的账号，不把缺失样本描述为零增长。"""
        start, end = report_range(period, at.astimezone(timezone(timedelta(minutes=settings["utcOffsetMinutes"]))).date())
        target = AnalyticsService(self.db_path_provider())
        snapshots = [target.overview(Filters(start, end, account_id=account_id)) for account_id in account_ids]
        label = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[period]
        title = f"PostSail 数据{label}"
        lines = [f"### {title}", f"统计区间：{start} 至 {end}", f"账号数量：{len(account_ids)}", ""]
        for key in ("publishedCount", "newFollowers", "playCount", "likeCount", "commentCount", "shareCount", "collectCount"):
            values = [snapshot["summary"].get(key) for snapshot in snapshots]
            known = [value for value in values if value is not None]
            value = str(sum(known)) if known else "—（缺少可计算的观测数据）"
            suffix = "（部分账号缺少数据）" if known and len(known) < len(values) else ""
            lines.append(f"{METRIC_LABELS[key]}：{value}{suffix}")
        starts = [s["coverage"].get("intervalStart") for s in snapshots if s["coverage"].get("intervalStart")]
        ends = [s["coverage"].get("intervalEnd") for s in snapshots if s["coverage"].get("intervalEnd")]
        if starts and ends:
            lines.append(f"实际观测跨度：{min(starts)} 至 {max(ends)}")
        lines.extend(["", "口径：仅包含实际采集作品。差值按后一次观测日期归属，包含上次采集以来的变化；"
                      "首次采集是基线。以下不是自然日精确流量，无法还原两次观测间每一天的真实分布。"])
        return title, "\n".join(lines), start, end

    @staticmethod
    def _due_periods(settings, at):
        """以当前持久化时区、时间和频次重新判定到期任务。"""
        if not settings["enabled"]:
            return []
        local = at.astimezone(timezone(timedelta(minutes=settings["utcOffsetMinutes"])))
        if local.strftime("%H:%M") < settings["sendTime"]:
            return []
        return [period for period in settings["frequencies"] if period == "daily" or
                period == "weekly" and local.weekday() == 0 or period == "monthly" and local.day == 1]

    def send(self, data, scheduled=False, at=None):
        """幂等登记先于任何网络操作，未知发送会阻止该目的地重复提交。"""
        at = at or datetime.now(timezone.utc)
        settings = self.settings(public=False)
        if scheduled and (not settings["enabled"] or self._stop.is_set()):
            return None
        if not settings["webhookUrl"]:
            raise AnalyticsError("请先配置报表机器人地址")
        validate_webhook(settings["channel"], settings["webhookUrl"])
        period = data.get("period", "daily")
        if scheduled and period not in self._due_periods(settings, at):
            return None
        ids = data.get("accountIds", settings["accountIds"])
        if not isinstance(ids, list) or not ids or len(ids) > 100:
            raise AnalyticsError("请选择推送账号")
        for account_id in ids:
            if isinstance(account_id, bool) or not isinstance(account_id, int):
                raise AnalyticsError("推送账号编号无效")
        start, end = report_range(period, at.astimezone(timezone(timedelta(minutes=settings["utcOffsetMinutes"]))).date())
        destination = destination_hash(settings["channel"], settings["webhookUrl"])
        key = f"schedule:{period}:{start}:{end}:{destination}" if scheduled else data.get("idempotencyKey")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise AnalyticsError("发送需要不超过200字的非空幂等键")
        digest = hashlib.sha256(json.dumps({"destination": destination, "period": period, "ids": ids,
                                           "start": str(start), "end": str(end)}, sort_keys=True).encode()).hexdigest()
        with self.connect() as conn:
            for account_id in ids:
                if not conn.execute("SELECT 1 FROM user_info WHERE id=? AND type BETWEEN 1 AND 9", (account_id,)).fetchone():
                    raise AnalyticsError("账号不存在", 404)
            previous = conn.execute("SELECT * FROM analytics_push_records WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != digest:
                    raise AnalyticsError("幂等键已用于不同报表", 409)
                return self._record(previous)
        # 同一周期已经发过时直接返回，避免每轮调度重新扫描长期快照。
        title, text, _, _ = self._report(settings, period, list(dict.fromkeys(ids)), at)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # 定时任务在认领前再次检查当前配置，关闭或修改范围后不发送旧报表。
            if scheduled:
                latest = self.settings(public=False, conn=conn)
                if period not in self._due_periods(latest, at) or self._stop.is_set() or any(
                        latest[k] != settings[k] for k in ("channel", "webhookUrl", "secret", "accountIds", "sendTime", "utcOffsetMinutes")):
                    return None
            previous = conn.execute("SELECT * FROM analytics_push_records WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != digest:
                    raise AnalyticsError("幂等键已用于不同报表", 409)
                return self._record(previous)
            if conn.execute("SELECT 1 FROM analytics_push_records WHERE destination_hash=? AND status IN ('sending','unknown')", (destination,)).fetchone():
                raise AnalyticsError("此机器人有发送中或待核查报表，请先核查群内结果", 409)
            identifier, stamp = uuid.uuid4().hex, utc_now()
            conn.execute("INSERT INTO analytics_push_records VALUES(?,?,?,?,?,?,'sending',NULL,?,?)",
                         (identifier, key, digest, destination, settings["channel"], period, stamp, stamp))
        try:
            status, error = self.sender(settings["channel"], settings["webhookUrl"], title, text, settings["secret"])
            if status not in {"sent", "failed", "unknown"}:
                status, error = "unknown", "推送器没有返回可确认的结果，请核查群内报表"
        except Exception:
            status, error = "unknown", "发送过程异常，请核查群内实际结果"
        with self.connect() as conn:
            conn.execute("UPDATE analytics_push_records SET status=?,error=?,updated_at=? WHERE id=?", (status, error, utc_now(), identifier))
            return self._record(conn.execute("SELECT * FROM analytics_push_records WHERE id=?", (identifier,)).fetchone())

    @staticmethod
    def _record(row):
        """公开任务结果不返回机器人授权地址及幂等散列。"""
        return {"id": row["id"], "channel": row["channel"], "period": row["period"], "status": row["status"],
                "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    def records(self):
        """仅查询最近的任务记录，无任何网络动作。"""
        with self.connect() as conn:
            return {"items": [self._record(r) for r in conn.execute("SELECT * FROM analytics_push_records ORDER BY created_at DESC,rowid DESC LIMIT 100")]}

    def resolve(self, identifier, outcome):
        """群内人工核对结果入审计，核对不会自行再次发送。"""
        if outcome not in {"sent", "not_sent"}:
            raise AnalyticsError("核查结果无效")
        with self.connect() as conn:
            changed = conn.execute("UPDATE analytics_push_records SET status=?,error=NULL,updated_at=? WHERE id=? AND status='unknown'",
                                   ("sent" if outcome == "sent" else "failed", utc_now(), identifier)).rowcount
            if not changed:
                raise AnalyticsError("没有此待核查报表", 409)
            return self._record(conn.execute("SELECT * FROM analytics_push_records WHERE id=?", (identifier,)).fetchone())

    def tick(self, at=None):
        """每日、周一、每月一号到达指定时间后发送完整上一周期。"""
        at = at or datetime.now(timezone.utc)
        settings = self.settings(public=False)
        periods = self._due_periods(settings, at)
        results = [self.send({"period": period}, scheduled=True, at=at) for period in periods]
        results = [result for result in results if result is not None]
        if results:
            self.merge_runtime_state(utc_now(), next((r["error"] for r in results if r["error"]), None))
        return results

    def merge_runtime_state(self, last_run_at, error):
        """只在写锁内更新运行字段，保留用户刚修改的频次、账号和关闭状态。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value_json FROM analytics_push_settings WHERE id=1").fetchone()
            if row:
                data = json.loads(row[0])
                data.update(lastRunAt=last_run_at, error=error)
                conn.execute("UPDATE analytics_push_settings SET value_json=? WHERE id=1", (json.dumps(data, ensure_ascii=False),))

    def start(self):
        """启动空闲运行器不意味着启用推送，旧未知任务不自动恢复发送。"""
        with self._worker_guard:
            if self._worker and self._worker.is_alive():
                return
            self.recover_interrupted()
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, name="analytics-push", daemon=True)
            self._worker.start()

    def recover_interrupted(self):
        """定期把超时认领转为待核查，近期中断任务不会永久停在发送中。"""
        with self.connect() as conn:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
            conn.execute("UPDATE analytics_push_records SET status='unknown',error='推送执行器中断，请核查群内结果',updated_at=? "
                         "WHERE status='sending' AND updated_at<?", (utc_now(), cutoff))

    def stop(self):
        """停掉后续调度，已在平台发送中的请求仍需等待明确响应。"""
        self._stop.set()

    def _run(self):
        """后台异常只登记脱敏状态，不重发未知结果。"""
        while not self._stop.wait(30):
            try:
                self.recover_interrupted()
                self.tick()
            except Exception:
                # 真实失败已写任务记录；配置问题记录到设置供界面显示。
                self.merge_runtime_state(utc_now(), "推送未完成，请查看推送记录或核对机器人配置")


def register_analytics_push_routes(app, db_path_provider, configuration):
    """注册配置和显式发送入口，测试可注入不联网的机器人发送器。"""
    bp = Blueprint("analytics_push", __name__, url_prefix="/api/analytics")
    holder = {}
    lock = threading.Lock()

    def service():
        with lock:
            if "service" not in holder:
                holder["service"] = AnalyticsPushService(db_path_provider, configuration, app.config.get("ANALYTICS_PUSH_SENDER"))
            return holder["service"]

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise AnalyticsError("请求体必须为 JSON 对象")
        return data

    def success(data):
        return jsonify({"code": 200, "msg": None, "data": data})

    @bp.errorhandler(AnalyticsError)
    def error(exc):
        return jsonify({"code": exc.code, "msg": str(exc), "data": None}), exc.code

    @bp.route("/push-settings", methods=["GET", "PATCH"])
    def settings():
        result = service().settings() if request.method == "GET" else service().update_settings(body())
        if request.method == "PATCH" and result["enabled"] and app.config.get("ANALYTICS_PUSH_WORKER_ENABLED", getattr(configuration, "ANALYTICS_PUSH_WORKER_ENABLED", True)):
            service().start()
        return success(result)

    @bp.post("/push")
    def push():
        data = body()
        data.setdefault("idempotencyKey", request.headers.get("Idempotency-Key"))
        return success(service().send(data))

    @bp.get("/push-records")
    def records():
        return success(service().records())

    @bp.post("/push-records/<identifier>/resolve")
    def resolve(identifier):
        return success(service().resolve(identifier, body().get("outcome")))

    app.register_blueprint(bp)
    app.extensions["analytics_push_service"] = service
