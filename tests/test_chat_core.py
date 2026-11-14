# -*- coding: utf-8 -*-
"""
聊天功能的基础测试（不打开窗口）。

运行：
    .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whale_api import (  # noqa: E402
    ApiError,
    build_messages,
    build_payload,
    extract_stream_delta,
    parse_sse_line,
)
from whale_config import Settings  # noqa: E402
from whale_markdown import plain_excerpt, render_markdown  # noqa: E402
import whale_secret  # noqa: E402
from whale_store import (  # noqa: E402
    Conversation,
    ConversationStore,
    Message,
    group_label,
)


class TempDirMixin:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        os.environ["WHALE_PET_DATA_DIR"] = str(self.tmp_path)

    def tearDown(self) -> None:
        os.environ.pop("WHALE_PET_DATA_DIR", None)
        self._tmp.cleanup()


class SettingsTests(TempDirMixin, unittest.TestCase):
    def test_round_trip(self) -> None:
        settings = Settings()
        settings.api_key = "sk-test-1234567890"
        settings.model = "deepseek-v4-pro"
        settings.thinking = False
        settings.reasoning_effort = "max"
        settings.save()

        loaded = Settings.load()
        self.assertEqual(loaded.api_key, "sk-test-1234567890")
        self.assertEqual(loaded.model, "deepseek-v4-pro")
        self.assertFalse(loaded.thinking)
        self.assertEqual(loaded.reasoning_effort, "max")

    def test_bad_values_fall_back(self) -> None:
        (self.tmp_path / "settings.json").write_text(
            json.dumps(
                {
                    "model": "no-such-model",
                    "reasoning_effort": "ultra",
                    "max_context_chars": 1,
                    "chat_position": "oops",
                }
            ),
            encoding="utf-8",
        )
        settings = Settings.load()
        self.assertEqual(settings.model, "deepseek-flash")
        self.assertEqual(settings.reasoning_effort, "high")
        self.assertEqual(settings.max_context_chars, 120000)
        self.assertIsNone(settings.chat_position)

    def test_endpoint_normalisation(self) -> None:
        settings = Settings()
        self.assertEqual(
            settings.chat_endpoint(), "https://api.deepseek.com/chat/completions"
        )
        settings.base_url = "https://example.com/v1/"
        self.assertEqual(
            settings.chat_endpoint(), "https://example.com/v1/chat/completions"
        )
        settings.base_url = "https://example.com/v1/chat/completions"
        self.assertEqual(
            settings.chat_endpoint(), "https://example.com/v1/chat/completions"
        )

    def test_mask(self) -> None:
        settings = Settings()
        self.assertEqual(settings.masked_key(), "未填写")
        settings.api_key = "sk-1234567890abcdef"
        self.assertEqual(settings.masked_key(), "sk-123…cdef")

    def test_legacy_plaintext_key_still_loads(self) -> None:
        (self.tmp_path / "settings.json").write_text(
            json.dumps({"api_key": "sk-old-plaintext", "model": "deepseek-flash"}),
            encoding="utf-8",
        )
        settings = Settings.load()
        self.assertEqual(settings.api_key, "sk-old-plaintext")
        self.assertFalse(settings.key_encrypted)
        self.assertFalse(settings.key_load_error)

    def test_corrupt_encrypted_key_is_reported(self) -> None:
        (self.tmp_path / "settings.json").write_text(
            json.dumps({"api_key_enc": "AAAA", "model": "deepseek-flash"}),
            encoding="utf-8",
        )
        settings = Settings.load()
        self.assertEqual(settings.api_key, "")
        self.assertTrue(settings.key_load_error)

    @unittest.skipUnless(whale_secret.available(), "Windows DPAPI not available")
    def test_key_is_encrypted_on_disk(self) -> None:
        settings = Settings()
        settings.api_key = "sk-secret-1234567890"
        settings.save()

        raw_text = (self.tmp_path / "settings.json").read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        self.assertNotIn("api_key", raw)
        self.assertIn("api_key_enc", raw)
        self.assertEqual(raw.get("api_key_store"), "dpapi")
        self.assertNotIn("sk-secret-1234567890", raw_text)
        self.assertEqual(Settings.load().api_key, "sk-secret-1234567890")

    @unittest.skipUnless(whale_secret.available(), "Windows DPAPI not available")
    def test_dpapi_round_trip(self) -> None:
        token = whale_secret.protect("sk-round-trip")
        self.assertIsNotNone(token)
        assert token is not None
        self.assertNotIn("sk-round-trip", token)
        self.assertEqual(whale_secret.unprotect(token), "sk-round-trip")

    @unittest.skipUnless(whale_secret.available(), "Windows DPAPI not available")
    def test_settings_copy_keeps_key(self) -> None:
        settings = Settings()
        settings.api_key = "sk-copy"
        copied = settings.copy()
        self.assertEqual(copied.api_key, "sk-copy")
        self.assertEqual(copied.model, settings.model)


class StoreTests(TempDirMixin, unittest.TestCase):
    def test_create_save_load_list_delete(self) -> None:
        store = ConversationStore(self.tmp_path / "conversations")
        first = store.create()
        first.add("user", "帮我写一个 Python 快速排序")
        first.add("assistant", "好呀～", reasoning="先想一下……")
        store.save(first)

        self.assertTrue(store.path_for(first.id).exists())
        self.assertEqual(len(store.list_conversations()), 1)

        # 换一个 store 实例，模拟重新打开程序
        reopened = ConversationStore(self.tmp_path / "conversations")
        loaded = reopened.get(first.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.title, "帮我写一个 Python 快速排序")
        self.assertEqual(len(loaded.messages), 2)
        self.assertEqual(loaded.messages[1].reasoning, "先想一下……")

        reopened.delete(first.id)
        self.assertIsNone(reopened.get(first.id))
        self.assertEqual(reopened.list_conversations(), [])

    def test_title_and_preview(self) -> None:
        conversation = Conversation()
        conversation.add("user", "  你好呀\n今天过得怎么样  ")
        self.assertEqual(conversation.title, "你好呀 今天过得怎么样")
        conversation.add("assistant", "很好呀，刚刚喷了一会儿水～")
        self.assertEqual(conversation.preview(), "很好呀，刚刚喷了一会儿水～")

    def test_title_truncation(self) -> None:
        conversation = Conversation()
        conversation.add("user", "一" * 60)
        self.assertTrue(conversation.title.endswith("…"))
        self.assertLessEqual(len(conversation.title), 23)

    def test_history_skips_errors_and_trims(self) -> None:
        conversation = Conversation()
        conversation.add("user", "旧问题" * 6)
        conversation.add("assistant", "旧回答" * 6)
        conversation.add("user", "新问题")
        conversation.add("assistant", "", error="网络错误")

        history = conversation.history_for_api(max_chars=10)
        self.assertEqual(history, [{"role": "user", "content": "新问题"}])

        full = conversation.history_for_api(max_chars=10000)
        self.assertEqual([m["role"] for m in full], ["user", "assistant", "user"])

    def test_group_label(self) -> None:
        now = datetime(2026, 11, 12, 12, 0).timestamp()  # 周四
        today = datetime(2026, 11, 12, 9, 0).timestamp()
        yesterday = datetime(2026, 11, 11, 9, 0).timestamp()
        monday = datetime(2026, 11, 9, 9, 0).timestamp()
        old = datetime(2026, 10, 1, 9, 0).timestamp()
        self.assertEqual(group_label(today, now), "今天")
        self.assertEqual(group_label(yesterday, now), "昨天")
        self.assertEqual(group_label(monday, now), "本周")
        self.assertEqual(group_label(old, now), "更早")


class MarkdownTests(unittest.TestCase):
    def test_escape_and_inline(self) -> None:
        html = render_markdown("**粗体** 和 `a < b` 还有 <script>")
        self.assertIn("<b>粗体</b>", html)
        self.assertIn("a &lt; b", html)
        self.assertNotIn("<script>", html)

    def test_code_fence(self) -> None:
        html = render_markdown("```python\nprint('<hi>')\n```")
        self.assertIn("<pre", html)
        self.assertIn("python", html)
        self.assertIn("print('&lt;hi&gt;')", html)

    def test_links(self) -> None:
        html = render_markdown("看看 [文档](https://example.com/a?b=1)")
        self.assertIn('href="https://example.com/a?b=1"', html)
        self.assertIn(">文档</a>", html)

    def test_table(self) -> None:
        html = render_markdown("| 名字 | 数量 |\n| --- | --- |\n| 鲸鱼 | 1 |")
        self.assertIn("<table", html)
        self.assertIn("鲸鱼", html)

    def test_list_and_heading(self) -> None:
        html = render_markdown("## 小标题\n\n- 第一\n- 第二\n\n1. 甲\n2. 乙")
        self.assertIn("小标题", html)
        self.assertIn("<ul", html)
        self.assertIn("<ol", html)

    def test_empty(self) -> None:
        self.assertEqual(render_markdown(""), "")

    def test_excerpt(self) -> None:
        self.assertEqual(
            plain_excerpt("**你好**\n\n```py\nprint(1)\n```"), "你好 代码"
        )


class ApiParsingTests(unittest.TestCase):
    def test_parse_sse_line(self) -> None:
        self.assertEqual(parse_sse_line('data: {"a": 1}'), '{"a": 1}')
        self.assertEqual(parse_sse_line("data:[DONE]"), "[DONE]")
        self.assertIsNone(parse_sse_line(""))
        self.assertIsNone(parse_sse_line(": keep-alive"))
        self.assertIsNone(parse_sse_line("event: message"))

    def test_extract_delta(self) -> None:
        payload = {
            "choices": [
                {
                    "delta": {
                        "content": "你好",
                        "reasoning_content": "想一想",
                    }
                }
            ],
            "usage": {"total_tokens": 12},
        }
        content, reasoning, usage = extract_stream_delta(payload)
        self.assertEqual(content, "你好")
        self.assertEqual(reasoning, "想一想")
        self.assertEqual(usage, {"total_tokens": 12})

        self.assertEqual(extract_stream_delta({"choices": []}), ("", "", None))

    def test_extract_error(self) -> None:
        with self.assertRaises(ApiError):
            extract_stream_delta({"error": {"message": "bad key"}})

    def test_payload_thinking(self) -> None:
        settings = Settings()
        settings.thinking = True
        settings.reasoning_effort = "max"
        payload = build_payload(settings, [{"role": "user", "content": "hi"}])
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertTrue(payload["stream"])

        settings.thinking = False
        payload = build_payload(settings, [{"role": "user", "content": "hi"}])
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)

    def test_build_messages(self) -> None:
        settings = Settings()
        settings.system_prompt = "你是小鲸鱼"
        conversation = Conversation()
        conversation.add("user", "你好")
        messages = build_messages(settings, conversation)
        self.assertEqual(messages[0], {"role": "system", "content": "你是小鲸鱼"})
        self.assertEqual(messages[1], {"role": "user", "content": "你好"})

    def test_message_round_trip(self) -> None:
        message = Message("assistant", "回答", "思考", ts=1.5, cancelled=True)
        restored = Message.from_dict(message.to_dict())
        self.assertEqual(restored.content, "回答")
        self.assertEqual(restored.reasoning, "思考")
        self.assertTrue(restored.cancelled)


if __name__ == "__main__":
    unittest.main()
