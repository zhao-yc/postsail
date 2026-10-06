"""跨原稿查询任务和持久化异常提醒；查询与已读操作都不会提交平台。"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .assets import utc_now
from .model import ArticleError
from .platforms import PLATFORMS

TASK_STATUSES = {"scheduled", "queued", "running", "needs_action", "previewed", "submitted",
                 "published", "failed", "unknown", "cancelled"}
ATTENTION_STATUSES = {"failed", "needs_action", "unknown"}


def positive_integer(value, name, maximum=2147483647):
    if isinstance(value, bool) or len(str(value)) > 19 or not re.fullmatch(r"[0-9]+", str(value)):
        raise ArticleError(f"{name} 必须为正整数")
    number = int(value)
    if not 1 <= number <= maximum:
        raise ArticleError(f"{name} 必须为 1–{maximum}")
    return number


def query_time(value, name):
    if not isinstance(value, str):
        raise ArticleError(f"{name} 必须为包含 UTC 偏移的日期时间")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("missing offset")
        return date.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError) as exc:
        raise ArticleError(f"{name} 必须为包含 UTC 偏移的有效日期时间") from exc


class TaskCenterMixin:
    def _center_items(self, conn, rows):
        accounts = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info'").fetchone():
            accounts = {row["id"]: row["userName"] for row in conn.execute("SELECT id,userName FROM user_info")}
        notices = {}
        if rows:
            placeholders = ",".join("?" for _ in rows)
            notices = {row["task_id"]: row["id"] for row in conn.execute(
                f"SELECT task_id,id FROM article_task_notifications WHERE read_at IS NULL AND resolved_at IS NULL AND task_id IN ({placeholders})",
                [row["id"] for row in rows])}
        return [{**{key: value for key, value in self.task(row).items() if key != "prepared_html"},
                 "title": row["snapshot_title"], "platform_label": PLATFORMS.get(row["platform"], {}).get("label", row["platform"]),
                 "account_name": accounts.get(row["account_id"], f"已移除账号 #{row['account_id']}"),
                 "account_exists": row["account_id"] in accounts,
                 "unread_notification_id": notices.get(row["id"])} for row in rows]

    def get_task(self, task_id):
        with self.store.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM article_publish_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ArticleError("任务不存在", 404)
            return self._center_items(conn, [row])[0]

    def all_tasks(self, filters):
        """分页按最近变更排序；统计沿用其他筛选条件但不受状态筛选影响。"""
        page = positive_integer(filters.get("page", 1), "page")
        size = positive_integer(filters.get("page_size", 20), "page_size", 100)
        status = filters.get("status", "")
        platform = filters.get("platform", "")
        mode = filters.get("mode", "")
        if not isinstance(status, str) or status not in TASK_STATUSES | {"", "attention", "pending"}:
            raise ArticleError("任务状态筛选无效")
        if not isinstance(platform, str) or (platform and platform not in PLATFORMS):
            raise ArticleError("任务平台筛选无效")
        if not isinstance(mode, str) or mode not in {"", "publish", "preview"}:
            raise ArticleError("任务模式筛选无效")
        clauses, params = [], []
        for field, value in (("platform", platform), ("mode", mode)):
            if value:
                clauses.append(f"{field}=?")
                params.append(value)
        unread = filters.get("unread", "")
        if not isinstance(unread, str) or unread not in {"", "0", "1"}:
            raise ArticleError("unread 必须为 0 或 1")
        if unread == "1":
            clauses.append("EXISTS (SELECT 1 FROM article_task_notifications n WHERE n.task_id=article_publish_tasks.id AND n.read_at IS NULL AND n.resolved_at IS NULL)")
        if filters.get("account_id") not in (None, ""):
            clauses.append("account_id=?")
            params.append(positive_integer(filters["account_id"], "account_id"))
        query = filters.get("q", "")
        if not isinstance(query, str) or len(query) > 200:
            raise ArticleError("标题搜索不能超过 200 字")
        if query.strip():
            clauses.append("snapshot_title LIKE ? ESCAPE '\\'")
            params.append("%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        dates = {}
        for field, operator in (("created_from", ">="), ("created_before", "<")):
            if filters.get(field):
                dates[field] = query_time(filters[field], field)
                # 历史记录可能没有六位微秒，用 SQLite 日期运算统一精度。
                clauses.append(f"julianday(created_at) {operator} julianday(?)")
                params.append(dates[field])
        if len(dates) == 2 and dates["created_from"] >= dates["created_before"]:
            raise ArticleError("创建时间范围的结束必须晚于开始")
        where = " AND ".join(clauses) or "1=1"
        with self.store.connect() as conn:
            conn.execute("BEGIN")
            counts = {row["status"]: row["count"] for row in conn.execute(
                f"SELECT status,COUNT(*) AS count FROM article_publish_tasks WHERE {where} GROUP BY status", params)}
            summary = {"total": sum(counts.values()), "attention": sum(counts.get(value, 0) for value in ATTENTION_STATUSES),
                       "pending": counts.get("queued", 0) + counts.get("scheduled", 0),
                       "running": counts.get("running", 0), "statuses": counts}
            if status == "attention":
                where += " AND status IN ('failed','needs_action','unknown')"
            elif status == "pending":
                where += " AND status IN ('queued','scheduled')"
            elif status:
                where += " AND status=?"
                params.append(status)
            total = conn.execute(f"SELECT COUNT(*) FROM article_publish_tasks WHERE {where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT * FROM article_publish_tasks WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                                [*params, size, (page - 1) * size]).fetchall()
            items = self._center_items(conn, rows)
        return {"items": items, "total": total, "page": page, "page_size": size, "summary": summary}

    def task_notifications(self, page=1, page_size=20):
        page = positive_integer(page, "page")
        size = positive_integer(page_size, "page_size", 100)
        with self.store.connect() as conn:
            conn.execute("BEGIN")
            unread = conn.execute("SELECT COUNT(*) FROM article_task_notifications WHERE read_at IS NULL AND resolved_at IS NULL").fetchone()[0]
            latest = conn.execute("SELECT COALESCE(MAX(id),0) FROM article_task_notifications").fetchone()[0]
            rows = conn.execute("""SELECT n.id AS notification_id,n.created_at AS notification_created_at,
                n.message AS notification_message,t.* FROM article_task_notifications n
                JOIN article_publish_tasks t ON t.id=n.task_id
                WHERE n.read_at IS NULL AND n.resolved_at IS NULL ORDER BY n.id DESC LIMIT ? OFFSET ?""",
                (size, (page - 1) * size)).fetchall()
            items = self._center_items(conn, rows)
        return {"items": items, "unread": unread, "latest_id": latest, "page": page, "page_size": size}

    def read_task_notification(self, notification_id):
        with self.store.connect(write=True) as conn:
            if not conn.execute("SELECT 1 FROM article_task_notifications WHERE id=?", (notification_id,)).fetchone():
                raise ArticleError("提醒不存在", 404)
            conn.execute("UPDATE article_task_notifications SET read_at=COALESCE(read_at,?) WHERE id=?", (utc_now(), notification_id))
        return {"id": notification_id}

    def read_task_notifications(self, data):
        """只读到客户端实际观察到的编号，不吞掉并发产生的新提醒。"""
        if not isinstance(data, dict) or set(data) != {"through_id"}:
            raise ArticleError("请提供 through_id，标记已观察到的提醒")
        through = positive_integer(data["through_id"], "through_id", 9223372036854775807)
        with self.store.connect(write=True) as conn:
            latest = conn.execute("SELECT COALESCE(MAX(id),0) FROM article_task_notifications").fetchone()[0]
            if through > latest:
                raise ArticleError("through_id 超过已存在的提醒编号")
            updated = conn.execute("""UPDATE article_task_notifications SET read_at=?
                WHERE id<=? AND read_at IS NULL AND resolved_at IS NULL""", (utc_now(), through))
        return {"read": updated.rowcount}
