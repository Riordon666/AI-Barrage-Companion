"""Unit tests for screen_context module — classification logic."""

from app.core.screen_context import _classify, ScreenContext, capture_screen_context


class TestClassify:
    """Test application classification from window title."""

    def test_classify_vscode(self) -> None:
        cat, app, desc = _classify(
            "main.py - AI-Barrage-Companion - Visual Studio Code", "Code.exe",
        )
        assert cat == "coding"
        assert desc == "正在 VS Code 中编写代码"

    def test_classify_pycharm(self) -> None:
        cat, app, desc = _classify("app - PyCharm Professional 2024.1", "")
        assert cat == "coding"

    def test_classify_chrome(self) -> None:
        cat, app, desc = _classify("YouTube - Google Chrome", "")
        assert cat == "browser"
        assert "Chrome" in desc

    def test_classify_game(self) -> None:
        cat, app, desc = _classify("League of Legends (TM) Client", "")
        assert cat == "game"
        assert "英雄联盟" in desc

    def test_classify_premiere(self) -> None:
        cat, app, desc = _classify("项目.prproj - Adobe Premiere Pro", "")
        assert cat == "media"

    def test_classify_unknown_app_falls_back_to_title(self) -> None:
        cat, app, desc = _classify("神秘应用 v3.14", "")
        assert cat == "unknown"
        assert "神秘应用" in desc

    def test_classify_empty_title(self) -> None:
        cat, app, desc = _classify("", "")
        assert cat == "unknown"
        assert app == "未知应用"

    def test_process_only_match(self) -> None:
        """When the window title is generic but process name is known."""
        from app.core.screen_context import _PROCESS_SIGNATURES

        # devenv.exe should map to Visual Studio
        assert "Visual Studio" in _PROCESS_SIGNATURES.get("devenv.exe", "")

    def test_mock_barrage_includes_screen_context_in_prompt(self) -> None:
        """Verify that the AI prompt includes screen_context when present."""
        from app.core.ai_service import OpenAICompatibleBarrageService
        from app.models import GenerationRequest, SceneSummary

        scene = SceneSummary(
            activity="active",
            pace="normal",
            event="normal",
            confidence=0.7,
            screen_context="正在 VS Code 中编写代码",
        )

        request = GenerationRequest(
            scene=scene,
            density="medium",
            personas=["support", "fun"],
            count=2,
        )

        prompt = OpenAICompatibleBarrageService._user_prompt(request)
        assert "正在 VS Code 中编写代码" in prompt
        assert "请根据上述屏幕内容生成弹幕" in prompt

    def test_prompt_without_screen_context_omits_context_section(self) -> None:
        """When screen_context is empty, the prompt should NOT include context section."""
        from app.core.ai_service import OpenAICompatibleBarrageService
        from app.models import GenerationRequest, SceneSummary

        scene = SceneSummary(
            activity="idle", pace="idle", event="idle", confidence=0.1,
        )
        request = GenerationRequest(
            scene=scene, density="low", personas=["troll"], count=1,
        )
        prompt = OpenAICompatibleBarrageService._user_prompt(request)
        assert "请根据上述屏幕内容生成弹幕" not in prompt


class TestScreenContextDataclass:
    def test_is_meaningful_true(self) -> None:
        ctx = ScreenContext(
            window_title="VS Code",
            app_name="Visual Studio Code",
            app_category="coding",
            description="正在 VS Code 中编写代码",
        )
        assert ctx.is_meaningful is True

    def test_is_meaningful_false(self) -> None:
        ctx = ScreenContext(
            window_title="",
            app_name="未知应用",
            app_category="unknown",
            description="正在使用电脑",
        )
        assert ctx.is_meaningful is False


class TestRealCapture:
    """Smoke test: verify capture_screen_context() runs without crashing."""

    def test_capture_returns_valid_context(self) -> None:
        ctx = capture_screen_context()
        assert isinstance(ctx, ScreenContext)
        assert isinstance(ctx.window_title, str)
        assert isinstance(ctx.app_category, str)
        assert isinstance(ctx.description, str)
