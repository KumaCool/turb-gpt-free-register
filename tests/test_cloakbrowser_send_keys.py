# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock

from core.cloakbrowser_driver import CloakElement


class CloakSendKeysAppendTests(unittest.TestCase):
    def test_send_keys_appends_via_keyboard_type(self):
        page = MagicMock()
        locator = MagicMock()
        el = CloakElement(page, locator=locator)
        el.send_keys("m")
        locator.fill.assert_not_called()
        page.keyboard.type.assert_called_once_with("m", delay=0)

    def test_send_keys_select_all_does_not_type(self):
        page = MagicMock()
        locator = MagicMock()
        el = CloakElement(page, locator=locator)
        el.send_keys("\ue009", "a")
        page.keyboard.type.assert_not_called()
        locator.fill.assert_not_called()
        page.keyboard.press.assert_called()

    def test_text_reads_inner_text(self):
        page = MagicMock()
        locator = MagicMock()
        locator.evaluate.return_value = "Gửi lại email"
        el = CloakElement(page, locator=locator)
        self.assertEqual(el.text.strip(), "Gửi lại email")
        locator.evaluate.assert_called()


class _FakeJsHandle:
    def __init__(self, *, js_type="object", json=None, element=None, props=None, items=None):
        self._js_type = js_type
        self._json = json
        self._element = element
        self._props = props or {}
        self._items = items or []
        self.disposed = False

    def as_element(self):
        return self._element

    def json_value(self):
        return self._json

    def evaluate(self, expression, arg=None):
        if "typeof v" in expression or "Array.isArray" in expression:
            return self._js_type
        if "v.length" in expression:
            return len(self._items)
        if "Object.keys" in expression:
            return list(self._props.keys())
        return None

    def evaluate_handle(self, expression, arg=None):
        if "v[i]" in expression:
            return self._items[int(arg)]
        return self._props[arg]

    def dispose(self):
        self.disposed = True


class CloakJsResultUnwrapTests(unittest.TestCase):
    def test_dict_nested_elements_stay_cloak_elements(self):
        from core.cloakbrowser_driver import CloakSeleniumDriver

        page = MagicMock()
        input_el = object()
        button_el = object()
        input_handle = _FakeJsHandle(js_type="object", element=input_el)
        button_handle = _FakeJsHandle(js_type="object", element=button_el)
        root = _FakeJsHandle(
            js_type="object",
            json={"ok": True, "input": {}, "button": {}},
            props={
                "ok": _FakeJsHandle(js_type="boolean", json=True),
                "input": input_handle,
                "button": button_handle,
            },
        )
        result = CloakSeleniumDriver._unwrap_js_result(page, root)
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["input"], CloakElement)
        self.assertIs(result["input"].handle, input_el)
        self.assertIsInstance(result["button"], CloakElement)
        self.assertFalse(input_handle.disposed)
        self.assertFalse(button_handle.disposed)
        self.assertTrue(root.disposed)

    def test_element_handle_is_not_disposed(self):
        from core.cloakbrowser_driver import CloakSeleniumDriver

        page = MagicMock()
        element = object()
        handle = _FakeJsHandle(js_type="object", element=element)
        result = CloakSeleniumDriver._unwrap_js_result(page, handle)
        self.assertIsInstance(result, CloakElement)
        self.assertIs(result.handle, element)
        self.assertFalse(handle.disposed)
