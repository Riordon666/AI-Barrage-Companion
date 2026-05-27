"""Extract real screen context (window title, app type) for AI prompts.

This replaces the old "activity=active pace=fast" approach with meaningful
text descriptions like "用户正在 VS Code 中编写代码", giving the AI model
actual context to generate barrages that fit what's happening on screen.
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Windows API declarations (ctypes — no pywin32 dependency)
# ---------------------------------------------------------------------------

_user32: Any = None


def _get_user32() -> Any:
    global _user32
    if _user32 is None:
        _user32 = ctypes.windll.user32
    return _user32


def _foreground_window_title() -> str:
    """Return the title of the foreground window, or '' on error."""
    if sys.platform != "win32":
        return ""
    u32 = _get_user32()
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = u32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    u32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _foreground_process_name() -> str:
    """Return the executable name of the foreground process (e.g. 'Code.exe')."""
    if sys.platform != "win32":
        return ""
    u32 = _get_user32()
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return ""

    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    try:
        import psutil  # optional — much better process detection

        proc = psutil.Process(pid.value)
        return proc.name() or ""
    except ImportError:
        pass
    except Exception:
        pass

    return ""  # no psutil → can't resolve process name


# ---------------------------------------------------------------------------
# Application classification
# ---------------------------------------------------------------------------

# (keyword, category, human-readable prefix) — first match wins.
_APP_SIGNATURES: list[tuple[str, str, str]] = [
    # Games
    ("League of Legends", "game", "正在玩《英雄联盟》"),
    ("VALORANT", "game", "正在玩《VALORANT》"),
    ("Counter-Strike", "game", "正在玩 CS"),
    ("Dota 2", "game", "正在玩 Dota 2"),
    ("原神", "game", "正在玩原神"),
    ("崩坏", "game", "正在玩崩坏系列"),
    ("Minecraft", "game", "正在玩 Minecraft"),
    ("Elden Ring", "game", "正在玩《艾尔登法环》"),
    ("Steam", "game", "正在 Steam 上浏览"),
    # IDEs / coding
    ("Visual Studio Code", "coding", "正在 VS Code 中编写代码"),
    ("Code.exe", "coding", "正在 VS Code 中编写代码"),
    ("PyCharm", "coding", "正在 PyCharm 中编写代码"),
    ("IntelliJ IDEA", "coding", "正在 IntelliJ 中编写代码"),
    ("Cursor", "coding", "正在 Cursor 中编写代码"),
    ("Sublime Text", "coding", "正在 Sublime 中编辑文本"),
    ("Vim", "coding", "正在 Vim 中编辑"),
    ("Neovim", "coding", "正在 Neovim 中编辑"),
    ("Notepad++", "coding", "正在 Notepad++ 中编辑"),
    ("Android Studio", "coding", "正在 Android Studio 中开发"),
    ("Xcode", "coding", "正在 Xcode 中开发"),
    # Terminal
    ("Windows PowerShell", "coding", "正在终端中操作"),
    ("Command Prompt", "coding", "正在命令行中操作"),
    ("Terminal", "coding", "正在终端中操作"),
    ("WSL", "coding", "正在 WSL 终端中操作"),
    # Browsers
    ("Google Chrome", "browser", "正在 Chrome 浏览网页"),
    ("Mozilla Firefox", "browser", "正在 Firefox 浏览网页"),
    ("Microsoft Edge", "browser", "正在 Edge 浏览网页"),
    # Media / creative
    ("Adobe Premiere", "media", "正在剪辑视频"),
    ("DaVinci Resolve", "media", "正在剪辑视频"),
    ("Adobe Photoshop", "media", "正在使用 PS 修图"),
    ("Adobe After Effects", "media", "正在做动效"),
    ("Blender", "media", "正在 Blender 中建模"),
    ("Figma", "media", "正在 Figma 中设计"),
    ("Spotify", "media", "正在听音乐"),
    ("网易云音乐", "media", "正在听音乐"),
    ("QQ音乐", "media", "正在听音乐"),
    # Office / productivity
    ("Microsoft Word", "office", "正在写文档"),
    ("Microsoft Excel", "office", "正在处理表格"),
    ("Microsoft PowerPoint", "office", "正在做 PPT"),
    ("WPS", "office", "正在使用 WPS 办公"),
    ("Obsidian", "office", "正在 Obsidian 中记笔记"),
    ("Notion", "office", "正在 Notion 中工作"),
    # Chat
    ("微信", "chat", "正在微信聊天"),
    ("WeChat", "chat", "正在微信聊天"),
    ("QQ", "chat", "正在 QQ 聊天"),
    ("Discord", "chat", "正在 Discord 聊天"),
    ("Telegram", "chat", "正在 Telegram 聊天"),
    ("Slack", "chat", "正在 Slack 工作交流"),
    # File manager / system
    ("文件资源管理器", "system", "正在浏览文件"),
    ("File Explorer", "system", "正在浏览文件"),
    ("任务管理器", "system", "正在查看任务管理器"),
    ("Task Manager", "system", "正在查看任务管理器"),
]

# Process-name-only matches (when window title doesn't help).
_PROCESS_SIGNATURES: dict[str, str] = {
    "devenv.exe": "正在 Visual Studio 中开发",
    "code.exe": "正在 VS Code 中编写代码",
    "pycharm64.exe": "正在 PyCharm 中编写代码",
    "idea64.exe": "正在 IntelliJ 中编写代码",
    "notepad++.exe": "正在 Notepad++ 中编辑",
    "obs64.exe": "正在 OBS 中录制/直播",
}


def _classify(title: str, process: str) -> tuple[str, str, str]:
    """Return (category, app_name, human_description) from title + process."""
    for keyword, category, description in _APP_SIGNATURES:
        if keyword.lower() in title.lower():
            return category, keyword, description

    # Fall back to process-name-only classification
    desc = _PROCESS_SIGNATURES.get(process.lower(), "")
    if desc:
        return "coding", process, desc

    if title:
        # Unknown application — still send the title so AI has context
        return "unknown", title, f"正在使用 {title}"
    return "unknown", "未知应用", "正在使用电脑"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ScreenContext:
    """Lightweight snapshot of what the user is doing right now."""

    window_title: str
    app_name: str
    app_category: str  # game / coding / browser / media / office / chat / system / unknown
    description: str   # human-readable summary for AI prompt
    warnings: list[str] = field(default_factory=list)

    @property
    def is_meaningful(self) -> bool:
        return bool(self.window_title.strip())


def capture_screen_context() -> ScreenContext:
    """Grab the active window title, classify it, and return a context summary.

    This is purely local — no screenshot, no OCR, no network.
    """
    title = _foreground_window_title()
    process = _foreground_process_name()
    category, app_name, description = _classify(title, process)

    warnings: list[str] = []
    if not title:
        warnings.append("未能获取活动窗口标题（可能处于全屏游戏或桌面）")

    return ScreenContext(
        window_title=title,
        app_name=app_name,
        app_category=category,
        description=description,
        warnings=warnings,
    )
