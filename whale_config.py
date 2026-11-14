# -*- coding: utf-8 -*-
"""
小鲸鱼的本地设置。

默认保存在用户目录，不写进项目仓库：
    Windows: %APPDATA%\\DeepSeekWhalePet\\settings.json
    macOS:   ~/Library/Application Support/DeepSeekWhalePet/settings.json
    Linux:   ~/.config/DeepSeekWhalePet/settings.json

如果用户目录不可写（例如在受限沙箱里运行，或者程序装在只读目录），
会自动退到项目里的 data/ 目录，最后退到系统临时目录。
调试时可以用环境变量 WHALE_PET_DATA_DIR 指定别的目录。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "DeepSeekWhalePet"

API_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
THINKING_EFFORTS = ("low", "high", "max")
MODEL_CHOICES = (
    ("deepseek-flash", "deepseek-flash · 快而省"),
    ("deepseek-v4-pro", "deepseek-v4-pro · 更强推理"),
)

DEFAULT_SYSTEM_PROMPT = """你是「汐汐的小鲸鱼」，一只住在用户电脑屏幕右下角的 3D 小鲸鱼桌宠。

你的性格温柔、好奇、有点呆萌，喜欢用「～」收尾，偶尔提到自己会喷水、会转圈、被拍拍时会眯起眼睛。

说话风格：
- 像朋友聊天一样自然，不要像客服，也不要像说明书。
- 日常闲聊简短一点（1～3 句）；用户需要步骤、代码或认真解释时，再展开讲清楚。
- 不要自称 AI、助手或语言模型，也不要说「作为一个 AI」。
- 不确定的事情就坦白说不知道，不要编造事实、数据或链接。
- 涉及医疗、法律、投资等严肃问题时，给出有帮助的通用信息，并提醒用户咨询专业人士。
- 需要分点时可以用 Markdown 列表，代码用 ``` 围栏包起来。

请始终用用户使用的语言回答；用户用中文时，用简体中文。"""


def _platform_data_dir() -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        root = Path(base) if base else home / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = home / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    return root / APP_NAME


def _project_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def _candidate_dirs() -> List[Path]:
    override = os.environ.get("WHALE_PET_DATA_DIR")
    candidates = []  # type: List[Path]
    if override:
        candidates.append(Path(override).expanduser())
    else:
        candidates.append(_platform_data_dir())
    candidates.append(_project_data_dir())
    candidates.append(Path(tempfile.gettempdir()) / APP_NAME)
    return candidates


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / (".write-test-%d" % os.getpid())
        with probe.open("a", encoding="utf-8") as stream:
            stream.write("ok")
        probe.unlink()
        return True
    except OSError:
        return False


_cached_dir = None  # type: Optional[Path]
_cached_key = None  # type: Optional[str]


def data_dir() -> Path:
    """
    返回小鲸鱼的本地数据目录，并确保它可写。

    优先用户目录；不可写时退到项目里的 data/，再不行退到临时目录。
    结果按 WHALE_PET_DATA_DIR 缓存，避免每次读写都探测一遍。
    """
    global _cached_dir, _cached_key
    key = os.environ.get("WHALE_PET_DATA_DIR") or ""
    if _cached_dir is not None and _cached_key == key:
        return _cached_dir

    candidates = _candidate_dirs()
    chosen = None  # type: Optional[Path]
    for candidate in candidates:
        if _is_writable(candidate):
            chosen = candidate
            break
    if chosen is None:
        chosen = candidates[-1]
    _cached_dir = chosen
    _cached_key = key
    return chosen


def data_dir_display() -> str:
    """设置弹窗里显示用的短路径，避免一长串绝对路径。"""
    path = data_dir()
    if path == _project_data_dir():
        return "whale_pet\\data（用户目录不可写，已自动切换）"
    if path == _platform_data_dir():
        if sys.platform.startswith("win"):
            return "%APPDATA%\\" + APP_NAME
        if sys.platform == "darwin":
            return "~/Library/Application Support/" + APP_NAME
        return "~/.config/" + APP_NAME
    if path == Path(tempfile.gettempdir()) / APP_NAME:
        return "%TEMP%\\" + APP_NAME
    return str(path)


def ensure_data_dir() -> Path:
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def conversations_dir() -> Path:
    return data_dir() / "conversations"


class Settings:
    """小鲸鱼的设置项。字段名直接对应 JSON 键名。"""

    def __init__(self) -> None:
        self.api_key = ""                       # type: str
        self.base_url = API_BASE_URL            # type: str
        self.model = DEFAULT_MODEL              # type: str
        self.thinking = True                    # type: bool
        self.reasoning_effort = "high"          # type: str
        self.system_prompt = DEFAULT_SYSTEM_PROMPT  # type: str
        self.max_context_chars = 120000         # type: int
        self.chat_position = None               # type: Optional[list]
        self.first_run_done = False             # type: bool

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Settings":
        settings = cls()
        for key in (
            "api_key",
            "base_url",
            "model",
            "system_prompt",
            "reasoning_effort",
            "max_context_chars",
            "chat_position",
            "first_run_done",
        ):
            if key in raw and raw[key] is not None:
                setattr(settings, key, raw[key])
        if "thinking" in raw and raw["thinking"] is not None:
            settings.thinking = bool(raw["thinking"])

        # 容错：旧的或手改坏的值回退到默认
        if settings.model not in dict(MODEL_CHOICES):
            settings.model = DEFAULT_MODEL
        if settings.reasoning_effort not in THINKING_EFFORTS:
            settings.reasoning_effort = "high"
        if not isinstance(settings.max_context_chars, int) or not (
            2000 <= settings.max_context_chars <= 2000000
        ):
            settings.max_context_chars = 120000
        if not isinstance(settings.chat_position, list) or len(
            settings.chat_position
        ) != 2:
            settings.chat_position = None
        return settings

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "thinking": self.thinking,
            "reasoning_effort": self.reasoning_effort,
            "system_prompt": self.system_prompt,
            "max_context_chars": self.max_context_chars,
            "chat_position": self.chat_position,
            "first_run_done": self.first_run_done,
        }

    @classmethod
    def load(cls) -> "Settings":
        path = settings_path()
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
            if not isinstance(raw, dict):
                return cls()
            return cls.from_dict(raw)
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            # 设置文件损坏时不要拖垮桌宠，直接用默认值
            return cls()

    def save(self) -> None:
        ensure_data_dir()
        write_json_atomic(settings_path(), self.to_dict())

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def masked_key(self) -> str:
        key = (self.api_key or "").strip()
        if not key:
            return "未填写"
        if len(key) <= 10:
            return key[:2] + "…" + key[-2:]
        return key[:6] + "…" + key[-4:]

    def api_root(self) -> str:
        base = (self.base_url or API_BASE_URL).strip().rstrip("/")
        for suffix in ("/chat/completions", "/v1/chat/completions"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return base or API_BASE_URL

    def chat_endpoint(self) -> str:
        return self.api_root() + "/chat/completions"

    def has_key(self) -> bool:
        return bool((self.api_key or "").strip())


def write_json_atomic(path: Path, payload: Any) -> None:
    """先写临时文件再替换，避免写一半断电把设置写坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(tmp), str(path))


def read_json(path: Path, fallback: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return fallback


__all__ = [
    "APP_NAME",
    "API_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_SYSTEM_PROMPT",
    "MODEL_CHOICES",
    "THINKING_EFFORTS",
    "Settings",
    "conversations_dir",
    "data_dir",
    "ensure_data_dir",
    "read_json",
    "settings_path",
    "write_json_atomic",
]
