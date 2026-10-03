"""独立文章服务：修订、不可变发布快照、幂等任务与安全恢复。"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import threading
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from .assets import ArticleAssets, utc_now
from .model import (ArticleError, PLATFORMS, clean_content, image_references, validate_options,
                    validate_platform_content, validate_platform_cover, option_asset_ids,
                    validate_option_asset, validate_title_characters)
from .store import ArticleStore, encode

BLOCK_DUPLICATES = {"queued", "running", "needs_action", "submitted", "published", "unknown"}


class ResolveImages(HTMLParser):
    """把外链图片和已上传素材统一成受管理的 ID，保留原稿顺序。"""

    def __init__(self, assets):
        super().__init__(convert_charrefs=True)
        self.assets, self.output, self.ids, self.text = assets, [], set(), []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img":
            asset_id, source = values.get("data-asset-id"), values.get("src", "")
            try:
                parts = urlsplit(source)
            except ValueError as exc:
                raise ArticleError("正文图片链接格式无效") from exc
            if not asset_id and parts.path.startswith("/api/article-assets/") and parts.path.endswith("/content"):
                asset_id = parts.path.split("/")[-2]
            if asset_id:
                self.assets.get(asset_id)
            elif parts.scheme in {"http", "https"}:
                asset_id = self.assets.import_url(source)["id"]
            else:
                raise ArticleError("正文图片必须引用已上传的素材或公开图片链接；本地文件请先经 CLI 上传")
            self.ids.add(asset_id)
            values["data-asset-id"] = asset_id
            values["src"] = f"/api/article-assets/{asset_id}/content"
        attributes = "".join(f' {key}="{html.escape(value or "", quote=True)}"' for key, value in values.items())
        self.output.append(f"<{tag}{attributes}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.output.append(f"</{tag}>")

    def handle_data(self, data):
        self.text.append(data)
        self.output.append(html.escape(data, quote=False))


class ArticleService:
    """每个后端实例持有一个服务，SQLite 租约保证文章全局串行执行。"""

    def __init__(self, db_path, asset_dir, cookie_dir, evidence_dir, *, runner=None, max_asset_bytes=20*1024*1024):
        self.store = ArticleStore(Path(db_path))
        self.assets = ArticleAssets(self.store, Path(asset_dir), max_asset_bytes)
        self.cookie_dir, self.evidence_dir = Path(cookie_dir), Path(evidence_dir)
        self.runner = runner
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.wakeup = threading.Event()
        self.thread = None
        self.start_lock = threading.Lock()

    def normalize(self, data, current=None):
        """校验原稿并冻结本地素材引用，网络处理始终在数据库事务之外。"""
        if not isinstance(data, dict):
            raise ArticleError("文章参数必须为 JSON 对象")
        title = data.get("title", current["title"] if current else "")
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ArticleError("原稿标题不能为空，且不能超过 300 字")
        content = data.get("content", current["content_html"] if current else "")
        parser = ResolveImages(self.assets)
        parser.feed(clean_content(content, data.get("format", "html")))
        if not "".join(parser.text).strip() and not parser.ids:
            raise ArticleError("文章正文不能为空；空段落不算正文")
        tags = data.get("tags", current["tags"] if current else [])
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
            raise ArticleError("话题必须为字符串数组，最多 20 个，每项不超过 100 字")
        defaults = data.get("platform_options", current["platform_options"] if current else {})
        if not isinstance(defaults, dict) or any(key not in PLATFORMS for key in defaults):
            raise ArticleError("平台默认配置必须以支持的平台名称为键")
        cover = data.get("cover_asset_id", current["cover_asset_id"] if current else None) or None
        if cover is not None and not isinstance(cover, str):
            raise ArticleError("封面必须引用已上传的素材 ID")
        if cover:
            self.assets.get(cover)
            parser.ids.add(cover)
        for platform, default in defaults.items():
            if not isinstance(default, dict):
                raise ArticleError("平台覆盖项必须为 JSON 对象")
            if not isinstance(default.get("options", {}), dict):
                raise ArticleError("平台声明 options 必须为对象")
            if default.get("cover_asset_id"):
                self.assets.get(default["cover_asset_id"])
                parser.ids.add(default["cover_asset_id"])
            for asset_id in option_asset_ids(platform, default.get("options", {})).values():
                self.assets.get(asset_id)
                parser.ids.add(asset_id)
        return {"title": title.strip(), "content_html": "".join(parser.output), "cover_asset_id": cover,
                "tags": tags, "platform_options": defaults}, parser.ids

    def create_article(self, data, *, article_id=None):
        """保存独立原稿，不调用官网接口，也不创建发布任务。"""
        article, refs = self.normalize(data)
        article_id, now = article_id or uuid.uuid4().hex, utc_now()
        with self.store.connect(write=True) as conn:
            existing = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
            if existing:
                stored = self.article(existing)
                # 兼容入口按内容复用 ID；不能悄悄改用网页编辑后的新修订。
                if stored["revision"] != 1 or any(stored[key] != value for key, value in article.items()):
                    raise ArticleError("兼容入口的原稿已被修改，请从文章管理或 article CLI 读取最新修订后发布", 409)
                return stored
            conn.execute("INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)",
                         (article_id, article["title"], article["content_html"], 1, article["cover_asset_id"],
                          encode(article["tags"]), encode(article["platform_options"]), now, now))
            self.store.refs(conn, "article", article_id, refs)
        return self.get_article(article_id)

    @staticmethod
    def article(row):
        """返回公共文章字段，不暴露 SQLite 内部 JSON 列。"""
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json"))
        result["platform_options"] = json.loads(result.pop("platform_options_json"))
        return result

    def get_article(self, article_id):
        """读取一个持久化原稿。"""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            raise ArticleError("文章不存在", 404)
        return self.article(row)

    def list_articles(self):
        """最新修改的文章优先展示。"""
        with self.store.connect() as conn:
            return [self.article(row) for row in conn.execute("SELECT * FROM articles ORDER BY updated_at DESC LIMIT 500")]

    def update_article(self, article_id, data):
        """乐观锁避免网页和智能体相互覆盖；旧发布快照不会被修改。"""
        current = self.get_article(article_id)
        if not isinstance(data, dict):
            raise ArticleError("文章参数必须为 JSON 对象")
        revision = data.get("expected_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision != current["revision"]:
            raise ArticleError("文章已被修改，请重新读取最新修订后保存", 409)
        article, refs = self.normalize(data, current)
        with self.store.connect(write=True) as conn:
            changed = conn.execute("""UPDATE articles SET title=?,content_html=?,cover_asset_id=?,tags_json=?,
                platform_options_json=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?""",
                (article["title"], article["content_html"], article["cover_asset_id"], encode(article["tags"]),
                 encode(article["platform_options"]), utc_now(), article_id, current["revision"]))
            if changed.rowcount != 1:
                raise ArticleError("文章修订冲突，请重新读取", 409)
            self.store.refs(conn, "article", article_id, refs)
        return self.get_article(article_id)

    def accounts(self):
        """文章 CLI 与网页共用账号记录，不输出 Cookie 路径和内容。"""
        with self.store.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
                return []
            rows = conn.execute("SELECT id,type,userName,status FROM user_info ORDER BY id").fetchall()
        names = {rules["account_type"]: platform for platform, rules in PLATFORMS.items()}
        return [{"id": row["id"], "platform": names[row["type"]], "user_name": row["userName"], "status": row["status"]}
                for row in rows if row["type"] in names]

    def account_file(self, account_id, platform):
        """只能使用该平台登记的网页账号，并限定在项目 Cookie 目录内。"""
        with self.store.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
                raise ArticleError("请先在账号管理中添加并登录平台账号")
            row = conn.execute("SELECT * FROM user_info WHERE id=?", (account_id,)).fetchone()
        if not row or row["type"] != PLATFORMS[platform]["account_type"]:
            raise ArticleError("账号不存在或与所选平台不匹配")
        path = (self.cookie_dir / row["filePath"]).resolve()
        if not path.is_relative_to(self.cookie_dir.resolve()) or not path.is_file():
            raise ArticleError("账号会话文件不可用，请在账号管理中重新登录")
        return path

    def snapshot(self, article, target, mode):
        """原稿默认项与单账号覆盖项合并，保留独立声明及封面。"""
        platform = target.get("platform")
        if platform not in PLATFORMS:
            raise ArticleError("不支持的文章平台")
        if PLATFORMS[platform].get("available") is False:
            raise ArticleError(PLATFORMS[platform]["reason"])
        defaults = article["platform_options"].get(platform, {})
        overrides = target.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ArticleError("平台覆盖项必须为对象")
        effective = {**defaults, **overrides}
        if not isinstance(defaults.get("options", {}), dict) or not isinstance(overrides.get("options", {}), dict):
            raise ArticleError("平台声明 options 必须为对象")
        options = {**defaults.get("options", {}), **overrides.get("options", {})}
        if "ai_generated" in options and not isinstance(options["ai_generated"], bool):
            raise ArticleError("AI 内容声明必须为布尔值")
        if any(config.get(field) for config in (effective, options) for field in ("schedule", "publish_date", "enableTimer")):
            raise ArticleError("首版文章仅支持立即发布，不支持定时")
        title = effective.get("title") or article["title"]
        if not isinstance(title, str):
            raise ArticleError("平台标题必须为文本")
        rules = PLATFORMS[platform]
        if not rules["title_min"] <= len(title.strip()) <= rules["title_max"]:
            raise ArticleError(f"{rules['label']}标题需 {rules['title_min']}–{rules['title_max']} 字，请设置该平台标题")
        validate_title_characters(platform, title)
        cover = effective.get("cover_asset_id") or article["cover_asset_id"]
        if rules.get("cover_supported") is False:
            if effective.get("cover_asset_id"):
                raise ArticleError(f"{rules['label']}文章不支持单独设置封面")
            cover = None
        if rules["cover_required"] and not cover:
            raise ArticleError(f"{rules['label']}必须设置封面")
        if cover:
            asset = self.assets.get(cover)
            if asset["size"] > rules["cover_max_bytes"]:
                raise ArticleError(f"{rules['label']}封面超过大小限制")
            if asset["width"] <= rules["cover_min_width"] or asset["height"] <= rules["cover_min_height"]:
                raise ArticleError(f"{rules['label']}封面尺寸必须大于 {rules['cover_min_width']}×{rules['cover_min_height']}")
            validate_platform_cover(platform, asset)
            if platform == "jingdong":
                images = image_references(article["content_html"])
                first_id = images[0].get("data-asset-id") if images else None
                validate_platform_cover(platform, asset, self.assets.get(first_id) if first_id else None)
        validate_options(platform, options)
        asset_fields = {field["name"]: field for field in rules["option_fields"] if field["type"] == "asset"}
        for name, asset_id in option_asset_ids(platform, options).items():
            validate_option_asset(asset_fields[name], self.assets.get(asset_id))
        tags = effective.get("tags")
        if tags is None:
            tags = [] if rules.get("tags_supported") is False else article["tags"]
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
            raise ArticleError("平台话题必须为文本数组，最多 20 个，每项不超过 100 字")
        validate_platform_content(platform, article["content_html"], tags)
        return {"platform": platform, "title": title.strip(), "content_html": article["content_html"],
                "cover_asset_id": cover, "tags": tags, "options": options, "mode": mode}

    def publish(self, article_id, data):
        """一个原稿修订形成一个批次，每个目标账号各自校验和执行。"""
        if not isinstance(data, dict):
            raise ArticleError("发布参数必须为 JSON 对象")
        if data.get("schedule") or data.get("publish_date") or data.get("enableTimer"):
            raise ArticleError("首版文章仅支持立即发布，不支持定时")
        mode = data.get("mode", "publish")
        targets = data.get("targets")
        key = data.get("idempotency_key")
        if not isinstance(mode, str) or mode not in {"publish", "preview"}:
            raise ArticleError("发布模式必须为 publish 或 preview")
        if not isinstance(targets, list) or not targets or len(targets) > 100 or any(not isinstance(t, dict) for t in targets):
            raise ArticleError("发布目标必须为非空数组，最多 100 个")
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ArticleError("发布请求必须提供 idempotency_key（最多 200 字）")
        article = self.get_article(article_id)
        revision = data.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ArticleError("发布请求必须提供正整数 revision")
        request_hash = hashlib.sha256(encode({"article_id": article_id, "revision": revision,
                                            "mode": mode, "targets": targets}).encode()).hexdigest()
        with self.store.connect(write=True) as conn:
            existing = conn.execute("SELECT * FROM article_publish_batches WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ArticleError("幂等键已用于不同请求", 409)
                batch_id = existing["id"]
            else:
                if revision != article["revision"]:
                    raise ArticleError("文章修订不匹配，请重新读取后发布", 409)
                # 防止获取原稿后恰好发生并发编辑。
                live = conn.execute("SELECT revision FROM articles WHERE id=?", (article_id,)).fetchone()
                if live["revision"] != revision:
                    raise ArticleError("文章已更新，请重新读取后发布", 409)
                batch_id, now = uuid.uuid4().hex, utc_now()
                conn.execute("INSERT INTO article_publish_batches VALUES (?,?,?,?,?,?,?)",
                             (batch_id, article_id, revision, mode, key, request_hash, now))
                seen = set()
                for target in targets:
                    platform, account_id = target.get("platform"), target.get("account_id")
                    if (not isinstance(platform, str) or platform not in PLATFORMS or
                            not isinstance(account_id, int) or isinstance(account_id, bool) or account_id < 1):
                        raise ArticleError("每个目标必须提供支持的平台和正整数 account_id")
                    if (platform, account_id) in seen:
                        raise ArticleError("同一批次不能重复选择同一账号")
                    seen.add((platform, account_id))
                    task_id, status, message = uuid.uuid4().hex, "queued", "等待执行"
                    snapshot = {"platform": platform, "mode": mode, "title": article["title"],
                                "content_html": article["content_html"], "cover_asset_id": article["cover_asset_id"],
                                "options": {}, "tags": article["tags"]}
                    try:
                        snapshot = self.snapshot(article, target, mode)
                        self.account_file(account_id, platform)
                    except ArticleError as exc:
                        status, message = "failed", str(exc)
                    if mode == "publish":
                        duplicates = conn.execute("""SELECT status FROM article_publish_tasks WHERE article_id=? AND revision=?
                            AND account_id=? AND platform=? AND mode='publish'""", (article_id, revision, account_id, platform))
                        if any(row["status"] in BLOCK_DUPLICATES for row in duplicates):
                            raise ArticleError("该文章修订在所选账号已有发布或待确认任务，请查看原任务", 409)
                    conn.execute("""INSERT INTO article_publish_tasks
                        (id,batch_id,article_id,revision,platform,account_id,mode,snapshot_json,status,stage,message,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (task_id, batch_id, article_id, revision, platform, account_id, mode,
                         encode(snapshot), status, "validation" if status == "failed" else "queued", message, now, now))
                    refs = [img.get("data-asset-id") for img in image_references(snapshot["content_html"])]
                    refs.extend(option_asset_ids(platform, snapshot["options"]).values())
                    self.store.refs(conn, "task", task_id, refs + [snapshot.get("cover_asset_id")])
        self.wakeup.set()
        return self.get_batch(batch_id)

    @staticmethod
    def task(row):
        """任务只公开进度与证据，Cookie 和内部快照不会进入 API 响应。"""
        result = dict(row)
        result.pop("snapshot_json", None)
        result["evidence"] = [f"/api/article-publish-tasks/{row['id']}/evidence/{Path(name).name}"
                              for name in json.loads(result.pop("evidence_json"))]
        result["retry_allowed"] = row["status"] in {"failed", "needs_action"} and not row["submit_started"] and row["stage"] != "validation"
        return result

    def get_batch(self, batch_id):
        """一个批次中账号任务独立，受理和公开发表分别展示。"""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM article_publish_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                raise ArticleError("发布批次不存在", 404)
            result = dict(row)
            result.pop("request_hash")
            result["tasks"] = [self.task(task) for task in conn.execute(
                "SELECT * FROM article_publish_tasks WHERE batch_id=? ORDER BY created_at,id", (batch_id,))]
        return result

    def batches(self, article_id=None):
        """按文章过滤持久化记录，网页刷新后可恢复查询。"""
        with self.store.connect() as conn:
            rows = conn.execute("SELECT id FROM article_publish_batches WHERE (? IS NULL OR article_id=?) ORDER BY created_at DESC LIMIT 100",
                                (article_id, article_id)).fetchall()
        return [self.get_batch(row["id"]) for row in rows]

    def retry(self, task_id):
        """只重试确定尚未提交的账号；原快照不能被新稿件替换。"""
        with self.store.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM article_publish_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ArticleError("任务不存在", 404)
            if not self.task(row)["retry_allowed"]:
                raise ArticleError("该任务不能重试；结果待确认时须先核查平台", 409)
            if row["mode"] == "publish":
                others = conn.execute("""SELECT status FROM article_publish_tasks WHERE id<>? AND article_id=?
                    AND revision=? AND account_id=? AND platform=? AND mode='publish'""",
                    (task_id, row["article_id"], row["revision"], row["account_id"], row["platform"]))
                if any(other["status"] in BLOCK_DUPLICATES for other in others):
                    raise ArticleError("该账号另有发布或待确认任务，禁止重复重试", 409)
            conn.execute("UPDATE article_publish_tasks SET status='queued',stage='queued',message='等待重试',updated_at=? WHERE id=?",
                         (utc_now(), task_id))
            batch_id = row["batch_id"]
        self.wakeup.set()
        return self.get_batch(batch_id)

    def resolve(self, task_id, data):
        """人工核查未知结果，或凭文章链接确认平台已受理任务公开发表。"""
        if not isinstance(data, dict):
            raise ArticleError("核查参数必须为 JSON 对象")
        resolution = data.get("resolution")
        if not isinstance(resolution, str) or resolution not in {"not_published", "submitted", "published"}:
            raise ArticleError("核查结果必须为 not_published、submitted 或 published")
        note = data.get("note", "")
        if not isinstance(note, str) or not note.strip():
            raise ArticleError("请填写平台核查说明")
        url = data.get("platform_url", "")
        try:
            parts = urlsplit(url) if isinstance(url, str) else None
            if parts is None or (url and (parts.scheme not in {"http", "https"} or not parts.hostname)):
                raise ValueError("链接无效")
        except ValueError as exc:
            raise ArticleError("平台链接必须为完整 HTTP/HTTPS 地址") from exc
        with self.store.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM article_publish_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ArticleError("任务不存在", 404)
            if row["status"] == "submitted":
                # 平台已经受理，人工核查只能确认发表，不能降级后重新发送。
                if resolution != "published":
                    raise ArticleError("平台已受理的任务只能确认已发表，不能降级或重试", 409)
                if not url:
                    raise ArticleError("确认已发表须提供完整 HTTP/HTTPS 平台文章链接")
                submit_started = row["submit_started"]
            elif row["status"] == "unknown":
                # 保留未知结果的既有契约：确认未发表后才能安全重试。
                submit_started = 0 if resolution == "not_published" else 1
            else:
                raise ArticleError("只有结果待确认或平台已受理的任务可以人工核查", 409)
            status = "failed" if resolution == "not_published" else resolution
            conn.execute("""UPDATE article_publish_tasks SET status=?,stage='resolved',submit_started=?,message=?,
                platform_url=?,platform_status='人工核查',updated_at=? WHERE id=?""",
                (status, submit_started, "人工核查：" + note, url, utc_now(), task_id))
            batch_id = row["batch_id"]
        return self.get_batch(batch_id)

    def start(self):
        """按需启动执行器，避免导入模块时创建后台线程。"""
        with self.start_lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, daemon=True, name="omnipost-article-worker")
            self.thread.start()

    def acquire(self):
        """过期租约才能接管；接管前根据提交阶段恢复上个进程的任务。"""
        now = time.time()
        with self.store.connect(write=True) as conn:
            lease = conn.execute("SELECT * FROM article_worker_lease WHERE id=1").fetchone()
            if lease and lease["owner"] != self.owner and lease["expires_at"] > now:
                return False
            new_owner = not lease or lease["owner"] != self.owner or lease["expires_at"] <= now
            conn.execute("INSERT OR REPLACE INTO article_worker_lease VALUES (1,?,?)", (self.owner, now + 30))
            if new_owner:
                conn.execute("""UPDATE article_publish_tasks SET status=CASE WHEN submit_started=1 THEN 'unknown' ELSE 'failed' END,
                    message=CASE WHEN submit_started=1 THEN '服务中断，提交结果待核查' ELSE '服务中断，可安全重试' END,
                    updated_at=? WHERE status='running'""", (utc_now(),))
        return True

    def owns_lease(self, conn):
        """提交前及结果写回均检查租约，防止旧进程继续操作。"""
        row = conn.execute("SELECT * FROM article_worker_lease WHERE id=1").fetchone()
        return bool(row and row["owner"] == self.owner and row["expires_at"] > time.time())

    def heartbeat(self):
        """浏览器操作期间续租；失去租约后不再重新获得执行权。"""
        while not self.stop_event.wait(5):
            try:
                with self.store.connect(write=True) as conn:
                    now = time.time()
                    conn.execute("UPDATE article_worker_lease SET expires_at=? WHERE id=1 AND owner=? AND expires_at>?",
                                 (now + 30, self.owner, now))
            except Exception:
                # 短暂锁等待由提交前租约检查兜底。
                continue

    def run_next(self):
        """原子领取一个目标，浏览器异常按是否开始提交决定能否重试。"""
        with self.store.connect(write=True) as conn:
            if not self.owns_lease(conn):
                return False
            row = conn.execute("SELECT * FROM article_publish_tasks WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return False
            task = dict(row)
            conn.execute("""UPDATE article_publish_tasks SET status='running',stage='preparing',attempts=attempts+1,
                message='准备文章与平台页面',updated_at=? WHERE id=?""", (utc_now(), task["id"]))
        snapshot = json.loads(task["snapshot_json"])
        directory = self.evidence_dir / task["id"]
        directory.mkdir(parents=True, exist_ok=True)

        def on_submit():
            """只有持有租约且任务仍在准备时才能开始一次提交。"""
            if task["mode"] != "publish":
                raise ArticleError("预览任务禁止进入正式提交阶段")
            with self.store.connect(write=True) as conn:
                if not self.owns_lease(conn):
                    raise ArticleError("执行器租约已失效，停止提交")
                updated = conn.execute("""UPDATE article_publish_tasks SET submit_started=1,stage='submitting',
                    message='正在提交，尚未确认平台结果',updated_at=? WHERE id=? AND status='running' AND submit_started=0""",
                    (utc_now(), task["id"]))
                if updated.rowcount != 1:
                    raise ArticleError("该任务已开始提交，禁止重复点击")

        try:
            asset_ids = {image.get("data-asset-id") for image in image_references(snapshot["content_html"])}
            if snapshot.get("cover_asset_id"):
                asset_ids.add(snapshot["cover_asset_id"])
            asset_ids.update(option_asset_ids(snapshot["platform"], snapshot.get("options", {})).values())
            assets = {asset_id: self.assets.get(asset_id) for asset_id in asset_ids if asset_id}
            runner = self.runner
            if runner is None:
                from .adapter import run_article_task
                runner = run_article_task
            result = runner(snapshot, self.account_file(task["account_id"], task["platform"]), assets, on_submit, directory)
            if not isinstance(result, dict) or result.get("status") not in {
                "previewed", "submitted", "published", "needs_action", "unknown", "failed"}:
                raise ArticleError("平台适配器未返回有效结果")
        except Exception as exc:
            result = {"status": "failed", "message": str(exc)}
        with self.store.connect(write=True) as conn:
            if not self.owns_lease(conn):
                return True
            current = conn.execute("SELECT * FROM article_publish_tasks WHERE id=?", (task["id"],)).fetchone()
            if current["submit_started"] and result["status"] in {"failed", "needs_action", "previewed"}:
                result["status"] = "unknown"
            if result["status"] in {"published", "submitted"} and not current["submit_started"]:
                result = {"status": "failed", "message": "适配器未记录提交阶段，拒绝将任务标为成功"}
            evidence = [Path(item).name for item in (result.get("evidence") or [])]
            conn.execute("""UPDATE article_publish_tasks SET status=?,stage='finished',message=?,platform_id=?,platform_url=?,
                platform_status=?,evidence_json=?,prepared_html=?,updated_at=? WHERE id=?""",
                (result["status"], result.get("message") or "", result.get("platform_id") or "", result.get("platform_url") or "",
                 result.get("platform_status") or "", encode(evidence), result.get("prepared_html") or "", utc_now(), task["id"]))
        (directory / "result.json").write_text(encode({**result, "task_id": task["id"]}), encoding="utf-8")
        return True

    def _loop(self):
        """单执行器轮询持久化队列；一个目标失败不停止其他目标。"""
        threading.Thread(target=self.heartbeat, daemon=True, name="article-lease-heartbeat").start()
        while not self.stop_event.is_set():
            try:
                if self.acquire() and self.run_next():
                    continue
            except Exception:
                # 队列内部异常也要落库，不能留下被心跳永久续租的 running 任务。
                logging.exception("文章执行器异常，正在按提交阶段结束当前任务")
                try:
                    with self.store.connect(write=True) as conn:
                        if self.owns_lease(conn):
                            conn.execute("""UPDATE article_publish_tasks SET
                                status=CASE WHEN submit_started=1 THEN 'unknown' ELSE 'failed' END,
                                stage='finished',message='执行器异常；请查看日志，提交后的结果须核查平台',updated_at=?
                                WHERE status='running'""", (utc_now(),))
                except Exception:
                    logging.exception("文章任务恢复写入失败，等待租约恢复")
            self.wakeup.wait(1)
            self.wakeup.clear()
