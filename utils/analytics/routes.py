"""可独立注册与测试的分析 API；刷新采集器由应用显式注入。"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from .service import AnalyticsError, AnalyticsService, Filters, capabilities
from .store import business_now, nullable_count, record_account_snapshot


def register_analytics_routes(app, db_path_provider, account_refresher=None):
    """注册分析入口，不导入主应用，不自行启动浏览器或后台线程。

    account_refresher(account_id, platform, limit) 返回实际采集结果：
    {items: list|None, followerCount: int|None, evidence: list,
     scope: 'partial', warnings: list[str]}。
    items=None 表示没有采集作品；空数组表示确实采集到空作品列表。
    """
    blueprint = Blueprint("analytics", __name__, url_prefix="/api/analytics")

    def service():
        """每次读取当前数据库路径，兼容测试库、个人配置及容器配置。"""
        return AnalyticsService(db_path_provider())

    def success(data):
        return jsonify({"code": 200, "msg": None, "data": data})

    @blueprint.errorhandler(AnalyticsError)
    def invalid(exc):
        return jsonify({"code": exc.code, "msg": str(exc), "data": None}), exc.code

    @blueprint.get("/capabilities")
    def get_capabilities():
        """能力说明与观测口径供前端显示，避免把支持平台误当全量采集。"""
        data = capabilities()
        data["refreshAvailable"] = account_refresher is not None
        return success(data)

    @blueprint.get("/overview")
    def overview():
        return success(service().overview(Filters.from_params(request.args)))

    @blueprint.get("/accounts")
    def accounts():
        return success(service().accounts(Filters.from_params(request.args)))

    @blueprint.get("/works")
    def works():
        return success(service().works(Filters.from_params(request.args)))

    @blueprint.get("/owners")
    def owners():
        return success(service().owners(Filters.from_params(request.args)))

    @blueprint.get("/rankings")
    def rankings():
        return success(service().rankings(Filters.from_params(request.args),
            entity=request.args.get("entity", "accounts"), metric=request.args.get("metric", "playCount")))

    @blueprint.get("/export")
    def export():
        """仅导出筛选后的公共分析字段，文件名使用固定实体和日期。"""
        filters = Filters.from_params(request.args)
        entity = request.args.get("entity", "works")
        content = service().export_csv(filters, entity=entity)
        filename = f"postsail-{entity}-{filters.start.isoformat()}-{filters.end.isoformat()}.csv"
        return Response(content, mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})

    @blueprint.get("/account-settings")
    def settings():
        return success(service().account_settings())

    @blueprint.route("/account-settings", methods=["PUT", "PATCH"])
    def update_settings():
        """负责人和标签由当前数据库账号关联，不允许创建虚构账号。"""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise AnalyticsError("请求体应为 JSON 对象")
        target = service()
        current = target.account(body.get("accountId"))
        return success(target.update_account_settings(current["accountId"],
            body.get("owner", current["owner"]), body.get("tags", current["tags"])))

    @blueprint.post("/accounts/<int:account_id>/refresh")
    def refresh(account_id):
        """先采集后短事务保存；失败不覆盖累计缓存与已知粉丝资料。"""
        target = service()
        account = target.account(account_id)
        if account_refresher is None:
            raise AnalyticsError("当前应用未接入账号数据采集器", 501)
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise AnalyticsError("请求体应为 JSON 对象")
        try:
            limit = int(body.get("limit", 5))
        except (ValueError, TypeError) as exc:
            raise AnalyticsError("采集条数无效") from exc
        if not 1 <= limit <= 20:
            raise AnalyticsError("采集条数需在 1–20 之间")
        try:
            result = account_refresher(account_id, account["platform"], limit)
        except AnalyticsError:
            raise
        except Exception as exc:
            # 已有平台采集错误包含可操作的说明；未知错误避免泄露会话路径。
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise AnalyticsError(exc.message, exc.code) from exc
            app.logger.exception("账号分析采集失败，账号编号 %s", account_id)
            raise AnalyticsError("采集失败，请查看服务日志并确认账号登录状态", 502) from exc
        if not isinstance(result, dict) or result.get("items") is not None and not isinstance(result["items"], list):
            raise AnalyticsError("采集器返回的数据结构无效", 502)
        if result.get("items") is not None and any(not isinstance(item, dict) or not str(item.get("item_id") or "").strip() for item in result["items"]):
            raise AnalyticsError("采集器返回了无效作品", 502)
        follower_count = nullable_count(result.get("followerCount"))
        warnings = result.get("warnings") or []
        if follower_count is None and result.get("followerCount") is not None:
            warnings = [*warnings, "采集的粉丝数不是有效精确数字，未写入指标"]
        synced_at = business_now().isoformat(timespec="microseconds")
        with target.connect() as conn:
            items = result.get("items")
            if items is not None:
                # 复用旧缓存写入的快照 hook，不另记录重复观测；和粉丝资料一次提交。
                from uploader.douyin_uploader.content_stats import replace_account_stats
                replace_account_stats(conn, platform=account["platform"], account_id=account_id,
                                      items=items, synced_at=synced_at, commit=False)
            record_account_snapshot(conn, platform=account["platform"], account_id=account_id,
                synced_at=synced_at, follower_count=follower_count, evidence=result.get("evidence") or [])
        return success({"accountId": account_id, "platform": account["platform"],
                        "lastSyncedAt": synced_at, "itemCount": len(items) if items is not None else None,
                        "followerCount": follower_count, "scope": "partial", "warnings": warnings})

    app.register_blueprint(blueprint)
    return blueprint
