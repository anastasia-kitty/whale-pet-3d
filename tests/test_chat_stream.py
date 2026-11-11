# -*- coding: utf-8 -*-
"""
用本地假服务端测试流式链路（不需要真的 API Key）。

运行：
    .\\.venv\\Scripts\\python.exe -m unittest tests.test_chat_stream -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from whale_api import ChatWorker  # noqa: E402
from whale_chat import ChatWindow  # noqa: E402
from whale_config import Settings  # noqa: E402
from whale_store import ConversationStore  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {}
        self.server.last_payload = payload  # type: ignore[attr-defined]
        self.server.last_auth = self.headers.get("Authorization")  # type: ignore[attr-defined]

        status = getattr(self.server, "status", 200)  # type: ignore[attr-defined]
        if status != 200:
            body = getattr(self.server, "body", b"{}")  # type: ignore[attr-defined]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        events = list(self.server.events)  # type: ignore[attr-defined]
        try:
            for event in events:
                if isinstance(event, float):
                    time.sleep(event)
                    continue
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, format: str, *args) -> None:
        pass


def _sse(delta: dict, usage: dict = None) -> str:
    payload = {"choices": [{"delta": delta, "index": 0}]}
    if usage:
        payload["usage"] = usage
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


class FakeServer:
    def __init__(self, events, status: int = 200, body: bytes = b"{}") -> None:
        self.events = events
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.events = events
        self.httpd.status = status
        self.httpd.body = body
        self.httpd.last_payload = None
        self.httpd.last_auth = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class StreamTestCase(unittest.TestCase):
    app = None  # type: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WHALE_PET_DATA_DIR"] = self._tmp.name
        self.settings = Settings()
        self.settings.api_key = "sk-test"
        self.settings.thinking = True
        self.settings.reasoning_effort = "high"
        self.settings.save()

    def tearDown(self) -> None:
        os.environ.pop("WHALE_PET_DATA_DIR", None)
        self._tmp.cleanup()

    def _wait(self, condition, timeout: float = 12.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def test_worker_streams_content_and_reasoning(self) -> None:
        events = [
            _sse({"reasoning_content": "先想"}),
            _sse({"reasoning_content": "一下。"}),
            _sse({"content": "你好"}),
            _sse({"content": "呀～"}),
            _sse({}, {"total_tokens": 42}),
            "data: [DONE]\n\n",
        ]
        with FakeServer(events) as server:
            self.settings.base_url = server.base_url
            worker = ChatWorker(
                self.settings,
                [{"role": "user", "content": "你好"}],
            )
            content = []
            reasoning = []
            result = {}
            worker.delta.connect(content.append)
            worker.reasoning.connect(reasoning.append)
            worker.completed.connect(
                lambda c, r, u, cancelled: result.update(
                    content=c, reasoning=r, usage=u, cancelled=cancelled
                )
            )
            worker.failed.connect(lambda msg: result.update(error=msg))
            worker.start()
            self.assertTrue(
                self._wait(lambda: bool(result)), "worker did not finish"
            )
            worker.wait(3000)

            self.assertEqual("".join(content), "你好呀～")
            self.assertEqual("".join(reasoning), "先想一下。")
            self.assertEqual(result["content"], "你好呀～")
            self.assertEqual(result["reasoning"], "先想一下。")
            self.assertEqual(result["usage"], {"total_tokens": 42})
            self.assertFalse(result["cancelled"])
            self.assertNotIn("error", result)

            payload = server.httpd.last_payload
            self.assertEqual(payload["model"], "deepseek-flash")
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            self.assertEqual(payload["reasoning_effort"], "high")
            self.assertTrue(payload["stream"])
            self.assertEqual(server.httpd.last_auth, "Bearer sk-test")

    def test_worker_cancel_keeps_partial(self) -> None:
        events = [
            _sse({"content": "第一段"}),
            0.25,
            _sse({"content": "第二段"}),
            0.25,
            _sse({"content": "第三段"}),
            "data: [DONE]\n\n",
        ]
        with FakeServer(events) as server:
            self.settings.base_url = server.base_url
            worker = ChatWorker(
                self.settings, [{"role": "user", "content": "讲个长故事"}]
            )
            result = {}
            received = []
            worker.delta.connect(received.append)
            worker.completed.connect(
                lambda c, r, u, cancelled: result.update(
                    content=c, cancelled=cancelled
                )
            )
            worker.failed.connect(lambda msg: result.update(error=msg))
            worker.start()
            self.assertTrue(self._wait(lambda: bool(received), 6.0))
            worker.cancel()
            self.assertTrue(self._wait(lambda: bool(result), 6.0))
            worker.wait(3000)
            self.assertNotIn("error", result)
            self.assertTrue(result["cancelled"])
            full = "第一段第二段第三段"
            self.assertTrue(full.startswith(result["content"]))
            self.assertLess(len(result["content"]), len(full))

    def test_chat_window_send_flow(self) -> None:
        events = [
            _sse({"reasoning_content": "用户只是打个招呼。"}),
            _sse({"content": "你好呀～"}),
            _sse({"content": "今天也要开心哦。"}),
            "data: [DONE]\n\n",
        ]
        with FakeServer(events) as server:
            self.settings.base_url = server.base_url
            self.settings.save()

            window = ChatWindow()
            window.open_window()
            window._send_text("你好")
            self.assertTrue(
                self._wait(lambda: not window._busy, 12.0),
                "window stayed busy",
            )
            self.app.processEvents()

            self.assertIsNotNone(window._conversation)
            conversation = window._conversation
            self.assertEqual([m.role for m in conversation.messages], ["user", "assistant"])
            self.assertEqual(conversation.messages[1].content, "你好呀～今天也要开心哦。")
            self.assertIn("打个招呼", conversation.messages[1].reasoning)
            self.assertEqual(conversation.title, "你好")

            stored = ConversationStore().get(conversation.id)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(len(stored.messages), 2)

            # 历史抽屉里能看到这段对话
            window._refresh_history()
            self.assertGreaterEqual(window._drawer.list.count(), 2)

            window.shutdown()

    def test_chat_window_shows_error(self) -> None:
        body = json.dumps(
            {"error": {"message": "Authentication Fails"}}
        ).encode("utf-8")
        with FakeServer([], status=401, body=body) as server:
            self.settings.base_url = server.base_url
            self.settings.save()

            window = ChatWindow()
            window.open_window()
            window._send_text("你好")
            self.assertTrue(
                self._wait(lambda: not window._busy, 8.0),
                "window stayed busy after error",
            )
            self.app.processEvents()

            self.assertIsNotNone(window._conversation)
            conversation = window._conversation
            self.assertEqual(conversation.messages[-1].role, "assistant")
            self.assertIn("API Key", conversation.messages[-1].error)
            self.assertIsNone(window._active_bubble)

            window.shutdown()


if __name__ == "__main__":
    unittest.main()
