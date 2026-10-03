"""Conflicting branch IDs never choose a platform without an explicit binding."""
import asyncio
import io
import json
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.account_bindings import (
    AccountBindingError, account_identity, bind_account,
    confirm_account_platform, require_account_platform,
)
from utils.platform_accounts import ACCOUNT_PLATFORMS


class AccountBindingFixture:
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        (self.base / "db").mkdir()
        (self.base / "cookiesFile").mkdir()
        self.db = self.base / "db" / "database.db"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            conn.execute("CREATE TABLE history(id INTEGER,platform TEXT,payload TEXT)")
            conn.execute("INSERT INTO history VALUES(1,'jd','original frozen task')")

    def add(self, kind, filename=None, *, platform=None):
        filename = filename or "fixture-" + str(kind) + ".json"
        (self.base / "cookiesFile" / filename).write_text('{"fixture":"unchanged session"}')
        with sqlite3.connect(self.db) as conn:
            cursor = conn.execute("INSERT INTO user_info(type,filePath,userName,status) VALUES(?,?,?,1)", (kind, filename, "original name"))
            account_id = cursor.lastrowid
            if platform:
                bind_account(conn, account_id, platform, "test-fixture")
        return account_id

    def row(self, account_id):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT * FROM user_info WHERE id=?", (account_id,)).fetchone()


class AccountBindingTests(AccountBindingFixture, unittest.TestCase):
    def test_legacy_filename_only_suggests_and_cannot_authenticate(self):
        for kind, slug in ((12, "wechat"), (13, "jd"), (14, "xiaohongshu_merchant"), (15, "dongchedi"), (16, "taobao")):
            account_id = self.add(kind, slug + "_" + "a" * 32 + ".json")
            with sqlite3.connect(self.db) as conn:
                identity = account_identity(conn, self.row(account_id))
                self.assertTrue(identity["needs_confirmation"])
                self.assertIsNone(identity["platform"])
                self.assertEqual(identity["suggested_platform"], slug)
                self.assertEqual(len(identity["candidates"]), 2)
                with self.assertRaises(AccountBindingError):
                    require_account_platform(conn, self.row(account_id))

    def test_main_and_work_same_type_migrate_independently_without_data_loss(self):
        first, second = self.add(13, "main.json"), self.add(13, "work.json")
        before = {p.name: p.read_bytes() for p in (self.base / "cookiesFile").iterdir()}
        original = self.row(second)
        main = confirm_account_platform(self.db, first, "dayu", 13)
        work = confirm_account_platform(self.db, second, "jd", 13)
        self.assertEqual((main["type"], work["type"]), (13, 26))
        self.assertEqual(self.row(second), (original[0], 26, *original[2:]))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(len(conn.execute("PRAGMA table_info(user_info)").fetchall()), 5)
            self.assertEqual(conn.execute("SELECT * FROM history").fetchall(), [(1, "jd", "original frozen task")])
            self.assertEqual(require_account_platform(conn, self.row(first)), "dayu")
            self.assertEqual(require_account_platform(conn, self.row(second)), "jd")
        with sqlite3.connect(work["backup_path"]) as backup:
            self.assertEqual(backup.execute("SELECT * FROM user_info WHERE id=?", (second,)).fetchone(), original)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.base / "cookiesFile").iterdir()})
        if os.name == "posix":
            self.assertEqual(Path(work["backup_path"]).stat().st_mode & 0o777, 0o600)

    def test_explicit_work_mapping_is_complete_and_confirmation_is_idempotent(self):
        for old, slug, new in ((12, "wechat", 25), (13, "jd", 26), (14, "xiaohongshu_merchant", 27), (15, "dongchedi", 24), (16, "taobao", 28)):
            account_id = self.add(old)
            result = confirm_account_platform(self.db, account_id, slug, old)
            self.assertEqual(result["type"], new)
            repeated = confirm_account_platform(self.db, account_id, slug, old)
            self.assertTrue(repeated["already_confirmed"])
            self.assertIsNone(repeated["backup_path"])

    def test_failed_migration_rolls_back_type_and_preserves_backup(self):
        account_id = self.add(12)
        before = self.row(account_id)
        with patch("utils.account_bindings.bind_account", side_effect=RuntimeError("injected storage failure")):
            with self.assertRaises(RuntimeError):
                confirm_account_platform(self.db, account_id, "wechat", 12)
        self.assertEqual(self.row(account_id), before)
        backups = list((self.db.parent / "account-migration-backups").glob("*.db"))
        self.assertEqual(len(backups), 1)

    def test_binding_rejects_changed_type_or_cookie_path(self):
        account_id = self.add(12, platform="yidian")
        for column, value in (("type", 13), ("filePath", "other-session.json")):
            row = list(self.row(account_id))
            row[1 if column == "type" else 2] = value
            with sqlite3.connect(self.db) as conn, self.assertRaises(AccountBindingError):
                require_account_platform(conn, row)
        with self.assertRaises(AccountBindingError):
            confirm_account_platform(self.db, account_id, "wechat", 12)

    def test_non_conflicting_legacy_types_remain_compatible(self):
        account_id = self.add(24)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(require_account_platform(conn, self.row(account_id), "dongchedi"), "dongchedi")

    def test_invalid_confirmation_does_not_mutate_or_backup(self):
        account_id = self.add(12)
        before = self.row(account_id)
        for slug, old in (("jd", 12), ("wechat", 13), ("jingdong", 12)):
            with self.assertRaises(AccountBindingError):
                confirm_account_platform(self.db, account_id, slug, old)
        self.assertEqual(self.row(account_id), before)
        self.assertFalse((self.db.parent / "account-migration-backups").exists())


