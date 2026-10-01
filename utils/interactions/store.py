"""互动消息、回复记录及运营配置的 SQLite 持久化。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    """所有持久化时间统一使用带时区的 UTC ISO 格式。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value):
    """保留中文并固定编码，便于幂等数据比较。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS interaction_messages (
 id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, platform TEXT NOT NULL,
 platform_message_id TEXT NOT NULL, kind TEXT NOT NULL, thread_id TEXT,
 parent_id TEXT, item_id TEXT, item_title TEXT, author_id TEXT, author_name TEXT,
 author_avatar TEXT, text TEXT NOT NULL, created_at TEXT, direction TEXT NOT NULL,
 read INTEGER NOT NULL DEFAULT 0, handled INTEGER NOT NULL DEFAULT 0,
 raw_json TEXT NOT NULL DEFAULT '{}',
 first_seen_at TEXT NOT NULL, baseline INTEGER NOT NULL DEFAULT 0,
 UNIQUE(account_id,platform,kind,platform_message_id)
);
CREATE INDEX IF NOT EXISTS interaction_messages_inbox ON interaction_messages(account_id,kind,created_at);
CREATE TABLE IF NOT EXISTS interaction_replies (
 id TEXT PRIMARY KEY, message_id TEXT NOT NULL, text TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 source TEXT NOT NULL, rule_id TEXT, status TEXT NOT NULL, platform_reply_id TEXT,
 error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(message_id) REFERENCES interaction_messages(id)
);
CREATE INDEX IF NOT EXISTS interaction_reply_message ON interaction_replies(message_id,created_at);
CREATE TABLE IF NOT EXISTS interaction_sync_state (
 account_id INTEGER NOT NULL, kind TEXT NOT NULL, last_synced_at TEXT,
 state TEXT NOT NULL DEFAULT 'idle', error TEXT, initialized INTEGER NOT NULL DEFAULT 0,
 baseline_at TEXT,
 PRIMARY KEY(account_id,kind)
);
CREATE TABLE IF NOT EXISTS interaction_sync_jobs (
 id TEXT PRIMARY KEY, status TEXT NOT NULL, request_json TEXT NOT NULL,
 results_json TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interaction_rules (
 id TEXT PRIMARY KEY, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interaction_phrases (
 id TEXT PRIMARY KEY, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interaction_settings (
 key TEXT PRIMARY KEY, value_json TEXT NOT NULL
);
"""


class InteractionStore:
    """数据库连接按操作创建，事务用于跨线程及多进程的回复去重。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            # 原地升级已有工作台数据库，不重建用户消息表。
            columns = {r[1] for r in conn.execute("PRAGMA table_info(interaction_sync_state)")}
            if "baseline_at" not in columns:
                conn.execute("ALTER TABLE interaction_sync_state ADD COLUMN baseline_at TEXT")
            message_columns = {r[1] for r in conn.execute("PRAGMA table_info(interaction_messages)")}
            if "raw_json" not in message_columns:
                conn.execute("ALTER TABLE interaction_messages ADD COLUMN raw_json TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self):
        """启用外键与等待锁，异常会回滚当前事务。"""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def settings(self):
        """首次安装保持后台采集和自动回复关闭。"""
        defaults = {"enabled": False, "intervalSeconds": 300, "accountIds": [],
                    "rateLimitPerHour": 20, "notifications": {"enabled": True, "browser": False},
                    "lastRunAt": None, "error": None}
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM interaction_settings WHERE key='settings'").fetchone()
        if row:
            defaults.update(json.loads(row[0]))
        return defaults

    def save_settings(self, data):
        """保存完整配置，读取时继续兼容未来新增默认字段。"""
        with self.connect() as conn:
            conn.execute("INSERT INTO interaction_settings(key,value_json) VALUES('settings',?) "
                         "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (encode(data),))
        return data

    def update_settings(self, transform):
        """在写事务内合并配置，避免后台状态和用户修改相互覆盖。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            defaults = {"enabled": False, "intervalSeconds": 300, "accountIds": [],
                        "rateLimitPerHour": 20, "notifications": {"enabled": True, "browser": False},
                        "lastRunAt": None, "error": None}
            row = conn.execute("SELECT value_json FROM interaction_settings WHERE key='settings'").fetchone()
            if row:
                defaults.update(json.loads(row[0]))
            result = transform(defaults)
            conn.execute("INSERT INTO interaction_settings(key,value_json) VALUES('settings',?) "
                         "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (encode(result),))
            return result

    def merge_runtime_state(self, last_run_at, error):
        """运行器只能更新审计状态，不能恢复用户已关闭的开关。"""
        return self.update_settings(lambda current: {**current, "lastRunAt": last_run_at, "error": error})

    def records(self, table):
        """仅允许固定的运营配置表，表名不接受用户输入。"""
        if table not in {"interaction_rules", "interaction_phrases"}:
            raise ValueError("不支持的配置表")
        with self.connect() as conn:
            rows = conn.execute(f"SELECT data_json FROM {table} ORDER BY created_at DESC,id").fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_record(self, table, data):
        """配置创建与更新复用同一持久化入口。"""
        if table not in {"interaction_rules", "interaction_phrases"}:
            raise ValueError("不支持的配置表")
        stamp = now()
        with self.connect() as conn:
            conn.execute(f"INSERT INTO {table}(id,data_json,created_at,updated_at) VALUES(?,?,?,?) "
                         "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at",
                         (data["id"], encode(data), stamp, stamp))
        return data
