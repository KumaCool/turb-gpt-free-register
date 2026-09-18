# -*- coding: utf-8 -*-
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import cloakbrowser_versions as versions
from core import cloakbrowser_driver as driver_mod
from webui import config_editor
from webui.app import create_app


class CloakVersionCatalogTests(unittest.TestCase):
    def test_list_merges_sources_and_keeps_current(self):
        with patch.object(versions, "fetch_pro_latest", return_value="151.0.7922.108.6"), \
             patch.object(versions, "fetch_github_releases", return_value=[
                 {"version": "151.0.7922.108.6", "pro": True},
                 {"version": "151.0.7922.108.4", "pro": True},
                 {"version": "146.0.7680.177.5", "pro": False},
                 {"version": "150.0.7871.114.6", "pro": True},
                 {"version": "150.0.7871.114.2", "pro": True},
             ]), \
             patch.object(versions, "list_cached_binaries", return_value=[
                 {"version": "151.0.7922.108.6", "pro": True},
             ]):
            payload = versions.list_chromium_versions(
                current="145.0.7632.159.7",
                license_key="pro-key",
            )
        self.assertEqual(payload["latest"], "151.0.7922.108.6")
        self.assertEqual(payload["versions"][0], {"value": "", "label": "latest (151.0.7922.108.6)"})
        values = [row["value"] for row in payload["versions"]]
        self.assertEqual(values[0], "")
        self.assertIn("151.0.7922.108.6", values)
        self.assertNotIn("151.0.7922.108.4", values)
        self.assertIn("150.0.7871.114.6", values)
        self.assertNotIn("150.0.7871.114.2", values)
        self.assertIn("146.0.7680.177.5", values)
        self.assertIn("145.0.7632.159.7", values)
        self.assertEqual(len([v for v in values if v]), 4)
        labels = {row["value"]: row["label"] for row in payload["versions"]}
        self.assertIn("Pro", labels["151.0.7922.108.6"])
        self.assertIn("免费", labels["146.0.7680.177.5"])

    def test_remote_failures_still_return_latest_row(self):
        with patch.object(versions, "fetch_pro_latest", side_effect=RuntimeError("down")), \
             patch.object(versions, "fetch_github_releases", side_effect=RuntimeError("down")), \
             patch.object(versions, "list_cached_binaries", return_value=[]), \
             patch.object(versions, "_bundled_chromium_version", return_value="146.0.7680.177.5"):
            payload = versions.list_chromium_versions(license_key="pro-key")
        self.assertEqual(payload["versions"][0]["value"], "")
        self.assertTrue(payload["versions"][0]["label"].startswith("latest"))
        self.assertTrue(payload["errors"])

    def test_stale_current_pin_keeps_its_major_slot(self):
        with patch.object(versions, "fetch_pro_latest", return_value="151.0.7922.108.6"), \
             patch.object(versions, "fetch_github_releases", return_value=[
                 {"version": "151.0.7922.108.6", "pro": True},
                 {"version": "151.0.7922.108.4", "pro": True},
             ]), \
             patch.object(versions, "list_cached_binaries", return_value=[]):
            payload = versions.list_chromium_versions(
                current="151.0.7922.108.4",
                license_key="pro-key",
            )
        values = [row["value"] for row in payload["versions"] if row["value"]]
        self.assertEqual(values, ["151.0.7922.108.4"])
        self.assertNotIn("151.0.7922.108.6", values)


