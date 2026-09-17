# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import db
from core import registration_service


SESSION_TIMEOUT = "RuntimeError: 等待 /api/auth/session accessToken 超时"


class SessionRecoverRetryContractTests(unittest.TestCase):
    @staticmethod
    def storage(root: Path) -> dict:
        return {
            "_ACCOUNTS_JSON": root / "accounts.json",
            "_OUTLOOK_JSON": root / "outlook.json",
            "_GENERIC_API_EMAIL_JSON": root / "generic.json",
            "_DOMAIN_EMAIL_JSON": root / "domain.json",
            "_JOBS_JSON": root / "jobs.json",
            "_LEGACY_ACCOUNTS_JSON": root / "legacy-accounts.json",
            "_LEGACY_OUTLOOK_JSON": root / "legacy-outlook.json",
            "_LEGACY_JOBS_JSON": root / "legacy-jobs.json",
            "_LEGACY_SQLITE": root / "legacy.db",
            "_CODEX_DIR": root / "codex",
            "_CODEX_AGENT_DIR": root / "agent",
            "_LEGACY_CODEX_EXPORT_STATE": root / "state.json",
            "_LOG_DIR": root / "logs",
            "_SQLITE_READY": False,
            "_SQLITE_READY_PATH": None,
        }

    def _isolate(self, root: Path):
        return patch.multiple(db, **self.storage(root))

    def _failed_job(self, *, email: str, error: str, account_id=None, status="failed"):
        job = db.create_job(email_source="imap")
        db.update_job(
            int(job["id"]),
            status=status,
            email=email,
            account_id=account_id,
            error=error,
        )
        return db.get_job(int(job["id"]))

    def _seed_imap(self, email: str, status: str) -> None:
        inserted, skipped = db.import_imap_emails(
            [{
                "email": email,
                "imap_password": "pw",
                "imap_server": "imap.example.com",
                "imap_port": 993,
            }]
        )
        self.assertEqual((inserted, skipped), (1, 0))
        db.release_imap_email(email, status=status, note="test")

    def test_ordinary_failed_job_without_account_retries_full_registration(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            job = self._failed_job(email="new@example.com", error="找不到邮箱输入框")
            info = registration_service.get_retry_info(job)
            self.assertTrue(info["retryable"])
            self.assertEqual(info["retry_action"], "registration")
            self.assertEqual(info["retry_label"], "重试")

    def test_account_with_access_token_still_retries_codex(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            account_id = db.insert_account(
                email="ok@example.com",
                access_token="tok-ok",
                email_source="imap",
                codex_status="failed",
            )
            job = self._failed_job(
                email="ok@example.com",
                error="Codex 未完成",
                account_id=account_id,
            )
            info = registration_service.get_retry_info(job)
            self.assertEqual(info["retry_action"], "codex")
            self.assertEqual(info["retry_label"], "补跑 Codex")

    def test_empty_access_token_account_retries_session_recover_not_codex(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            account_id = db.insert_account(
                email="empty-at@example.com",
                access_token="",
                email_source="imap",
            )
            job = self._failed_job(
                email="empty-at@example.com",
                error=SESSION_TIMEOUT,
                account_id=account_id,
            )
            info = registration_service.get_retry_info(job)
            self.assertTrue(info["retryable"])
            self.assertEqual(info["retry_action"], "session_recover")
            self.assertEqual(info["retry_label"], "补 token")

    def test_stock_timeout_with_failed_pool_email_retries_session_recover(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "cirque82vestal@icloud.com"
            self._seed_imap(email, "failed")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT)
            info = registration_service.get_retry_info(job)
            self.assertTrue(info["retryable"])
            self.assertEqual(info["retry_action"], "session_recover")
            self.assertEqual(info["retry_label"], "补 token")

    def test_stock_timeout_not_blocked_by_other_email_registration_success(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "cirque82vestal@icloud.com"
            self._seed_imap(email, "failed")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT)
            child, created = db.create_retry_job(
                int(job["id"]),
                job_type="registration",
                email_source="imap",
                email="leis-lupus85@icloud.com",
            )
            self.assertTrue(created)
            db.update_job(int(child["id"]), status="success", email="leis-lupus85@icloud.com")
            info = registration_service.get_retry_info(db.get_job(int(job["id"])))
            self.assertTrue(info["retryable"])
            self.assertEqual(info["retry_action"], "session_recover")
            self.assertEqual(info["retry_label"], "补 token")

    def test_stock_retry_inserts_placeholder_account_then_recovers(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "job8@icloud.com"
            self._seed_imap(email, "failed")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT)
            self.assertIsNone(db.get_account_by_email(email))
            executor = MagicMock()
            with patch.object(registration_service, "get_executor", return_value=executor):
                result = registration_service.retry_job(int(job["id"]))
            self.assertEqual(result["retry_action"], "session_recover")
            acc = db.get_account_by_email(email)
            self.assertIsNotNone(acc)
            self.assertFalse(str(acc.get("access_token") or "").strip())
            self.assertEqual(result["job"]["account_id"], acc["id"])
            self.assertEqual(result["job"]["email"], email)
            self.assertEqual(int(result["job"]["id"]), int(job["id"]))
            self.assertEqual(len(db.list_jobs(limit=100)), 1)
            executor.submit.assert_called_once()
            self.assertEqual(executor.submit.call_args.args[0].__name__, "_run_session_recover_job")

    def test_stock_timeout_with_available_pool_email_still_retries_registration(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "not-created@icloud.com"
            self._seed_imap(email, "available")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT)
            info = registration_service.get_retry_info(job)
            self.assertEqual(info["retry_action"], "registration")

    def test_stopped_job_with_access_token_log_retries_session_recover_not_new_registration(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "hotbeds-names-5e@icloud.com"
            self._seed_imap(email, "available")
            job = self._failed_job(
                email=email,
                error="用户手动停止（任务实例不存在）",
                status="stopped",
            )
            Path(job["log_file"]).write_text(
                "12:15:53 [INFO] [Cloak注册] 已拿到 accessToken：hotbeds-names-5e@icloud.com\n"
                "12:15:53 [INFO] [Cloak注册] 注册成功后随机停留 25.8s\n",
                encoding="utf-8",
            )
            info = registration_service.get_retry_info(db.get_job(int(job["id"])))
            self.assertTrue(info["retryable"])
            self.assertEqual(info["retry_action"], "session_recover")
            self.assertEqual(info["retry_label"], "补 token")
            executor = MagicMock()
            with patch.object(registration_service, "get_executor", return_value=executor):
                result = registration_service.retry_job(int(job["id"]))
            self.assertEqual(result["retry_action"], "session_recover")
            self.assertEqual(int(result["job"]["id"]), int(job["id"]))
            self.assertFalse(result.get("created"))
            self.assertEqual(len(db.list_jobs(limit=100)), 1)
            acc = db.get_account_by_email(email)
            self.assertIsNotNone(acc)
            self.assertFalse(str(acc.get("access_token") or "").strip())
            self.assertEqual(db.get_imap_email_by_email(email)["status"], "failed")
            executor.submit.assert_called_once()
            self.assertEqual(executor.submit.call_args.args[0].__name__, "_run_session_recover_job")
            self.assertEqual(int(executor.submit.call_args.args[1]), int(job["id"]))

    def test_orphan_stop_keeps_created_email_when_log_has_access_token(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "kept-after-stop@icloud.com"
            self._seed_imap(email, "used")
            job = db.create_job(email_source="imap")
            db.update_job(
                int(job["id"]),
                status="stopping",
                email=email,
                error="用户手动停止中",
            )
            saved = db.get_job(int(job["id"]))
            Path(saved["log_file"]).write_text(
                "12:15:53 [INFO] [Cloak注册] 已拿到 accessToken：kept-after-stop@icloud.com\n",
                encoding="utf-8",
            )
            result = registration_service.request_stop_job(int(job["id"]))
            self.assertTrue(result["ok"])
            self.assertEqual(result["state"], "stopped")
            stopped = db.get_job(int(job["id"]))
            self.assertEqual(stopped["status"], "stopped")
            self.assertTrue(stopped.get("account_id"))
            acc = db.get_account(int(stopped["account_id"]))
            self.assertEqual(acc["email"], email)
            self.assertFalse(str(acc.get("access_token") or "").strip())
            self.assertEqual(db.get_imap_email_by_email(email)["status"], "failed")
            info = registration_service.get_retry_info(stopped)
            self.assertEqual(info["retry_action"], "session_recover")

    def test_retry_job_session_recover_keeps_email_and_job_type(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "recover@example.com"
            account_id = db.insert_account(email=email, access_token="", email_source="imap")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT, account_id=account_id)
            executor = MagicMock()
            with patch.object(registration_service, "get_executor", return_value=executor):
                result = registration_service.retry_job(int(job["id"]))
            self.assertTrue(result["ok"])
            self.assertEqual(result["retry_action"], "session_recover")
            reused = result["job"]
            self.assertEqual(int(reused["id"]), int(job["id"]))
            self.assertEqual(reused["job_type"], "registration")
            self.assertEqual(reused["email"], email)
            self.assertEqual(reused["account_id"], account_id)
            self.assertNotIn("完整注册", str(result.get("message") or ""))
            self.assertNotIn("已创建重试任务", str(result.get("message") or ""))
            self.assertEqual(len(db.list_jobs(limit=100)), 1)
            executor.submit.assert_called_once()
            self.assertEqual(int(executor.submit.call_args.args[1]), int(job["id"]))

    def test_account_created_failure_inserts_placeholder_without_token(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            job = db.create_job(email_source="imap")
            fake_result = {
                "success": False,
                "email": "created@example.com",
                "account_created": True,
                "error": SESSION_TIMEOUT,
            }
            with patch.object(
                registration_service,
                "_prepare_registration_args",
                return_value=(None, "Name", "1990-01-01"),
            ), patch(
                "main.run_registration",
                return_value=fake_result,
            ):
                registration_service._run_one_job(int(job["id"]), str(Path(td) / "job.log"))
            saved = db.get_job(int(job["id"]))
            self.assertEqual(saved["status"], "failed")
            self.assertTrue(saved.get("account_id"))
            acc = db.get_account(int(saved["account_id"]))
            self.assertEqual(acc["email"], "created@example.com")
            self.assertFalse(str(acc.get("access_token") or "").strip())
            info = registration_service.get_retry_info(saved)
            self.assertEqual(info["retry_action"], "session_recover")

    def test_failed_session_recover_does_not_fall_back_to_registration(self):
        with tempfile.TemporaryDirectory() as td, self._isolate(Path(td)):
            email = "stay@example.com"
            account_id = db.insert_account(email=email, access_token="", email_source="imap")
            job = self._failed_job(email=email, error=SESSION_TIMEOUT, account_id=account_id)
            executor = MagicMock()
            with patch.object(registration_service, "get_executor", return_value=executor):
                first = registration_service.retry_job(int(job["id"]))
            self.assertEqual(int(first["job"]["id"]), int(job["id"]))
            db.update_job(int(job["id"]), status="failed", error="查活失败", email=email, account_id=account_id)
            info = registration_service.get_retry_info(db.get_job(int(job["id"])))
            self.assertEqual(info["retry_action"], "session_recover")
            with patch.object(registration_service, "get_executor", return_value=executor):
                second = registration_service.retry_job(int(job["id"]))
            self.assertEqual(second["retry_action"], "session_recover")
            self.assertEqual(int(second["job"]["id"]), int(job["id"]))
            self.assertEqual(second["job"]["job_type"], "registration")
            self.assertEqual(second["job"]["email"], email)
            self.assertEqual(len(db.list_jobs(limit=100)), 1)


class SessionRecoverUiCopyTests(unittest.TestCase):
    def test_session_recover_copy_does_not_say_full_registration(self):
        templates = [
            Path("/app/webui/templates/index.html"),
            Path("/app/webui/templates/index_legacy.html"),
        ]
        if not templates[0].exists():
            templates = [
                Path(__file__).resolve().parent.parent / "webui" / "templates" / "index.html",
                Path(__file__).resolve().parent.parent / "webui" / "templates" / "index_legacy.html",
            ]
        for path in templates:
            text = path.read_text(encoding="utf-8")
            self.assertIn("session_recover", text)
            self.assertIn("用同一邮箱补 accessToken，不换邮箱", text)
            recover_idx = text.find("session_recover")
            nearby = text[recover_idx:recover_idx + 400]
            self.assertNotIn("创建新的完整注册任务", nearby)
            recover_confirm = "用同一邮箱补 accessToken，不换邮箱。在本任务内继续，不新建任务。"
            self.assertIn(recover_confirm, text)
            confirm_idx = text.find(recover_confirm)
            confirm_block = text[max(0, confirm_idx - 80):confirm_idx + len(recover_confirm) + 10]
            self.assertNotIn("创建新的完整注册任务", confirm_block)
            self.assertNotIn("原任务记录和日志会保留", confirm_block)


if __name__ == "__main__":
    unittest.main()
