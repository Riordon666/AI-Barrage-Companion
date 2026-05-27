# 步骤 07：API 配置弹窗、OCR 降级与 UI 修复

## 1. 本步骤目标

本步骤修复运行时发现的几个问题：

- 点击“配置 API 提供商”时报错，弹窗无法打开。
- Windows OCR 在部分环境中抛出 `RuntimeError` 并反复刷日志。
- 测试环境中真实 `mss` 截屏失败会打断集成测试。
- API 弹窗加载当前配置或历史配置时，可能被提供商默认值覆盖。
- 控制面板交互稳定性继续优化。

## 2. 修复内容

### 2.1 API 配置弹窗信号修复

问题：

```text
AttributeError: 'PySide6.QtCore.Signal' object has no attribute 'connect'
```

原因：

PySide6 的 `Signal` 必须定义为 `QObject`/`QWidget` 子类的类属性，不能在 `__init__` 里创建后直接调用 `connect()`。

处理：

- `ApiConfigDialog.connectionResult = Signal(bool, str)` 改为类属性。
- 后台连接测试线程通过 `connectionResult.emit(...)` 回到 UI 线程。
- API 弹窗实例保存到 `ControlPanel._api_dialog`，避免窗口对象被 Python 回收。

### 2.2 API 配置加载修复

问题：

加载当前配置或历史配置时，会先填入用户保存的 Base URL / Model，然后又调用提供商默认填充逻辑，导致用户配置被覆盖。

处理：

- 当前配置加载后不再二次调用提供商默认填充。
- 历史配置双击加载后不再覆盖保存的 URL 和模型。
- 只有用户主动切换提供商时，才自动填充该提供商默认 Base URL 和模型列表。

### 2.3 OCR 降级修复

问题：

部分 Windows 环境中，WinRT OCR 依赖可以导入，但异步识别调用会抛出 `RuntimeError`：

```text
Windows OCR 异常 (RuntimeError)
```

处理：

- 本会话中首次遇到 Windows OCR `RuntimeError` 后，标记 Windows OCR 不可用。
- 后续 OCR 直接跳过 Windows OCR，进入 Tesseract 降级路径。
- 日志从反复异常改为一次性提示“Windows OCR 当前不可用，已改用 Tesseract 降级”。
- OCR 返回结果增加状态诊断，区分“后端不可用”“图像转换失败”“后端可用但没识别到文字”等情况。
- Tesseract 识别前增加灰度化、放大、自动对比度和锐化预处理，提高整屏小字识别概率。
- UI OCR 日志显示具体后端和原因，不再只显示笼统的“未识别到文字”。

### 2.4 截屏失败处理

问题：

测试或部分桌面环境里，`mss` 的 BitBlt 截屏可能失败。

处理：

- 默认 `MssScreenCapture` 失败时，运行时使用一帧内存空图继续流程，避免应用崩溃。
- 显式注入的测试截屏器失败时，保留安全默认场景 `unknown/normal/normal`。
- `screen_capture.py` 改用 `mss.MSS()`，避免 `mss.mss()` 弃用警告。

### 2.5 UI 交互稳定性

处理：

- API 弹窗连接测试按钮恢复状态更稳定。
- 弹窗关闭时关闭后台测试线程池。
- 保留用户配置，不再意外重置模型和 Base URL。

## 3. 验证

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall app tests
```

结果：

```text
77 passed
compileall passed
```

## 4. 当前状态

本步骤后：

- API 配置弹窗可正常打开。
- OCR 在 Windows OCR 不可用时会稳定降级。
- OCR 日志会显示更具体的失败原因或识别后端。
- 集成测试恢复全绿。
- 截屏失败不再直接打断运行管线。

仍建议后续做一次真实 GUI 手动验收，重点检查：

- API 弹窗打开、测试连接、保存配置。
- OCR 开启后是否能识别当前屏幕文字。
- 没有 Tesseract 时 OCR 是否给出清晰降级表现。
- 弹幕覆盖层、区域设置、字体设置是否符合预期。