class CloakDriverVersionKwargsTests(unittest.TestCase):
    def _fake_cfg(self, **overrides):
        defaults = {
            "CLOAK_USE_PROXY": False,
            "CLOAK_EXTRA_ARGS": [],
            "CLOAK_FINGERPRINT_SEED": "",
            "CLOAK_HEADLESS": True,
            "CLOAK_HUMANIZE": True,
            "CLOAK_GEOIP": False,
            "CLOAK_LOCALE": "",
            "CLOAK_TIMEZONE": "",
            "CLOAK_LICENSE_KEY": "",
            "CLOAK_BROWSER_VERSION": "",
            "CLOAK_RELEASE_CHANNEL": "",
            "CLOAK_USER_DATA_DIR": "",
            "CLOAK_SELENIUM_TIMEOUT": 90,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _patch_cloak(self, launch, persistent):
        cloak_mod = MagicMock()
        cloak_mod.launch = launch
        cloak_mod.launch_persistent_context = persistent
        return patch.dict(sys.modules, {"cloakbrowser": cloak_mod})

    def test_empty_version_is_not_passed(self):
        fake_browser = MagicMock()
        fake_context = MagicMock()
        fake_page = MagicMock()
        fake_browser.new_context.return_value = fake_context
        fake_context.new_page.return_value = fake_page
        launch = MagicMock(return_value=fake_browser)
        with patch.object(driver_mod, "_cfg", self._fake_cfg()), self._patch_cloak(launch, MagicMock()):
            driver_mod.build_cloak_driver(proxy="")
        kwargs = launch.call_args.kwargs
        self.assertNotIn("browser_version", kwargs)
        self.assertNotIn("release_channel", kwargs)

    def test_pinned_version_and_preview_channel_are_passed(self):
        fake_browser = MagicMock()
        fake_context = MagicMock()
        fake_page = MagicMock()
        fake_browser.new_context.return_value = fake_context
        fake_context.new_page.return_value = fake_page
        launch = MagicMock(return_value=fake_browser)
        with patch.object(driver_mod, "_cfg", self._fake_cfg(
            CLOAK_BROWSER_VERSION="146.0.7680.177.5",
            CLOAK_RELEASE_CHANNEL="preview",
        )), self._patch_cloak(launch, MagicMock()):
            driver_mod.build_cloak_driver(proxy="")
        kwargs = launch.call_args.kwargs
        self.assertEqual(kwargs["browser_version"], "146.0.7680.177.5")
        self.assertEqual(kwargs["release_channel"], "preview")

    def test_persistent_context_gets_same_kwargs(self):
        fake_context = MagicMock()
        fake_page = MagicMock()
        fake_context.new_page.return_value = fake_page
        persistent = MagicMock(return_value=fake_context)
        with patch.object(driver_mod, "_cfg", self._fake_cfg(
            CLOAK_USER_DATA_DIR="/tmp/cloak-profile",
            CLOAK_BROWSER_VERSION="151.0.7922.108.6",
        )), self._patch_cloak(MagicMock(), persistent):
            driver_mod.build_cloak_driver(proxy="")
        kwargs = persistent.call_args.kwargs
        self.assertEqual(kwargs["browser_version"], "151.0.7922.108.6")


class CloakVersionWebUiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(auth_code="test-auth").test_client()
        self.client.environ_base["HTTP_X_AUTH_CODE"] = "test-auth"

    def test_config_editor_exposes_version_fields(self):
        fields = {field["key"]: field for field in config_editor.EDITABLE_FIELDS}
        self.assertEqual(fields["CLOAK_BROWSER_VERSION"]["group"], "CloakBrowser")
        self.assertEqual(fields["CLOAK_RELEASE_CHANNEL"]["group"], "CloakBrowser")

    def test_chromium_versions_api_uses_catalog(self):
        payload = {
            "latest": "151.0.7922.108.6",
            "versions": [{"value": "", "label": "latest (151.0.7922.108.6)"}],
            "errors": [],
        }
        with patch("core.cloakbrowser_versions.list_chromium_versions", return_value=payload):
            r = self.client.get("/api/cloak/chromium-versions")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["latest"], "151.0.7922.108.6")
        self.assertEqual(body["versions"][0]["value"], "")
        self.assertIn("latest (", body["versions"][0]["label"])


if __name__ == "__main__":
    unittest.main()
