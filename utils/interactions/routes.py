"""消息工作台 API；导入及只读能力查询不启动自动化。"""
from pathlib import Path
import threading

from flask import Blueprint, jsonify, request

from .service import InteractionError, InteractionService


def register_interaction_routes(app, configuration):
    """可注入隔离数据库和 adapter，实际启动时再初始化运行器。"""
    bp = Blueprint("interactions", __name__, url_prefix="/api/interactions")
    holder, lock = {}, threading.Lock()

    def service():
        """惰性创建服务，账号和 Cookie 使用当前项目配置。"""
        with lock:
            if "service" not in holder:
                base = Path(app.config.get("INTERACTION_BASE_DIR", configuration.BASE_DIR))
                holder["service"] = InteractionService(
                    app.config.get("INTERACTION_DB_PATH", base / "db" / "database.db"),
                    app.config.get("INTERACTION_COOKIE_DIR", base / "cookiesFile"),
                    adapter_factory=app.config.get("INTERACTION_ADAPTER_FACTORY"),
                    capability_provider=app.config.get("INTERACTION_CAPABILITIES"))
            return holder["service"]

    def body():
        """禁止数组和无效 JSON 被默认为空对象。"""
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise InteractionError("请求体必须为 JSON 对象")
        return value

    def response(data=None, message="操作完成"):
        """沿用管理台响应格式，发送结果位于数据的 status。"""
        return jsonify({"code": 200, "msg": message, "data": data})

    @bp.errorhandler(InteractionError)
    def error(exc):
        return jsonify({"code": exc.status, "msg": str(exc), "errorCode": exc.code, "data": None}), exc.status

    # 平台认证和能力错误使用明确 HTTP 码，不冒充服务内部故障。
    from .adapters.base import InteractionAdapterError

    @bp.errorhandler(InteractionAdapterError)
    def adapter_error(exc):
        status = 401 if exc.code in {"needs_login", "invalid_signature"} else 403 if exc.code == "permission_denied" else 400 if exc.code in {"unsupported", "invalid_target", "invalid_reply", "invalid_request"} else 502
        return jsonify({"code": status, "msg": str(exc), "errorCode": exc.code, "data": None}), status

    @bp.get("/capabilities")
    def capabilities():
        """适配器能力查询不写库。"""
        provider = app.config.get("INTERACTION_CAPABILITIES")
        if provider is None:
            from .adapters import list_capabilities
            provider = list_capabilities
        return response({"platforms": provider()})

    @bp.get("/accounts")
    def accounts():
        return response(service().accounts())

    @bp.get("/messages")
    def messages():
        return response(service().messages(request.args))

    @bp.get("/messages/<message_id>")
    def message(message_id):
        return response(service().message(message_id))

    @bp.post("/messages/<message_id>/state")
    def mark(message_id):
        return response(service().mark(message_id, body()))

    @bp.post("/messages/<message_id>/reply")
    def reply(message_id):
        data = body()
        data.setdefault("idempotencyKey", request.headers.get("Idempotency-Key"))
        return response(service().reply(message_id, data), "请以回复状态判断平台实际结果")

    @bp.post("/replies/<reply_id>/resolve")
    def resolve(reply_id):
        return response(service().resolve(reply_id, body()), "平台核查结果已登记")

    @bp.post("/sync")
    def sync():
        return response(service().create_sync_job(body(), background=app.config.get("INTERACTION_ASYNC_JOBS", True)), "同步任务已受理")

    @bp.get("/sync-jobs/<job_id>")
    def sync_job(job_id):
        return response(service().sync_job(job_id))

    @bp.route("/rules", methods=["GET", "POST"])
    def rules():
        return response(service().rules() if request.method == "GET" else service().save_rule(body()))

    @bp.route("/rules/<rule_id>", methods=["PATCH", "DELETE"])
    def rule(rule_id):
        return response(service().delete_record("interaction_rules", rule_id) if request.method == "DELETE" else service().save_rule(body(), rule_id))

    @bp.route("/phrases", methods=["GET", "POST"])
    def phrases():
        return response({"items": service().store.records("interaction_phrases")} if request.method == "GET" else service().save_phrase(body()))

    @bp.route("/phrases/<phrase_id>", methods=["PATCH", "DELETE"])
    def phrase(phrase_id):
        return response(service().delete_record("interaction_phrases", phrase_id) if request.method == "DELETE" else service().save_phrase(body(), phrase_id))

    @bp.route("/settings", methods=["GET", "PATCH"])
    def settings():
        result = service().store.settings() if request.method == "GET" else service().update_settings(body())
        if request.method == "PATCH" and result["enabled"] and app.config.get("INTERACTION_WORKER_ENABLED", getattr(configuration, "INTERACTION_WORKER_ENABLED", True)):
            service().start()
        return response(result)

    @bp.get("/notifications")
    def notifications():
        return response(service().notifications())

    @bp.post("/webhooks/douyin/<int:account_id>")
    def douyin_webhook(account_id):
        """遵循平台挑战响应；回调认证失败不会落入消息库。"""
        if request.content_length and request.content_length > 256 * 1024:
            raise InteractionError("平台回调超过大小限制", 413)
        result = service().webhook(account_id, request.get_data(), request.headers.get("X-Douyin-Signature", ""))
        return jsonify(result) if "challenge" in result else jsonify({"code": 0, "message": "success"})

    app.register_blueprint(bp)
    app.extensions["interaction_service"] = service
