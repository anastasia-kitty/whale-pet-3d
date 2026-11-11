# -*- coding: utf-8 -*-
"""
对话的本地存储。

每段对话一个 JSON 文件，放在数据目录的 conversations/ 下：
    conversations/20261109-132401-ab12cd.json

这样即使某一段对话写坏了，也不会影响其他对话；也方便直接备份。
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from whale_config import conversations_dir, read_json, write_json_atomic

TITLE_MAX_CHARS = 22
GROUP_LABELS = ("今天", "昨天", "本周", "更早")


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def _clean_title(text: str) -> str:
    line = " ".join((text or "").strip().split())
    if not line:
        return "新的对话"
    if len(line) > TITLE_MAX_CHARS:
        line = line[:TITLE_MAX_CHARS].rstrip() + "…"
    return line


class Message:
    """一条对话消息。"""

    def __init__(
        self,
        role: str,
        content: str = "",
        reasoning: str = "",
        ts: Optional[float] = None,
        error: str = "",
        cancelled: bool = False,
    ) -> None:
        self.role = role
        self.content = content
        self.reasoning = reasoning
        self.ts = ts if ts is not None else _now()
        self.error = error
        self.cancelled = cancelled

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
        }
        if self.reasoning:
            payload["reasoning"] = self.reasoning
        if self.error:
            payload["error"] = self.error
        if self.cancelled:
            payload["cancelled"] = True
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Message":
        return cls(
            role=str(raw.get("role", "assistant")),
            content=str(raw.get("content", "")),
            reasoning=str(raw.get("reasoning", "")),
            ts=float(raw.get("ts", _now())),
            error=str(raw.get("error", "")),
            cancelled=bool(raw.get("cancelled", False)),
        )


class Conversation:
    """一段对话，包含若干条消息。"""

    def __init__(
        self,
        conv_id: Optional[str] = None,
        title: str = "新的对话",
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        messages: Optional[List[Message]] = None,
    ) -> None:
        now = _now()
        self.id = conv_id or _new_id()
        self.title = title or "新的对话"
        self.created_at = created_at if created_at is not None else now
        self.updated_at = updated_at if updated_at is not None else now
        self.messages = messages if messages is not None else []  # type: List[Message]

    # ------------------------------------------------------------------
    def add(
        self,
        role: str,
        content: str = "",
        reasoning: str = "",
        error: str = "",
        cancelled: bool = False,
    ) -> Message:
        message = Message(
            role=role,
            content=content,
            reasoning=reasoning,
            error=error,
            cancelled=cancelled,
        )
        self.messages.append(message)
        self.updated_at = message.ts
        if role == "user" and self.title in ("新的对话", "", None):
            self.title = _clean_title(content)
        return message

    def history_for_api(self, max_chars: int = 120000) -> List[Dict[str, str]]:
        """挑出要发给模型的历史消息：跳过出错/空消息，从最近往前塞。"""
        usable = [
            m
            for m in self.messages
            if m.role in ("user", "assistant")
            and (m.content or "").strip()
            and not m.error
        ]
        selected = []
        total = 0
        for message in reversed(usable):
            cost = len(message.content) + 32
            if selected and total + cost > max_chars:
                break
            selected.append(
                {"role": message.role, "content": message.content.strip()}
            )
            total += cost
        selected.reverse()
        return selected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Conversation":
        raw_messages = raw.get("messages") or []
        messages = [
            Message.from_dict(item)
            for item in raw_messages
            if isinstance(item, dict)
        ]
        return cls(
            conv_id=str(raw.get("id") or _new_id()),
            title=str(raw.get("title") or "新的对话"),
            created_at=float(raw.get("created_at", _now())),
            updated_at=float(raw.get("updated_at", _now())),
            messages=messages,
        )

    def preview(self) -> str:
        for message in reversed(self.messages):
            text = (message.content or "").strip()
            if text:
                return " ".join(text.split())
        return "还没有聊过天"


def group_label(timestamp: float, now: Optional[float] = None) -> str:
    """把时间戳归入「今天 / 昨天 / 本周 / 更早」。"""
    moment = datetime.fromtimestamp(timestamp)
    today = date.today() if now is None else datetime.fromtimestamp(now).date()
    delta = (today - moment.date()).days
    if delta <= 0:
        return GROUP_LABELS[0]
    if delta == 1:
        return GROUP_LABELS[1]
    week_start = today - timedelta(days=today.weekday())
    if moment.date() >= week_start:
        return GROUP_LABELS[2]
    return GROUP_LABELS[3]


class ConversationStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else conversations_dir()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录不可写时仍然允许聊天，只是保存会失败并在界面上提示
            pass
        self._cache = {}  # type: Dict[str, Conversation]

    # ------------------------------------------------------------------
    def path_for(self, conv_id: str) -> Path:
        safe = "".join(ch for ch in conv_id if ch.isalnum() or ch in "-_")
        return self.root / (safe + ".json")

    def list_conversations(self) -> List[Conversation]:
        """按最近更新时间倒序返回所有对话。"""
        found = {}  # type: Dict[str, Conversation]
        try:
            files = list(self.root.glob("*.json"))
        except OSError:
            files = []
        for path in files:
            raw = read_json(path, None)
            if not isinstance(raw, dict):
                continue
            try:
                conversation = Conversation.from_dict(raw)
            except (TypeError, ValueError):
                continue
            # 文件名是权威 id，防止 JSON 里的 id 被手改乱
            conversation.id = path.stem
            found[conversation.id] = conversation
        self._cache.update(found)
        return sorted(found.values(), key=lambda c: c.updated_at, reverse=True)

    def get(self, conv_id: str) -> Optional[Conversation]:
        if conv_id in self._cache:
            return self._cache[conv_id]
        raw = read_json(self.path_for(conv_id), None)
        if not isinstance(raw, dict):
            return None
        try:
            conversation = Conversation.from_dict(raw)
        except (TypeError, ValueError):
            return None
        conversation.id = conv_id
        self._cache[conv_id] = conversation
        return conversation

    def create(self) -> Conversation:
        conversation = Conversation()
        self._cache[conversation.id] = conversation
        self.save(conversation)
        return conversation

    def save(self, conversation: Conversation) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path_for(conversation.id), conversation.to_dict())
        self._cache[conversation.id] = conversation

    def delete(self, conv_id: str) -> None:
        self._cache.pop(conv_id, None)
        try:
            self.path_for(conv_id).unlink()
        except FileNotFoundError:
            pass

    def rename(self, conv_id: str, title: str) -> Optional[Conversation]:
        conversation = self.get(conv_id)
        if conversation is None:
            return None
        conversation.title = _clean_title(title) if title.strip() else conversation.title
        conversation.updated_at = _now()
        self.save(conversation)
        return conversation

    def latest_or_create(self) -> Conversation:
        conversations = self.list_conversations()
        if conversations:
            return conversations[0]
        return self.create()

    # ------------------------------------------------------------------
    def group(self, conversations: Iterable[Conversation]) -> List[Any]:
        """返回 [(分组名, [对话...]), ...]，顺序固定。"""
        buckets = {}  # type: Dict[str, List[Conversation]]
        for conversation in conversations:
            label = group_label(conversation.updated_at)
            buckets.setdefault(label, []).append(conversation)
        return [(label, buckets[label]) for label in GROUP_LABELS if label in buckets]


__all__ = [
    "Conversation",
    "ConversationStore",
    "GROUP_LABELS",
    "Message",
    "group_label",
]
