# -*- coding: utf-8 -*-
"""
DeepSeek 对话接口：只依赖 Python 标准库 + PyQt5 的 QThread。

为什么不用 requests / openai：
桌宠原本只依赖 PyQt5，用 urllib 就能完成 HTTPS + SSE 流式读取，
少一个第三方依赖，打包和换电脑都更省心。

线程模型：
    ChatWorker(QThread) 在后台读流，通过 Qt 信号把增量文本发回主线程；
    点「停止」时 cancel() 会关闭连接，已经收到的内容仍然会保存。
"""

from __future__ import annotations

import json
import socket
import ssl
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

from PyQt5.QtCore import QThread, pyqtSignal

from whale_config import Settings
from whale_store import Conversation

USER_AGENT = "DeepSeekWhalePet/1.0 (PyQt5)"

STATUS_HINTS = {
    400: "请求格式有点问题",
    401: "API Key 无效或已失效",
    402: "账户余额不足",
    403: "这个 API Key 没有访问权限",
    404: "接口地址不对，检查一下设置里的 API 地址",
    422: "请求参数未被接受",
    429: "请求太频繁或超出额度，稍等一下再试",
    500: "DeepSeek 服务器开小差了",
    502: "网关错误",
    503: "服务暂时不可用，稍后再试",
    504: "网关超时",
}


class ApiError(Exception):
    """带中文提示的接口错误。"""


def friendly_http_error(status: int, body: bytes) -> str:
    hint = STATUS_HINTS.get(status, "请求失败")
    detail = ""
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("type") or "")
            elif isinstance(err, str):
                detail = err
            elif payload.get("message"):
                detail = str(payload["message"])
    except ValueError:
        detail = body.decode("utf-8", "replace").strip()[:160]
    text = f"{hint}（HTTP {status}）"
    if detail:
        text += f"\n{detail}"
    return text


def friendly_network_error(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLError):
        return "HTTPS 证书验证失败，请检查系统时间或网络代理设置。"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "连接超时了，检查一下网络，或者稍后再试。"
    if isinstance(exc, error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.gaierror):
            return "找不到服务器，可能是断网或 DNS 有问题。"
        if isinstance(reason, ssl.SSLError):
            return "HTTPS 证书验证失败，请检查系统时间或网络代理设置。"
        return f"网络连接失败：{reason}"
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "连接被断开了，稍后再试一次吧。"
    return f"出了点小问题：{exc}"


def parse_sse_line(line: str) -> Optional[str]:
    """从一行 SSE 文本里取出 data 内容；注释 / 空行返回 None。"""
    if not line:
        return None
    stripped = line.strip("\r\n")
    if not stripped or stripped.startswith(":"):
        return None
    if stripped.startswith("data:"):
        return stripped[5:].strip()
    return None


def extract_stream_delta(
    payload: Dict[str, Any]
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """解析一个流式 chunk，返回 (content 增量, reasoning 增量, usage)。"""
    if not isinstance(payload, dict):
        return "", "", None
    if payload.get("error"):
        err = payload["error"]
        message = ""
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("type") or "")
        else:
            message = str(err)
        raise ApiError(message or "接口返回了错误")

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", "", usage
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return "", "", usage
    content = delta.get("content") or ""
    reasoning = delta.get("reasoning_content") or ""
    return str(content), str(reasoning), usage


def build_messages(
    settings: Settings, conversation: Conversation
) -> List[Dict[str, str]]:
    messages = []  # type: List[Dict[str, str]]
    system_prompt = (settings.system_prompt or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(
        conversation.history_for_api(max_chars=settings.max_context_chars)
    )
    return messages


def build_payload(
    settings: Settings,
    messages: List[Dict[str, str]],
    stream: bool = True,
) -> Dict[str, Any]:
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": stream,
    }
    if settings.thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = settings.reasoning_effort
    else:
        payload["thinking"] = {"type": "disabled"}
    return payload