class AccountBindingApiTests(AccountBindingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import sau_backend
        self.backend = sau_backend
        self.addCleanup(patch.stopall)
        patch.object(sau_backend, "BASE_DIR", self.base).start()
        patch.dict(sau_backend.app.config, {"OMNIPOST_DB_PATH": self.db}).start()
        self.client = sau_backend.app.test_client()

    def test_deleting_account_clears_binding_before_id_reuse_and_preserves_history(self):
        account_id = self.add(26, platform="jd")
        response = self.client.get(f"/deleteAccount?id={account_id}")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIsNone(self.row(account_id))
        with sqlite3.connect(self.db) as conn:
            self.assertIsNone(conn.execute(
                "SELECT * FROM account_platform_bindings WHERE account_id=?", (account_id,)
            ).fetchone())
            self.assertEqual(conn.execute("SELECT * FROM history").fetchall(), [(1, "jd", "original frozen task")])
        new_id = self.add(27, platform="xiaohongshu_merchant")
        self.assertEqual(new_id, account_id)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(require_account_platform(conn, self.row(new_id)), "xiaohongshu_merchant")

    def test_pending_rows_are_visible_but_refresh_replacement_login_and_publish_are_blocked(self):
        account_id = self.add(12, "old-work.json")
        original = self.row(account_id)
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)) as check, \
                patch.dict(self.backend.app.extensions, {"legacy_article_publish": MagicMock()}) as extensions:
            response = self.client.get("/getAccounts")
            identity = response.json["accountIdentities"][str(account_id)]
            self.assertTrue(identity["needs_confirmation"])
            self.assertEqual(response.json["data"], [list(original)])
            self.assertEqual(self.client.get("/getValidAccounts?type=12").status_code, 200)
            check.assert_not_called()
            response = self.client.post("/uploadCookie", data={"id": str(account_id), "platform": "12", "file": (io.BytesIO(b'{}'), "session.json")})
            self.assertEqual(response.status_code, 400)
            with patch.object(self.backend.threading, "Thread") as start:
                self.assertEqual(self.client.get(f"/login?type=12&id=test&accountId={account_id}").status_code, 400)
                start.assert_not_called()
            response = self.client.post("/postVideo", json={"type": 12, "accountList": ["old-work.json"]})
            self.assertEqual(response.status_code, 400)
            extensions["legacy_article_publish"].assert_not_called()
        self.assertEqual(self.row(account_id), original)

    def test_confirmation_api_and_rename_cannot_change_platform(self):
        account_id = self.add(13)
        self.assertEqual(self.client.post("/confirmAccountPlatform", json=[]).status_code, 400)
        response = self.client.post("/confirmAccountPlatform", json={"id": account_id, "platform": "jd", "expectedType": 13})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.row(account_id)[1], 26)
        response = self.client.post("/updateUserinfo", json={"id": account_id, "type": 18, "userName": "changed"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/updateUserinfo", json={"id": account_id, "type": 26, "userName": "changed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.row(account_id)[1:4], (26, "fixture-13.json", "changed"))

    def test_new_imports_create_authoritative_binding_even_for_ambiguous_type(self):
        payload = {"cookies": [{"name": "fixture", "value": "not-real", "domain": ".yidianzixun.com", "path": "/"}], "origins": []}
        with patch.object(self.backend, "check_cookie", new=AsyncMock(return_value=True)):
            response = self.client.post("/importCookie", data={"platform": "12", "name": "new", "file": (io.BytesIO(json.dumps(payload).encode()), "session.json")})
        self.assertEqual(response.status_code, 200, response.json)
        account_id = response.json["data"]["id"]
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(require_account_platform(conn, self.row(account_id)), "yidian")
