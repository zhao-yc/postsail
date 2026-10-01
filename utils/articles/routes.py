"""文章 API 与旧文章入口兼容层，视频路由保持原来的执行方式。"""
from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from .model import ArticleError, PLATFORMS, capabilities
from .service import ArticleService
from .store import encode


def register_article_routes(app, configuration):
    """惰性初始化数据库及执行器，测试可注入隔离目录与关闭 worker。"""
    bp = Blueprint("articles", __name__)
    lock = threading.Lock()
    holder = {}

    def service():
        """目录跟随当前项目，公开代码不包含维护者电脑或服务器地址。"""
        with lock:
            if "service" not in holder:
                base = Path(app.config.get("ARTICLE_BASE_DIR", configuration.BASE_DIR))
                holder["service"] = ArticleService(
                    app.config.get("ARTICLE_DB_PATH", base / "db" / "database.db"),
                    app.config.get("ARTICLE_ASSET_DIR", base / "articleData" / "assets"),
                    app.config.get("ARTICLE_COOKIE_DIR", base / "cookiesFile"),
                    app.config.get("ARTICLE_EVIDENCE_DIR", base / "articleData" / "evidence"),
                    runner=app.config.get("ARTICLE_RUNNER"),
                    max_asset_bytes=getattr(configuration, "ARTICLE_ASSET_MAX_BYTES", 20 * 1024 * 1024))
            result = holder["service"]
        if app.config.get("ARTICLE_WORKER_ENABLED", getattr(configuration, "ARTICLE_WORKER_ENABLED", True)):
            result.start()
        return result

    def payload():
        """请求体只有对象有效，给调用者可操作的中文错误。"""
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ArticleError("请求体必须为 JSON 对象")
        return data

    def response(data=None, message="操作完成"):
        """沿用现有管理台 envelope，HTTP 受理不等于平台发布成功。"""
        return jsonify({"code": 200, "msg": message, "data": data})

    @bp.errorhandler(ArticleError)
    def handle_article_error(exc):
        return jsonify({"code": exc.status, "msg": str(exc), "data": None}), exc.status

    @bp.route("/api/article-capabilities")
    def get_capabilities():
        return response({"platforms": capabilities()})

    @bp.route("/api/article-accounts")
    def get_accounts():
        return response(service().accounts())

    @bp.route("/api/article-assets", methods=["POST"])
    def create_asset():
        assets = service().assets
        if "file" in request.files:
            uploaded = request.files["file"]
            result = assets.save(uploaded.stream.read(assets.max_bytes + 1), uploaded.filename or "图片")
        else:
            url = payload().get("url")
            if not isinstance(url, str):
                raise ArticleError("请上传 file 或提供公开图片 url")
            result = assets.import_url(url)
        return response(result, "图片素材已保存")

    @bp.route("/api/article-assets/<asset_id>/content")
    def asset_content(asset_id):
        asset = service().assets.get(asset_id)
        return send_file(asset["path"], mimetype=asset["mime_type"], conditional=True)

    @bp.route("/api/article-assets/<asset_id>", methods=["GET", "DELETE"])
    def asset_item(asset_id):
        assets = service().assets
        if request.method == "DELETE":
            assets.delete(asset_id)
            return response(message="图片已删除")
        return response(assets.serialize(assets.get(asset_id)))

    @bp.route("/api/articles", methods=["GET", "POST"])
    def articles():
        if request.method == "GET":
            return response(service().list_articles())
        return response(service().create_article(payload()), "原稿已保存")

    @bp.route("/api/articles/<article_id>", methods=["GET", "PATCH"])
    def article_item(article_id):
        if request.method == "GET":
            return response(service().get_article(article_id))
        return response(service().update_article(article_id, payload()), "原稿修订已保存")

    @bp.route("/api/articles/<article_id>/publish", methods=["POST"])
    def publish(article_id):
        data = payload()
        if not data.get("idempotency_key"):
            data["idempotency_key"] = request.headers.get("Idempotency-Key")
        return response(service().publish(article_id, data), "任务已受理，请查看各平台实际结果")

    @bp.route("/api/article-publish-batches")
    def batches():
        return response(service().batches(request.args.get("article_id")))

    @bp.route("/api/article-publish-batches/<batch_id>")
    def batch_item(batch_id):
        return response(service().get_batch(batch_id))

    @bp.route("/api/article-publish-tasks/<task_id>/retry", methods=["POST"])
    def retry(task_id):
        return response(service().retry(task_id), "该账号任务已加入重试队列")

    @bp.route("/api/article-publish-tasks/<task_id>/resolve", methods=["POST"])
    def resolve(task_id):
        return response(service().resolve(task_id, payload()), "平台核查结果已记录")

    @bp.route("/api/article-publish-tasks/<task_id>/evidence/<filename>")
    def evidence(task_id, filename):
        if Path(filename).name != filename or Path(filename).suffix not in {".png", ".json", ".txt"}:
            raise ArticleError("证据文件名无效")
        instance = service()
        with instance.store.connect() as conn:
            task = conn.execute("SELECT evidence_json FROM article_publish_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise ArticleError("任务不存在", 404)
        path = (instance.evidence_dir / task_id / filename).resolve()
        if not path.is_relative_to(instance.evidence_dir.resolve()) or not path.is_file():
            raise ArticleError("证据文件不存在", 404)
        return send_file(path, conditional=True)

    def legacy_article(data):
        """旧纯文本文章请求转换到新服务，账号继续用网页账号记录。"""
        instance = service()
        if data.get("enableTimer") or data.get("schedule") or data.get("publish_date"):
            raise ArticleError("首版文章仅支持立即发布，不支持定时")
        key = data["idempotency_key"] if "idempotency_key" in data else (request.headers.get("Idempotency-Key") or uuid.uuid4().hex)
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ArticleError("幂等键必须为非空文本，且不能超过 200 字")
        try:
            account_type = int(data.get("type"))
        except (TypeError, ValueError) as exc:
            raise ArticleError("文章平台类型无效") from exc
        platform = next((name for name, rules in PLATFORMS.items() if rules["account_type"] == account_type), None)
        if not platform:
            raise ArticleError("不支持的文章平台")
        filenames = data.get("accountList", [])
        if not isinstance(filenames, list) or not filenames:
            raise ArticleError("账号列表不能为空")
        with instance.store.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
                raise ArticleError("请先在账号管理中添加并登录平台账号")
            accounts = conn.execute("SELECT id,filePath FROM user_info WHERE type=?", (account_type,)).fetchall()
        account_ids = []
        for value in filenames:
            match = next((row for row in accounts if str(row["filePath"]) == str(value) or row["id"] == value), None)
            if not match:
                raise ArticleError("旧文章请求中的账号不在账号管理记录中")
            account_ids.append(match["id"])
        cover = data.get("thumbnail") or data.get("coverImage") or data.get("cover")
        cover_id = None
        if cover:
            root = Path(configuration.BASE_DIR) / "videoFile"
            path = (root / str(cover)).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ArticleError("封面必须为已上传的项目素材")
            if path.stat().st_size > instance.assets.max_bytes:
                raise ArticleError("封面超过文章图片大小限制")
            cover_id = instance.assets.save(path.read_bytes(), path.name)["id"]
        raw_statements = data.get("workStatements") or data.get("workStatement") or ""
        statement = raw_statements[0] if isinstance(raw_statements, list) and raw_statements else raw_statements
        article_data = {"title": data.get("title"), "content": data.get("articleBody") or data.get("body") or "",
                        "format": "text", "cover_asset_id": cover_id, "tags": data.get("tags") or []}
        # 相同旧原稿复用 ID，旧客户端重复请求也不会新增不同稿件绕过去重。
        identity = hashlib.sha256(encode(article_data).encode()).hexdigest()
        article = instance.create_article(article_data, article_id="legacy-" + identity[:32])
        if request.path == '/postVideoBatch':
            key = hashlib.sha256((key + encode(data)).encode()).hexdigest()
        return instance.publish(article["id"], {
            "revision": article["revision"], "mode": "preview" if data.get("dryRun") else "publish",
            "idempotency_key": key,
            "targets": [{"platform": platform, "account_id": account_id,
                         "overrides": {"options": {"statement": statement, "ai_generated": bool(data.get("aiGenerated"))}}}
                        for account_id in account_ids]})

    app.register_blueprint(bp)
    app.extensions["article_service"] = service
    app.extensions["legacy_article_publish"] = legacy_article
