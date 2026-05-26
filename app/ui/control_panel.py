"""Control panel for runtime settings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from app.models import ApiConfig, AppSettings


class ControlPanel(QWidget):
    """Expose generation, display, and API controls."""

    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumWidth(420)
        self._settings = settings
        self._provider_keys = [provider.key for provider in SUPPORTED_PROVIDERS]

        self._build_controls()
        self._apply_styles()
        self._load_settings(settings)

    def _build_controls(self) -> None:
        self._pause_button = QPushButton("暂停")
        self._pause_button.setCheckable(True)
        self._pause_button.toggled.connect(self._on_pause_toggled)

        self._density = QComboBox()
        self._density.addItems(["low", "medium", "high"])
        self._density.currentTextChanged.connect(self.densityChanged.emit)

        self._display_area = QSlider(Qt.Orientation.Horizontal)
        self._display_area.setRange(0, 100)
        self._display_area.valueChanged.connect(self.displayAreaChanged.emit)
        self._display_area_value = QLabel()
        self._display_area.valueChanged.connect(
            lambda value: self._display_area_value.setText(f"{value}%")
        )

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 48)
        self._font_size.valueChanged.connect(self.fontSizeChanged.emit)

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

        self._save_button = QPushButton("保存配置")
        self._save_button.clicked.connect(self._save_settings)
        self._quit_button = QPushButton("退出")
        self._quit_button.clicked.connect(self.quitRequested.emit)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(self._title())
        layout.addWidget(self._runtime_group())
        layout.addWidget(self._display_group())
        layout.addWidget(self._provider_group())
        layout.addLayout(self._button_row())
        self.setLayout(layout)

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
        group.setLayout(form)
        return group

    def _button_row(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        buttons.addWidget(self._pause_button)
        buttons.addStretch(1)
        buttons.addWidget(self._save_button)
        buttons.addWidget(self._quit_button)
        return buttons

    def _load_settings(self, settings: AppSettings) -> None:
        self._density.setCurrentText(settings.density)
        self._display_area.setValue(settings.display_area_percent)
        self._font_size.setValue(settings.barrage_font_size)
        self._mock_when_missing.setChecked(settings.use_mock_when_api_missing)

        provider_key = settings.api.provider if settings.api else "custom"
        provider_index = self._provider_keys.index(provider_key) if provider_key in self._provider_keys else self._provider_keys.index("custom")
        self._provider.setCurrentIndex(provider_index)
        self._on_provider_changed(provider_index)

        if settings.api:
            self._base_url.setText(settings.api.base_url)
            self._model.setCurrentText(settings.api.model)
            self._api_key.setText(settings.api.api_key)

    def _on_provider_changed(self, index: int) -> None:
        provider_key = self._provider.itemData(index) or "custom"
        preset = provider_for_key(str(provider_key))
        self._base_url.setText(preset.base_url)
        self._model.clear()
        self._model.addItems(list(preset.models))
        self._api_key.setEnabled(preset.key != "ollama")
        if preset.key == "ollama":
            self._api_key.clear()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._pause_button.setText("继续" if paused else "暂停")
        self.pauseChanged.emit(paused)

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

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f5f7fa;
                color: #202421;
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-size: 13px;
            }
            QLabel#title {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #66706a;
            }
            QGroupBox {
                border: 1px solid #d7dee8;
                border-radius: 8px;
                margin-top: 12px;
                padding: 12px;
                background: #ffffff;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px;
                background: #ffffff;
            }
            QPushButton {
                border: 1px solid #1f6f5b;
                border-radius: 6px;
                padding: 8px 14px;
                background: #1f6f5b;
                color: white;
                font-weight: 600;
            }
            QPushButton:checked {
                background: #9a3f3f;
                border-color: #9a3f3f;
            }
            QPushButton:hover {
                background: #27836c;
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
            """
        )
