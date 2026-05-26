"""Control panel for runtime settings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config.provider_presets import PROVIDER_BY_KEY, SUPPORTED_PROVIDERS, provider_for_key
from app.core.logger import get_emitter, get_logger
from app.models import ApiConfig, AppSettings

logger = get_logger("control_panel")


class ControlPanel(QWidget):
    """Expose generation, display, and API controls."""

    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()
    # Thread-safe signal for connection test (Qt signals are thread-safe)
    connectionResult = Signal(bool, str)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumWidth(480)
        self._settings = settings
        self._provider_keys = [provider.key for provider in SUPPORTED_PROVIDERS]
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conn_test")
        self._connection_timeout: QTimer | None = None
        self._status_message = ""
        self._status_type = "info"

        self._build_controls()
        self._apply_styles()
        self._load_settings(settings)
        self._connect_logger()

    def _on_connection_result(self, success: bool, message: str) -> None:
        """Handle connection test result on the main thread."""
        if self._connection_timeout is not None:
            self._connection_timeout.stop()
            self._connection_timeout = None

        self._test_connection_button.setEnabled(True)
        self._test_connection_button.setText("测试连接")
        self._connection_status.setVisible(True)
        self._connection_status.setText(message)
        if success:
            self._connection_status.setStyleSheet("color: #1f6f5b; font-weight: 600;")
        else:
            self._connection_status.setStyleSheet("color: #9a3f3f; font-weight: 600;")
        self.set_status(message, "success" if success else "error")

    def _build_controls(self) -> None:
        self._pause_button = QPushButton("暂停")
        self._pause_button.setCheckable(True)
        self._pause_button.toggled.connect(self._on_pause_toggled)
        self._pause_button.setProperty("class", "primary")

        self._density = QComboBox()
        self._density.addItems(["low", "medium", "high"])
        self._density.currentTextChanged.connect(self.densityChanged.emit)

        self._display_area = QSlider(Qt.Orientation.Horizontal)
        self._display_area.setRange(0, 100)
        self._display_area.valueChanged.connect(self.displayAreaChanged.emit)
        self._display_area_value = QLabel("65%")
        self._display_area.valueChanged.connect(
            lambda value: self._display_area_value.setText(f"{value}%")
        )

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 48)
        self._font_size.valueChanged.connect(self.fontSizeChanged.emit)

        # --- Provider ---
        self._provider = QComboBox()
        for provider in SUPPORTED_PROVIDERS:
            self._provider.addItem(provider.label, provider.key)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)

        self._base_url = QLineEdit()
        self._model = QComboBox()
        self._model.setEditable(True)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("本地 Ollama 或自定义无 Key 可留空")

        self._mock_when_missing = QCheckBox("无 API Key 时使用模拟弹幕")

        self._test_connection_button = QPushButton("测试连接")
        self._test_connection_button.setProperty("class", "secondary")
        self._test_connection_button.clicked.connect(self._test_connection)

        self._connection_status = QLabel("")
        self._connection_status.setObjectName("connStatus")
        self._connection_status.setVisible(False)

        self._save_button = QPushButton("保存配置")
        self._save_button.setProperty("class", "primary")
        self._save_button.clicked.connect(self._save_settings)

        self._quit_button = QPushButton("退出")
        self._quit_button.setProperty("class", "danger")
        self._quit_button.clicked.connect(self.quitRequested.emit)

        # --- Status bar ---
        self._status_bar = QLabel("[i] 就绪")
        self._status_bar.setObjectName("statusBar")

        # --- Log area ---
        self._log_display = QLabel()
        self._log_display.setObjectName("logDisplay")
        self._log_display.setWordWrap(True)
        self._log_display.setMaximumHeight(60)
        self._log_display.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._log_display.setVisible(False)

        self._toggle_log_button = QPushButton("显示日志")
        self._toggle_log_button.setProperty("class", "text")
        self._toggle_log_button.setFixedHeight(22)
        self._toggle_log_button.clicked.connect(self._toggle_log)

        # Wire thread-safe signal
        self.connectionResult.connect(self._on_connection_result)

        # --- Layout ---
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(self._title())
        layout.addWidget(self._runtime_group())
        layout.addWidget(self._display_group())
        layout.addWidget(self._provider_group())

        buttons = QHBoxLayout()
        buttons.addWidget(self._pause_button)
        buttons.addStretch(1)
        buttons.addWidget(self._save_button)
        buttons.addWidget(self._quit_button)
        layout.addLayout(buttons)

        layout.addWidget(self._status_bar)
        log_row = QHBoxLayout()
        log_row.addWidget(self._toggle_log_button)
        log_row.addStretch()
        layout.addLayout(log_row)
        layout.addWidget(self._log_display)

        self.setLayout(layout)

    # ---- UI components ----

    def _title(self) -> QWidget:
        frame = QFrame()
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        title = QLabel("AI Barrage Companion")
        title.setObjectName("title")
        subtitle = QLabel("虚拟观众弹幕控制台")
        subtitle.setObjectName("subtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        frame.setLayout(box)
        return frame

    def _runtime_group(self) -> QGroupBox:
        group = QGroupBox("运行")
        form = QFormLayout()
        form.addRow("弹幕密度", self._density)
        form.addRow("", self._mock_when_missing)
        group.setLayout(form)
        return group

    def _display_group(self) -> QGroupBox:
        group = QGroupBox("显示")
        form = QFormLayout()
        area_row = QHBoxLayout()
        area_row.addWidget(self._display_area)
        area_row.addWidget(self._display_area_value)
        form.addRow("显示区域", area_row)
        form.addRow("字体大小", self._font_size)
        group.setLayout(form)
        return group

    def _provider_group(self) -> QGroupBox:
        group = QGroupBox("AI 提供商")
        form = QFormLayout()
        form.addRow("提供商", self._provider)
        form.addRow("Base URL", self._base_url)
        form.addRow("模型", self._model)
        form.addRow("API Key", self._api_key)

        test_row = QHBoxLayout()
        test_row.addWidget(self._test_connection_button)
        test_row.addWidget(self._connection_status)
        test_row.addStretch()
        form.addRow("", test_row)

        group.setLayout(form)
        return group

    # ---- Actions ----

    def _test_connection(self) -> None:
        provider_key = str(self._provider.currentData() or "custom")
        preset = provider_for_key(provider_key)
        base_url = self._base_url.text().strip()
        api_key = self._api_key.text().strip()
        model = self._model.currentText().strip() or (preset.models[0] if preset else "")

        if not base_url:
            self._on_connection_result(False, "Base URL 为空")
            return

        self._test_connection_button.setEnabled(False)
        self._test_connection_button.setText("测试中...")
        self._connection_status.setVisible(True)
        self._connection_status.setText("连接中...")
        self._connection_status.setStyleSheet("color: #8b8b8b; font-weight: 600;")
        self.set_status("连接测试中...", "info")

        # Safety timeout: re-enable after 15 s in case thread hangs
        self._connection_timeout = QTimer(self)
        self._connection_timeout.setSingleShot(True)
        self._connection_timeout.timeout.connect(
            lambda: self._on_connection_result(False, "连接超时 (15 秒)")
        )
        self._connection_timeout.start(15000)

        self._executor.submit(self._do_connection_test, base_url, api_key, model)

    def _do_connection_test(self, base_url: str, api_key: str, model: str) -> None:
        """Background thread for connection test (uses thread-safe signal emit)."""
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model or "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0)) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    self.connectionResult.emit(True, f"连接成功 ({model})")
                    logger.info("API 连接测试成功: %s | model=%s", base_url, model)
                else:
                    detail = resp.text[:80]
                    self.connectionResult.emit(False, f"HTTP {resp.status_code}: {detail}")
                    logger.warning("API 连接失败: %s | status=%s", base_url, resp.status_code)
        except httpx.TimeoutException:
            self.connectionResult.emit(False, "连接超时 (8 秒)")
            logger.warning("API 连接超时: %s", base_url)
        except httpx.ConnectError:
            self.connectionResult.emit(False, "无法连接，请检查 URL 或网络")
            logger.warning("API 无法连接: %s", base_url)
        except Exception as exc:
            self.connectionResult.emit(False, str(exc)[:60])
            logger.error("API 连接异常: %s | %s", base_url, exc)

    def _save_settings(self) -> None:
        provider_key = str(self._provider.currentData() or "custom")
        preset = PROVIDER_BY_KEY.get(provider_key)
        api_key = self._api_key.text().strip()
        base_url = self._base_url.text().strip()
        model = self._model.currentText().strip()
        api = None
        if api_key or provider_key in {"ollama", "custom"} or not self._mock_when_missing.isChecked():
            api = ApiConfig(
                provider=provider_key,
                base_url=base_url or (preset.base_url if preset else ""),
                api_key=api_key,
                model=model or (preset.models[0] if preset else ""),
            )

        self._settings.density = self._density.currentText()  # type: ignore[assignment]
        self._settings.api = api
        self._settings.use_mock_when_api_missing = self._mock_when_missing.isChecked()
        self._settings.display_area_percent = self._display_area.value()
        self._settings.barrage_font_size = self._font_size.value()
        self.settingsSaved.emit(self._settings)

        # Visual feedback
        self._save_button.setText("[ok] 已保存")
        self._save_button.setStyleSheet(
            "QPushButton { background: #1f6f5b; border: 1px solid #1f6f5b;"
            " border-radius: 6px; padding: 8px 14px; color: white; }"
        )
        self.set_status("配置已保存", "success")
        logger.info("配置已保存: density=%s, provider=%s", self._settings.density, provider_key)

        QTimer.singleShot(1500, self._restore_save_button)

    def _restore_save_button(self) -> None:
        self._save_button.setText("保存配置")
        self._save_button.setStyleSheet("")

    def set_status(self, message: str, msg_type: str = "info") -> None:
        self._status_message = message
        self._status_type = msg_type
        colors = {"info": "#66706a", "success": "#1f6f5b", "error": "#9a3f3f"}
        prefix = {"info": "[i]", "success": "[ok]", "error": "[!]"}
        self._status_bar.setText(f"{prefix.get(msg_type, '[i]')} {message}")
        self._status_bar.setStyleSheet(f"color: {colors.get(msg_type, '#66706a')}; font-size: 12px;")

    def _toggle_log(self) -> None:
        visible = not self._log_display.isVisible()
        self._log_display.setVisible(visible)
        self._toggle_log_button.setText("隐藏日志" if visible else "显示日志")

    def _connect_logger(self) -> None:
        get_emitter().newLog.connect(self._on_log_message)

    def _on_log_message(self, message: str) -> None:
        current = self._log_display.text()
        lines = (current + "\n" + message).splitlines()
        if len(lines) > 100:
            lines = lines[-100:]
        self._log_display.setText("\n".join(lines))

    # ---- Helpers ----

    def _load_settings(self, settings: AppSettings) -> None:
        self._density.setCurrentText(settings.density)
        self._display_area.setValue(settings.display_area_percent)
        self._font_size.setValue(settings.barrage_font_size)
        self._mock_when_missing.setChecked(settings.use_mock_when_api_missing)

        provider_key = settings.api.provider if settings.api else "custom"
        if provider_key in self._provider_keys:
            provider_index = self._provider_keys.index(provider_key)
        else:
            provider_index = self._provider_keys.index("custom")
        self._provider.setCurrentIndex(provider_index)
        self._on_provider_changed(provider_index)

        if settings.api:
            self._base_url.setText(settings.api.base_url)
            if settings.api.model:
                self._model.setCurrentText(settings.api.model)
                le = self._model.lineEdit()
                if le is not None:
                    le.setText(settings.api.model)
            self._api_key.setText(settings.api.api_key)

    def _on_provider_changed(self, index: int) -> None:
        provider_key = self._provider.itemData(index) or "custom"
        preset = provider_for_key(str(provider_key))
        self._base_url.setText(preset.base_url)
        self._model.clear()
        self._model.addItems(list(preset.models))
        self._api_key.setEnabled(preset.key != "ollama")
        self._connection_status.setVisible(False)
        if preset.key == "ollama":
            self._api_key.clear()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._pause_button.setText("继续" if paused else "暂停")
        self.pauseChanged.emit(paused)
        self.set_status("已暂停" if paused else "运行中", "info")
        logger.info("弹幕%s", "暂停" if paused else "继续")

    # ---- Styles ----

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f5f7fa;
                color: #202421;
                font-family: "Segoe UI", "Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "Noto Sans SC", sans-serif;
                font-size: 13px;
            }
            QLabel#title {
                font-size: 22px;
                font-weight: 700;
                color: #1a1d1b;
            }
            QLabel#subtitle {
                color: #66706a;
                font-size: 13px;
            }
            QLabel#statusBar {
                padding: 4px 0;
                font-size: 12px;
            }
            QLabel#logDisplay {
                background: #1e1e1e;
                color: #c0c0c0;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
                padding: 6px 8px;
                border-radius: 4px;
            }
            QLabel#connStatus {
                font-size: 12px;
                padding: 2px 0;
            }
            QGroupBox {
                border: 1px solid #d7dee8;
                border-radius: 8px;
                margin-top: 12px;
                padding: 14px 12px 10px;
                background: #ffffff;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QComboBox {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 8px;
                background: #ffffff;
                color: #1a1d1b;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #1f6f5b;
            }
            QSpinBox {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 4px 4px 8px;
                background: #ffffff;
                color: #1a1d1b;
                min-height: 20px;
            }
            QSpinBox:focus {
                border-color: #1f6f5b;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                width: 18px;
                border-left: 1px solid #cbd5e1;
            }
            QSpinBox::up-button {
                subcontrol-position: top right;
                border-bottom: 1px solid #cbd5e1;
                border-top-right-radius: 6px;
            }
            QSpinBox::down-button {
                subcontrol-position: bottom right;
                border-bottom-right-radius: 6px;
            }
            QPushButton {
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton[class="primary"] {
                background: #1f6f5b;
                border: 1px solid #1f6f5b;
                color: white;
            }
            QPushButton[class="primary"]:hover {
                background: #27836c;
                border-color: #27836c;
            }
            QPushButton[class="primary"]:pressed {
                background: #175a49;
            }
            QPushButton[class="secondary"] {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                color: #202421;
            }
            QPushButton[class="secondary"]:hover {
                background: #eef1f5;
                border-color: #a0aec0;
            }
            QPushButton[class="secondary"]:pressed {
                background: #d7dee8;
            }
            QPushButton[class="danger"] {
                background: #ffffff;
                border: 1px solid #e2c0c0;
                color: #9a3f3f;
            }
            QPushButton[class="danger"]:hover {
                background: #fdf0f0;
                border-color: #c78a8a;
            }
            QPushButton[class="danger"]:pressed {
                background: #f5d6d6;
            }
            QPushButton[class="text"] {
                background: transparent;
                border: none;
                color: #66706a;
                font-weight: 400;
                font-size: 12px;
                padding: 2px 4px;
            }
            QPushButton[class="text"]:hover {
                color: #1f6f5b;
            }
            QPushButton:checked {
                background: #9a3f3f;
                border-color: #9a3f3f;
                color: white;
            }
            QPushButton:checked:hover {
                background: #b54a4a;
                border-color: #b54a4a;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #d7dee8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #1f6f5b;
            }
            QSlider::handle:horizontal:hover {
                background: #27836c;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #1f6f5b;
                border-color: #1f6f5b;
            }
            """
        )
