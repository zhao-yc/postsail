"""Stable account identity across the incompatible main/work numeric registries.

Legacy rows and cookie files remain intact. Ambiguous types require an explicit
choice; a filename may suggest a choice but never authorizes a migration.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class AccountBindingError(ValueError):
    pass


LEGACY_CHOICES = {
    12: ("yidian", "wechat"), 13: ("dayu", "jd"),
    14: ("netease", "xiaohongshu_merchant"),
    15: ("acfun", "dongchedi"), 16: ("kuaichuan", "taobao"),
}


def ensure_account_bindings(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS account_platform_bindings (
        account_id INTEGER PRIMARY KEY, platform TEXT NOT NULL,
        bound_type INTEGER NOT NULL, bound_file_path TEXT NOT NULL,
        original_type INTEGER NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
    )""")


def _account(row):
    if row is None:
        raise AccountBindingError("账号不存在")
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(("id", "type", "filePath", "userName", "status"), row))


def _binding(conn, account_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='account_platform_bindings' AND type='table'").fetchone():
        return None
    raw = conn.execute("SELECT platform,bound_type,bound_file_path FROM account_platform_bindings WHERE account_id=?", (account_id,)).fetchone()
    return tuple(raw) if raw else None


def account_identity(conn, row):
    from utils.platform_accounts import ACCOUNT_PLATFORMS
    from utils.articles.platforms import PLATFORMS
    row = _account(row)
    if "filePath" not in row:
        row = _account(conn.execute("SELECT id,type,filePath,userName,status FROM user_info WHERE id=?", (row["id"],)).fetchone())
    kind, path = row["type"], row["filePath"]
    binding = _binding(conn, row["id"])
    canonical = ACCOUNT_PLATFORMS.get(kind)
    result = {"platform": None, "needs_confirmation": True, "reason": "账号平台绑定不一致，请恢复正确账号数据", "candidates": [], "suggested_platform": None}
    if binding:
        if binding == (canonical, kind, path):
            result.update(platform=canonical, needs_confirmation=False, reason="")
        return result
    if kind not in LEGACY_CHOICES:
        if canonical:
            result.update(platform=canonical, needs_confirmation=False, reason="")
        return result
    result["reason"] = "旧账号编号存在冲突，请先在账号管理中确认所属平台；原会话和状态已保留"
    for platform in LEGACY_CHOICES[kind]:
        account_type = next(value for value, slug in ACCOUNT_PLATFORMS.items() if slug == platform)
        label = PLATFORMS.get(platform, {}).get("label", platform)
        result["candidates"].append({"platform": platform, "label": label, "type": account_type})
        if re.fullmatch(re.escape(platform) + r"_[0-9a-f]{32}\.json", str(path)):
            result["suggested_platform"] = platform
    return result


def require_account_platform(conn, row, expected_platform=None):
    identity = account_identity(conn, row)
    if identity["needs_confirmation"]:
        raise AccountBindingError(identity["reason"])
    if expected_platform is not None and identity["platform"] != expected_platform:
        raise AccountBindingError("账号与所选平台不匹配")
    return identity["platform"]


def bind_account(conn, account_id, platform, source="created", *, original_type=None):
    from utils.platform_accounts import ACCOUNT_PLATFORMS
    row = conn.execute("SELECT id,type,filePath,userName,status FROM user_info WHERE id=?", (account_id,)).fetchone()
    row = _account(row)
    if ACCOUNT_PLATFORMS.get(row["type"]) != platform:
        raise AccountBindingError("账号类型与明确平台不一致")
    ensure_account_bindings(conn)
    existing = _binding(conn, account_id)
    expected = (platform, row["type"], row["filePath"])
    if existing:
        if existing != expected:
            raise AccountBindingError("已有平台绑定不可覆盖")
        return
    conn.execute("INSERT INTO account_platform_bindings VALUES (?,?,?,?,?,?,?)", (
        account_id, platform, row["type"], row["filePath"],
        row["type"] if original_type is None else original_type, source,
        datetime.now(timezone.utc).isoformat()))


def confirm_account_platform(db_path, account_id, platform, expected_type):
    """Explicit, backed-up, idempotent single-account migration; no cookie writes."""
    from utils.platform_accounts import ACCOUNT_PLATFORMS
    if type(account_id) is not int or account_id <= 0 or type(expected_type) is not int:
        raise AccountBindingError("账号 ID 或原编号无效")
    db_path = Path(db_path)
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM user_info WHERE id=?", (account_id,)).fetchone()
        row = _account(row)
        existing = _binding(conn, account_id)
        if existing:
            require_account_platform(conn, row, platform)
            return {"account_id": account_id, "platform": platform, "type": row["type"], "backup_path": None, "already_confirmed": True}
        if row["type"] != expected_type or platform not in LEGACY_CHOICES.get(expected_type, ()):
            raise AccountBindingError("账号已变化或所选平台不属于该旧编号，请刷新后重试")
        new_type = next((kind for kind, slug in ACCOUNT_PLATFORMS.items() if slug == platform), None)
        if new_type is None:
            raise AccountBindingError("平台未登记")
        backup_dir = db_path.parent / "account-migration-backups"
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        backup = backup_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex + ".db")
        # A separate connection makes SQLite's backup API include committed WAL data.
        backup.touch(mode=0o600, exist_ok=False)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        backup.chmod(0o600)
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM user_info WHERE id=?", (account_id,)).fetchone()
        if _account(current) != row or _binding(conn, account_id):
            raise AccountBindingError("账号在确认期间发生变化，未执行迁移，请刷新后重试")
        conn.execute("UPDATE user_info SET type=? WHERE id=?", (new_type, account_id))
        bind_account(conn, account_id, platform, "explicit-legacy-confirmation", original_type=expected_type)
        return {"account_id": account_id, "platform": platform, "type": new_type, "backup_path": str(backup), "already_confirmed": False}
