"""Control panel with tabbed interface: Home / Settings / Logs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.provider_presets import PROVIDER_BY_KEY, SUPPORTED_PROVIDERS, provider_for_key
from app.core.logger import get_emitter, get_logger
from app.core.utils import as_density
from app.models import ApiConfig, AppSettings

logger = get_logger("control_panel")

# ---------------------------------------------------------------------------
# API Config Dialog (unchanged core, kept for modularity)
# ---------------------------------------------------------------------------


class ApiConfigDialog(QWidget):
    """Modal dialog for editing API provider settings with history."""

    saved = Signal(ApiConfig, list)

    def __init__(self, current: ApiConfig | None, history: list[ApiConfig], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API 提供商设置")
        self.setMinimumWidth(520)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._current = current
        self._history: list[ApiConfig] = list(history)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api_dlg")
        self._ct: QTimer | None = None
        self._cr = Signal(bool, str)
        self._cr.connect(self._on_conn_result)
        self._build()
        self._load_current()
        self._apply_styles()

    def _build(self) -> None:
        l = QVBoxLayout()
        l.setContentsMargins(20, 20, 20, 20)
        l.setSpacing(10)
        f = QFormLayout()
        self._prov = QComboBox()
        for p in SUPPORTED_PROVIDERS:
            self._prov.addItem(p.label, p.key)
        self._prov.currentIndexChanged.connect(self._on_prov)
        self._url = QLineEdit()
        self._mdl = QComboBox(); self._mdl.setEditable(True)
        self._key = QLineEdit(); self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("Ollama/自定义可留空")
        f.addRow("提供商", self._prov)
        f.addRow("Base URL", self._url)
        f.addRow("模型", self._mdl)
        f.addRow("API Key", self._key)
        l.addLayout(f)
        tr = QHBoxLayout()
        self._tbtn = QPushButton("测试连接"); self._tbtn.setProperty("class", "secondary")
        self._tbtn.clicked.connect(self._test)
        self._ts = QLabel(""); self._ts.setObjectName("connStatus")
        tr.addWidget(self._tbtn); tr.addWidget(self._ts); tr.addStretch()
        l.addLayout(tr)
        hl = QLabel("已保存的配置（双击加载）"); hl.setStyleSheet("font-weight:600;margin-top:6px")
        l.addWidget(hl)
        self._hist = QListWidget(); self._hist.setMaximumHeight(120)
        self._hist.itemDoubleClicked.connect(self._load_hist)
        self._refresh_hist()
        l.addWidget(self._hist)
        hr = QHBoxLayout()
        db = QPushButton("删除选中"); db.setProperty("class", "text"); db.clicked.connect(self._del_hist)
        hr.addWidget(db); hr.addStretch()
        l.addLayout(hr)
        br = QHBoxLayout(); br.addStretch()
        cb = QPushButton("取消"); cb.setProperty("class", "secondary"); cb.clicked.connect(self.close)
        self._save = QPushButton("保存配置"); self._save.setProperty("class", "primary"); self._save.clicked.connect(self._do_save)
        br.addWidget(cb); br.addWidget(self._save)
        l.addLayout(br)
        self.setLayout(l)

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget{background:#f5f7fa;color:#202421;font-family:\"Segoe UI\",\"Microsoft YaHei\",sans-serif;font-size:13px}
            QLineEdit,QComboBox{border:1px solid #cbd5e1;border-radius:6px;padding:6px 8px;background:#fff}
            QLineEdit:focus,QComboBox:focus{border-color:#1f6f5b}
            QPushButton{border-radius:6px;padding:8px 16px;font-weight:600}
            QPushButton[class=\"primary\"]{background:#1f6f5b;border:1px solid #1f6f5b;color:#fff}
            QPushButton[class=\"primary\"]:hover{background:#27836c}
            QPushButton[class=\"secondary\"]{background:#fff;border:1px solid #cbd5e1}
            QPushButton[class=\"secondary\"]:hover{background:#eef1f5}
            QPushButton[class=\"text\"]{background:transparent;border:none;color:#9a3f3f;font-weight:400;font-size:12px;padding:2px 4px}
            QPushButton[class=\"text\"]:hover{color:#b54a4a}
            QPushButton:disabled{opacity:.5}
            QLabel#connStatus{font-size:12px;padding:2px 0}
            QListWidget{border:1px solid #cbd5e1;border-radius:6px;background:#fff}
            QListWidget::item{padding:4px 8px}
            QListWidget::item:selected{background:#d4ede6;color:#1a1d1b}
        """)

    def _load_current(self) -> None:
        if self._current is None:
            self._prov.setCurrentIndex(self._prov.findData("custom"))
            return
        idx = self._prov.findData(self._current.provider)
        if idx >= 0: self._prov.setCurrentIndex(idx)
        self._url.setText(self._current.base_url)
        self._mdl.setCurrentText(self._current.model)
        le = self._mdl.lineEdit()
        if le: le.setText(self._current.model)
        self._key.setText(self._current.api_key)
        self._on_prov(self._prov.currentIndex())

    def _on_prov(self, i: int) -> None:
        k = self._prov.itemData(i) or "custom"
        p = provider_for_key(str(k))
        self._url.setText(p.base_url)
        self._mdl.clear(); self._mdl.addItems(list(p.models))
        self._key.setEnabled(p.key != "ollama")
        if p.key == "ollama": self._key.clear()

    def _cfg(self) -> ApiConfig:
        k = str(self._prov.currentData() or "custom")
        p = provider_for_key(k)
        return ApiConfig(provider=k, base_url=self._url.text().strip() or p.base_url,
                         api_key=self._key.text().strip(),
                         model=self._mdl.currentText().strip() or (p.models[0] if p else ""))

    def _refresh_hist(self) -> None:
        self._hist.clear(); seen = set()
        for c in self._history:
            lbl = f"{c.provider} | {c.model} | {c.base_url}"
            if lbl not in seen: seen.add(lbl); self._hist.addItem(lbl)

    def _load_hist(self, item) -> None:
        i = self._hist.row(item)
        if 0 <= i < len(self._history):
            c = self._history[i]
            pi = self._prov.findData(c.provider)
            if pi >= 0: self._prov.setCurrentIndex(pi)
            self._url.setText(c.base_url)
            self._mdl.setCurrentText(c.model)
            le = self._mdl.lineEdit()
            if le: le.setText(c.model)
            self._key.setText(c.api_key)
            self._on_prov(self._prov.currentIndex())
            self._ts.setText("")

    def _del_hist(self) -> None:
        r = self._hist.currentRow()
        if 0 <= r < len(self._history):
            del self._history[r]; self._refresh_hist()
            logger.info("API 配置历史已删除 (#%d)", r + 1)

    def _test(self) -> None:
        c = self._cfg()
        if not c.base_url: self._on_conn_result(False, "Base URL 为空"); return
        self._tbtn.setEnabled(False); self._tbtn.setText("测试中...")
        self._ts.setText("连接中..."); self._ts.setStyleSheet("color:#8b8b8b;font-weight:600")
        self._ct = QTimer(self); self._ct.setSingleShot(True)
        self._ct.timeout.connect(lambda: self._on_conn_result(False, "连接超时 (15s)"))
        self._ct.start(15000)
        self._executor.submit(self._do_test, c)

    def _do_test(self, c: ApiConfig) -> None:
        url = c.base_url.rstrip("/") + "/chat/completions"
        h = {"Content-Type": "application/json"}
        if c.api_key: h["Authorization"] = f"Bearer {c.api_key}"
        try:
            with httpx.Client(timeout=httpx.Timeout(8, connect=5)) as cl:
                r = cl.post(url, headers=h, json={"model": c.model or "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 1})
                if r.status_code == 200: self._cr.emit(True, f"连接成功 ({c.model})")
                else: self._cr.emit(False, f"HTTP {r.status_code}: {r.text[:80]}")
        except httpx.TimeoutException: self._cr.emit(False, "连接超时 (8s)")
        except httpx.ConnectError: self._cr.emit(False, "无法连接，请检查 URL 或网络")
        except Exception as e: self._cr.emit(False, str(e)[:60])

    def _on_conn_result(self, ok: bool, msg: str) -> None:
        if self._ct: self._ct.stop(); self._ct = None
        self._tbtn.setEnabled(True); self._tbtn.setText("测试连接")
        self._ts.setText(msg); self._ts.setStyleSheet(f"color:{'#1f6f5b' if ok else '#9a3f3f'};font-weight:600")

    def _do_save(self) -> None:
        c = self._cfg()
        self._history = [h for h in self._history if not (h.provider == c.provider and h.base_url == c.base_url and h.model == c.model)]
        self._history.insert(0, c)
        if len(self._history) > 20: self._history = self._history[:20]
        self.saved.emit(c, list(self._history))
        self.close()
        logger.info("API 已保存: %s | %s (历史 %d)", c.provider, c.model, len(self._history))


# ---------------------------------------------------------------------------
# Stats card widget
# ---------------------------------------------------------------------------

def _stat_card(title: str, value: str, sub: str = "", color: str = "#1f6f5b") -> QFrame:
    """Create a compact metric card."""
    card = QFrame()
    card.setStyleSheet(f"QFrame{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px}}")
    vl = QVBoxLayout(); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(4)
    t = QLabel(title); t.setStyleSheet("color:#66706a;font-size:11px;font-weight:600;text-transform:uppercase")
    v = QLabel(value); v.setStyleSheet(f"color:{color};font-size:22px;font-weight:700")
    vl.addWidget(t); vl.addWidget(v)
    if sub:
        s = QLabel(sub); s.setStyleSheet("color:#8b949e;font-size:11px")
        vl.addWidget(s)
    card.setLayout(vl)
    return card


# ---------------------------------------------------------------------------
# Main Control Panel
# ---------------------------------------------------------------------------

class ControlPanel(QWidget):
    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumWidth(520)
        self.setMaximumHeight(760)
        self._settings = settings
        self._status_msg = ""
        self._status_type = "info"
        self._build()
        self._apply_styles()
        self._load_settings(settings)
        self._connect_logger()

    # ---- build ----

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._home_tab(), "首页")
        tabs.addTab(self._settings_tab(), "设置")
        tabs.addTab(self._logs_tab(), "日志")
        tabs.setStyleSheet("""
            QTabWidget::pane{border:1px solid #d7dee8;border-radius:0 0 8px 8px;background:#fff}
            QTabBar::tab{background:#eef1f5;padding:8px 24px;margin-right:2px;border-radius:8px 8px 0 0;font-weight:600;font-size:13px}
            QTabBar::tab:selected{background:#fff;color:#1f6f5b}
            QTabBar::tab:hover{background:#d7dee8}
        """)

        outer = QVBoxLayout()
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(8)
        outer.addWidget(tabs)

        # bottom bar
        bb = QHBoxLayout()
        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True); self._pause_btn.toggled.connect(self._on_pause)
        self._pause_btn.setProperty("class", "primary"); self._pause_btn.setFixedWidth(72)
        bb.addWidget(self._pause_btn)
        bb.addStretch()
        self._save_btn = QPushButton("保存配置"); self._save_btn.setProperty("class", "secondary"); self._save_btn.clicked.connect(self._save_settings)
        self._quit_btn = QPushButton("退出"); self._quit_btn.setProperty("class", "danger"); self._quit_btn.clicked.connect(self.quitRequested.emit)
        bb.addWidget(self._save_btn); bb.addWidget(self._quit_btn)
        outer.addLayout(bb)

        self._status_bar = QLabel("[i] 就绪"); self._status_bar.setObjectName("statusBar")
        outer.addWidget(self._status_bar)
        self.setLayout(outer)

    # ---- Home tab ----

    def _home_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(); l.setContentsMargins(16, 16, 16, 16); l.setSpacing(10)

        # Stats row 1
        r1 = QHBoxLayout(); r1.setSpacing(10)
        self._card_total = _stat_card("总弹幕", "0")
        self._card_ai = _stat_card("AI 生成", "0", sub="", color="#1f6f5b")
        self._card_mock = _stat_card("模拟弹幕", "0", sub="", color="#e6a23c")
        self._card_cache = _stat_card("缓存命中", "0", sub="", color="#409eff")
        r1.addWidget(self._card_total); r1.addWidget(self._card_ai)
        r1.addWidget(self._card_mock); r1.addWidget(self._card_cache)
        l.addLayout(r1)

        # Stats row 2
        r2 = QHBoxLayout(); r2.setSpacing(10)
        self._card_uptime = _stat_card("运行时长", "--", color="#909399")
        self._card_captures = _stat_card("截屏次数", "0", color="#909399")
        self._card_tokens = _stat_card("≈Token 消耗", "0", color="#909399")
        r2.addWidget(self._card_uptime); r2.addWidget(self._card_captures); r2.addWidget(self._card_tokens)
        l.addLayout(r2)

        # API info card
        api_g = QGroupBox("API 提供商")
        self._api_info = QLabel("未配置"); self._api_info.setStyleSheet("color:#66706a;font-size:13px")
        self._conn_dot = QLabel("●"); self._conn_dot.setStyleSheet("color:#8b949e;font-size:16px;font-weight:700")
        api_row = QHBoxLayout(); api_row.addWidget(self._conn_dot); api_row.addWidget(self._api_info); api_row.addStretch()
        api_g.setLayout(api_row)
        l.addWidget(api_g)

        l.addStretch()

        # Refresh timer for stats
        self._stats_timer = QTimer(self); self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.setInterval(2000)
        w.setLayout(l)
        return w

    # ---- Settings tab ----

    def _settings_tab(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        l = QVBoxLayout(); l.setContentsMargins(16, 16, 16, 16); l.setSpacing(10)

        # Density
        self._density = QComboBox(); self._density.addItems(["low", "medium", "high"])
        self._density.currentTextChanged.connect(self.densityChanged.emit)

        # Display
        self._display_area = QSlider(Qt.Orientation.Horizontal); self._display_area.setRange(0, 100)
        self._display_area.valueChanged.connect(self.displayAreaChanged.emit)
        self._da_val = QLabel("65%")
        self._display_area.valueChanged.connect(lambda v: self._da_val.setText(f"{v}%"))
        self._font_size = QSpinBox(); self._font_size.setRange(12, 48)
        self._font_size.valueChanged.connect(self.fontSizeChanged.emit)

        # Toggles
        self._mock_ck = QCheckBox("无 API Key 时使用模拟弹幕")
        self._vision_ck = QCheckBox("发送截图给 AI（视觉模式）")
        self._ocr_ck = QCheckBox("启用 OCR 屏幕文字识别（Windows 内置引擎）")
        self._win_ck = QCheckBox("启用窗口标题检测")

        # Privacy / Cost
        self._privacy = QComboBox(); self._privacy.addItems(["strict", "balanced"])
        self._cost = QComboBox(); self._cost.addItems(["immersive", "balanced", "saving"])
        self._cap_int = QDoubleSpinBox(); self._cap_int.setRange(0.5, 30); self._cap_int.setSingleStep(0.5); self._cap_int.setSuffix(" 秒")

        # API button
        self._api_btn = QPushButton("⚙ 配置 API 提供商"); self._api_btn.setProperty("class", "secondary")
        self._api_btn.clicked.connect(self._open_api_dialog)
        self._api_summary = QLabel("未配置"); self._api_summary.setStyleSheet("color:#66706a;font-size:12px")

        l.addWidget(self._group("弹幕", [("密度", self._density), ("", self._mock_ck)]))
        l.addWidget(self._group("显示", [("显示区域", self._hbox(self._display_area, self._da_val)), ("字体大小", self._font_size)]))
        l.addWidget(self._group("屏幕感知", [("", self._ocr_ck), ("", self._win_ck), ("", self._vision_ck)]))
        l.addWidget(self._group("API", [("", self._api_btn), ("", self._api_summary)]))
        l.addWidget(self._group("高级", [("隐私模式", self._privacy), ("成本模式", self._cost), ("截屏间隔", self._cap_int)]))
        l.addStretch()
        w.setLayout(l)
        scroll.setWidget(w)
        return scroll

    def _group(self, title: str, rows: list[tuple[str, QWidget]]) -> QGroupBox:
        g = QGroupBox(title)
        f = QFormLayout()
        for label, widget in rows: f.addRow(label, widget)
        g.setLayout(f)
        return g

    def _hbox(self, *widgets: QWidget) -> QWidget:
        w = QWidget(); b = QHBoxLayout(); b.setContentsMargins(0, 0, 0, 0)
        for c in widgets: b.addWidget(c)
        w.setLayout(b); return w

    # ---- Logs tab ----

    def _logs_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(); l.setContentsMargins(12, 12, 12, 12); l.setSpacing(8)

        sub = QTabWidget()
        sub.setStyleSheet("QTabBar::tab{padding:6px 16px;font-size:12px}")
        self._sys_log = QPlainTextEdit(); self._sys_log.setReadOnly(True)
        self._ocr_log = QPlainTextEdit(); self._ocr_log.setReadOnly(True)
        self._api_log = QPlainTextEdit(); self._api_log.setReadOnly(True)
        for te in (self._sys_log, self._ocr_log, self._api_log):
            te.setStyleSheet("background:#1b1e23;color:#c0c0c0;font-family:Consolas,'Courier New',monospace;font-size:12px;border:1px solid #2a2d35;border-radius:6px;padding:8px")
            te.setMaximumBlockCount(500)
        sub.addTab(self._sys_log, "系统")
        sub.addTab(self._ocr_log, "OCR")
        sub.addTab(self._api_log, "API")
        l.addWidget(sub)
        w.setLayout(l)
        return w

    # ---- actions ----

    def _refresh_stats(self) -> None:
        ctrl = getattr(self, '_controller', None)
        if ctrl is None: return
        s = ctrl.stats
        self._card_total.findChildren(QLabel)[1].setText(str(s["barrages_sent"]))
        self._card_ai.findChildren(QLabel)[1].setText(str(s["barrages_ai"]))
        self._card_mock.findChildren(QLabel)[1].setText(str(s["barrages_mock"]))
        self._card_cache.findChildren(QLabel)[1].setText(str(s["barrages_cache"]))
        self._card_captures.findChildren(QLabel)[1].setText(str(s["captures"]))
        self._card_tokens.findChildren(QLabel)[1].setText(f"{s['tokens_approx_in'] + s['tokens_approx_out']}")
        uptime = int(ctrl.session_uptime)
        self._card_uptime.findChildren(QLabel)[1].setText(f"{uptime//60}m {uptime%60}s")
        # Connection dot
        if s["api_failures"] > s.get("api_calls", 1) // 2:
            self._conn_dot.setStyleSheet("color:#9a3f3f;font-size:16px;font-weight:700")
        else:
            self._conn_dot.setStyleSheet("color:#1f6f5b;font-size:16px;font-weight:700")

    def set_controller(self, ctrl) -> None:  # type: ignore[no-untyped-def]
        self._controller = ctrl
        self._stats_timer.start()

    def _on_pause(self, paused: bool) -> None:
        self._pause_btn.setText("继续" if paused else "暂停")
        self.pauseChanged.emit(paused)
        self.set_status("已暂停" if paused else "运行中", "info")
        logger.info("弹幕%s", "暂停" if paused else "继续")

    def _open_api_dialog(self) -> None:
        dlg = ApiConfigDialog(self._settings.api, list(self._settings.api_history), self)
        dlg.saved.connect(self._on_api_saved)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()

    def _on_api_saved(self, config: ApiConfig, history: list[ApiConfig]) -> None:
        self._settings.api = config
        self._settings.api_history = history
        self._refresh_api_summary()
        self.set_status(f"API: {config.provider} · {config.model}", "success")
        self._save_settings()

    def _refresh_api_summary(self) -> None:
        a = self._settings.api
        if a and a.provider:
            self._api_info.setText(f"<b>{a.provider}</b> · {a.model}<br><span style='font-size:11px;color:#8b949e'>{a.base_url}</span>")
            self._api_summary.setText(f"{a.provider} · {a.model}\n{a.base_url}")
            self._api_summary.setStyleSheet("color:#1f6f5b;font-size:12px")
        else:
            self._api_info.setText("未配置 — 将使用模拟弹幕")
            self._api_summary.setText("未配置 — 将使用模拟弹幕"); self._api_summary.setStyleSheet("color:#9a3f3f;font-size:12px")

    def _save_settings(self) -> None:
        self._settings.density = as_density(self._density.currentText())
        self._settings.use_mock_when_api_missing = self._mock_ck.isChecked()
        self._settings.enable_vision = self._vision_ck.isChecked()
        self._settings.enable_ocr = self._ocr_ck.isChecked()
        self._settings.enable_window_title = self._win_ck.isChecked()
        self._settings.privacy_mode = self._privacy.currentText()  # type:ignore[assignment]
        self._settings.cost_mode = self._cost.currentText()  # type:ignore[assignment]
        self._settings.capture_interval_seconds = self._cap_int.value()
        self._settings.display_area_percent = self._display_area.value()
        self._settings.barrage_font_size = self._font_size.value()
        self.settingsSaved.emit(self._settings)
        self._save_btn.setText("[ok] 已保存")
        self._save_btn.setStyleSheet("QPushButton{background:#1f6f5b;border:1px solid #1f6f5b;border-radius:6px;padding:8px 14px;color:#fff}")
        self.set_status("配置已保存", "success")
        QTimer.singleShot(1500, lambda: (self._save_btn.setText("保存配置"), self._save_btn.setStyleSheet("")))

    def _load_settings(self, s: AppSettings) -> None:
        self._density.setCurrentText(s.density)
        self._display_area.setValue(s.display_area_percent)
        self._font_size.setValue(s.barrage_font_size)
        self._mock_ck.setChecked(s.use_mock_when_api_missing)
        self._vision_ck.setChecked(s.enable_vision)
        self._ocr_ck.setChecked(s.enable_ocr)
        self._win_ck.setChecked(s.enable_window_title)
        self._privacy.setCurrentText(s.privacy_mode)
        self._cost.setCurrentText(s.cost_mode)
        self._cap_int.setValue(s.capture_interval_seconds)
        self._refresh_api_summary()

    def set_status(self, msg: str, typ: str = "info") -> None:
        self._status_msg = msg; self._status_type = typ
        colors = {"info": "#66706a", "success": "#1f6f5b", "error": "#9a3f3f"}
        prefixes = {"info": "[i]", "success": "[ok]", "error": "[!]"}
        self._status_bar.setText(f"{prefixes.get(typ, '[i]')} {msg}")
        self._status_bar.setStyleSheet(f"color:{colors.get(typ, '#66706a')};font-size:12px")

    # ---- log collector ----

    def _connect_logger(self) -> None:
        get_emitter().newLog.connect(self._on_log)

    def _on_log(self, msg: str) -> None:
        if "[API" in msg or "[HTTP" in msg or "弹幕生成" in msg:
            self._api_log.appendPlainText(msg + "\n")
        elif "OCR" in msg or "识别" in msg:
            self._ocr_log.appendPlainText(msg + "\n")
        else:
            self._sys_log.appendPlainText(msg + "\n")

    def append_ocr_log(self, msg: str) -> None:
        self._ocr_log.appendPlainText(f"{time.strftime('%H:%M:%S')} | {msg}\n")

    def append_api_log(self, msg: str) -> None:
        self._api_log.appendPlainText(f"{time.strftime('%H:%M:%S')} | {msg}\n")

    # ---- styles ----

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget{background:#f5f7fa;color:#202421;font-family:\"Segoe UI\",\"Microsoft YaHei\",sans-serif;font-size:13px}
            QGroupBox{border:1px solid #d7dee8;border-radius:8px;margin-top:12px;padding:14px 12px 10px;background:#fff;font-weight:600}
            QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px}
            QLineEdit,QComboBox{border:1px solid #cbd5e1;border-radius:6px;padding:6px 8px;background:#fff}
            QLineEdit:focus,QComboBox:focus{border-color:#1f6f5b}
            QSpinBox,QDoubleSpinBox{border:1px solid #cbd5e1;border-radius:6px;padding:4px 4px 4px 8px;background:#fff;min-height:20px}
            QSpinBox:focus,QDoubleSpinBox:focus{border-color:#1f6f5b}
            QPushButton{border-radius:6px;padding:8px 16px;font-weight:600}
            QPushButton[class=\"primary\"]{background:#1f6f5b;border:1px solid #1f6f5b;color:#fff}
            QPushButton[class=\"primary\"]:hover{background:#27836c}
            QPushButton[class=\"secondary\"]{background:#fff;border:1px solid #cbd5e1}
            QPushButton[class=\"secondary\"]:hover{background:#eef1f5}
            QPushButton[class=\"danger\"]{background:#fff;border:1px solid #e2c0c0;color:#9a3f3f}
            QPushButton[class=\"danger\"]:hover{background:#fdf0f0}
            QPushButton:checked{background:#9a3f3f;border-color:#9a3f3f;color:#fff}
            QPushButton:checked:hover{background:#b54a4a}
            QPushButton:disabled{opacity:.5}
            QSlider::groove:horizontal{height:6px;background:#d7dee8;border-radius:3px}
            QSlider::handle:horizontal{width:16px;margin:-5px 0;border-radius:8px;background:#1f6f5b}
            QSlider::handle:horizontal:hover{background:#27836c}
            QCheckBox{spacing:6px}
            QCheckBox::indicator{width:16px;height:16px;border-radius:3px;border:1px solid #cbd5e1;background:#fff}
            QCheckBox::indicator:checked{background:#1f6f5b;border-color:#1f6f5b}
            QScrollArea{border:none;background:transparent}
            QLabel#statusBar{padding:4px 0;font-size:12px}
        """)
