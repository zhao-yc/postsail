"""SQLite 增量结构和短事务；所有发布记录都写入现有项目数据库。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .model import ArticleError


SCHEMA = """
CREATE TABLE IF NOT EXISTS article_assets (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL, mime_type TEXT NOT NULL,
 size INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, sha256 TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, content_html TEXT NOT NULL, revision INTEGER NOT NULL,
 cover_asset_id TEXT, tags_json TEXT NOT NULL, platform_options_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS article_asset_refs (
 owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, asset_id TEXT NOT NULL,
 PRIMARY KEY(owner_type, owner_id, asset_id)
);
CREATE TABLE IF NOT EXISTS article_publish_batches (
 id TEXT PRIMARY KEY, article_id TEXT NOT NULL, revision INTEGER NOT NULL, mode TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS article_publish_tasks (
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, article_id TEXT NOT NULL, revision INTEGER NOT NULL,
 platform TEXT NOT NULL, account_id INTEGER NOT NULL, mode TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'queued', message TEXT NOT NULL DEFAULT '',
 attempts INTEGER NOT NULL DEFAULT 0, submit_started INTEGER NOT NULL DEFAULT 0,
 platform_id TEXT NOT NULL DEFAULT '', platform_url TEXT NOT NULL DEFAULT '', platform_status TEXT NOT NULL DEFAULT '',
 evidence_json TEXT NOT NULL DEFAULT '[]', prepared_html TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS article_task_status ON article_publish_tasks(status, created_at);
CREATE INDEX IF NOT EXISTS article_task_duplicate ON article_publish_tasks(article_id,revision,account_id,mode);
CREATE TABLE IF NOT EXISTS article_worker_lease (
 id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires_at REAL NOT NULL
);
"""


def encode(value) -> str:
    """稳定 JSON 编码用于快照及幂等请求摘要。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ArticleStore:
    """初始化只增加新表，禁止重建已有账号或素材表。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self, write=False):
        """并发写入用立即事务，事务不跨越网络或浏览器操作。"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def refs(conn, owner_type: str, owner_id: str, asset_ids):
        """引用跟随稿件修订替换，快照引用则持续保留。"""
        asset_ids = {asset_id for asset_id in asset_ids if asset_id}
        for asset_id in asset_ids:
            if not conn.execute("SELECT 1 FROM article_assets WHERE id=?", (asset_id,)).fetchone():
                raise ArticleError("图片素材在保存期间被删除，请重新上传", 409)
        conn.execute("DELETE FROM article_asset_refs WHERE owner_type=? AND owner_id=?", (owner_type, owner_id))
        conn.executemany("INSERT INTO article_asset_refs VALUES (?,?,?)",
                         [(owner_type, owner_id, asset_id) for asset_id in asset_ids])