def _make_request(settings: Settings, payload: Dict[str, Any]) -> request.Request:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if payload.get("stream") else "application/json",
        "Authorization": "Bearer " + (settings.api_key or "").strip(),
        "User-Agent": USER_AGENT,
    }
    return request.Request(
        settings.chat_endpoint(),
        data=body,
        headers=headers,
        method="POST",
    )


class ChatWorker(QThread):
    """后台读取流式回答。"""

    delta = pyqtSignal(str)
    reasoning = pyqtSignal(str)
    # content, reasoning, usage, cancelled
    completed = pyqtSignal(str, str, dict, bool)
    failed = pyqtSignal(str)

    def __init__(self, settings: Settings, messages: List[Dict[str, str]]) -> None:
        super().__init__()
        self.settings = settings
        self.messages = messages
        self._cancel = threading.Event()
        self._response = None  # type: Optional[Any]

    def cancel(self) -> None:
        self._cancel.set()
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        content_parts = []  # type: List[str]
        reasoning_parts = []  # type: List[str]
        usage = {}  # type: Dict[str, Any]
        payload = build_payload(self.settings, self.messages, stream=True)

        try:
            req = _make_request(self.settings, payload)
            context = ssl.create_default_context()
            self._response = request.urlopen(req, timeout=180, context=context)

            while not self._cancel.is_set():
                raw = self._response.readline()
                if not raw:
                    break
                data = parse_sse_line(raw.decode("utf-8", "replace"))
                if data is None:
                    continue
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                piece, thought, chunk_usage = extract_stream_delta(chunk)
                if chunk_usage:
                    usage = chunk_usage
                if thought:
                    reasoning_parts.append(thought)
                    self.reasoning.emit(thought)
                if piece:
                    content_parts.append(piece)
                    self.delta.emit(piece)

            cancelled = self._cancel.is_set()
            self.completed.emit(
                "".join(content_parts),
                "".join(reasoning_parts),
                usage,
                cancelled,
            )
        except error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            if self._cancel.is_set():
                self.completed.emit(
                    "".join(content_parts), "".join(reasoning_parts), usage, True
                )
            else:
                self.failed.emit(friendly_http_error(exc.code, body))
        except ApiError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - 网络异常类型很多，统一转成提示
            if self._cancel.is_set():
                self.completed.emit(
                    "".join(content_parts), "".join(reasoning_parts), usage, True
                )
            else:
                self.failed.emit(friendly_network_error(exc))
        finally:
            response = self._response
            self._response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass


class KeyTestWorker(QThread):
    """点「测试连接」时，用一条极短消息验证 Key / 模型 / 地址。"""

    done = pyqtSignal(bool, str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._cancel = threading.Event()
        self._response = None  # type: Optional[Any]

    def cancel(self) -> None:
        self._cancel.set()
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def run(self) -> None:
        snapshot = self.settings.copy()
        snapshot.thinking = False
        payload = {
            "model": snapshot.model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 8,
            "thinking": {"type": "disabled"},
        }
        try:
            req = _make_request(snapshot, payload)
            context = ssl.create_default_context()
            self._response = request.urlopen(req, timeout=30, context=context)
            raw = self._response.read()
            if self._cancel.is_set():
                return
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                data = {}
            model = ""
            if isinstance(data, dict):
                model = str(data.get("model") or "")
            label = snapshot.model
            if model and model != snapshot.model:
                label = f"{snapshot.model}（服务器：{model}）"
            self.done.emit(True, f"连接成功，{label} 可以正常对话～")
        except error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            if not self._cancel.is_set():
                self.done.emit(False, friendly_http_error(exc.code, body))
        except Exception as exc:  # noqa: BLE001
            if not self._cancel.is_set():
                self.done.emit(False, friendly_network_error(exc))
        finally:
            response = self._response
            self._response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass


__all__ = [
    "ApiError",
    "ChatWorker",
    "KeyTestWorker",
    "build_messages",
    "build_payload",
    "extract_stream_delta",
    "friendly_http_error",
    "friendly_network_error",
    "parse_sse_line",
]
