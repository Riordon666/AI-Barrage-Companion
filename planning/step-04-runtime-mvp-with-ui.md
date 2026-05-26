# 步骤 04：运行时 MVP 与桌面 UI

## 1. 本步骤目标

本步骤把项目从“可生成、可调度弹幕”的核心库状态，推进到除打包发布外的 MVP 运行时：

- 支持本地 JSON 配置读写。
- 支持真实截屏入口和本地帧差分析。
- 支持采样策略、隐私过滤、AI 生成、缓存、模拟降级。
- 支持 PySide6 透明弹幕覆盖层。
- 支持基础控制面板和托盘入口。
- 用主流程控制器串联 `capture -> analyze -> privacy -> generate/cache -> enqueue -> render`。

本步骤不做发布打包，不生成 Windows 可执行文件。

## 2. 新增或更新的文件

新增：

```text
app/config/settings.py
app/config/settings_store.py
app/core/screen_capture.py
app/core/frame_analyzer.py
app/core/capture_scheduler.py
app/core/barrage_cache.py
app/core/ai_service.py
app/ui/overlay.py
app/ui/control_panel.py
app/ui/tray.py
app/ui/application.py
tests/test_settings_store.py
tests/test_frame_analyzer.py
tests/test_capture_scheduler.py
tests/test_barrage_cache.py
tests/test_ai_service.py
planning/step-04-runtime-mvp-with-ui.md
```

更新：

```text
main.py
app/constants.py
app/core/__init__.py
planning/implementation-roadmap.md
```

## 3. 配置读写

`SettingsStore` 位于：

```text
app/config/settings_store.py
```

行为：

- 无配置文件时使用默认配置。
- 配置文件损坏时回退默认配置，并返回提示信息。
- 支持保存和加载 API 配置、密度、成本模式、隐私模式等字段。
- 不在异常消息中输出 API Key。

默认配置入口位于：

```text
app/config/settings.py
```

## 4. 截屏与帧分析

`MssScreenCapture` 位于：

```text
app/core/screen_capture.py
```

它使用 `mss` 获取主屏截图，截图对象只留在内存里，不写入磁盘。

`BasicFrameAnalyzer` 位于：

```text
app/core/frame_analyzer.py
```

它对画面做小尺寸采样，通过连续帧灰度差异估算：

- `change_ratio`
- `static_seconds`
- `repeat_score`
- `pace`
- `SceneSummary`

第一版不做 OCR，不读取窗口标题，不识别文件名。

## 5. 采样策略

`BasicCaptureScheduler` 位于：

```text
app/core/capture_scheduler.py
```

行为：

- 平衡模式按配置间隔采样。
- 省电模式把采样窗口提高到 8 到 12 秒。
- 沉浸模式可缩短到约 1 到 2 秒。
- 快速变化时把最短间隔降到 1 秒。
- 空闲状态允许更长采样间隔。

## 6. AI 服务与缓存

`OpenAICompatibleBarrageService` 位于：

```text
app/core/ai_service.py
```

行为：

- 调用 OpenAI 兼容的 `/chat/completions` 接口。
- 构造只包含粗粒度场景摘要的 Prompt。
- 解析 JSON 数组。
- JSON 失败时尝试按文本行提取。
- API Key 缺失、请求失败、空结果时降级到 `MockBarrageService`。

`InMemoryBarrageCache` 位于：

```text
app/core/barrage_cache.py
```

行为：

- 按 `activity/pace/event` 缓存弹幕。
- 同文本去重。
- 普通场景可优先复用缓存弹幕，减少 API 调用。

## 7. 透明覆盖层

`PySideOverlayRenderer` 位于：

```text
app/ui/overlay.py
```

行为：

- 创建透明、无边框、置顶窗口。
- 默认尽量点击穿透。
- 把 `TrackAssignment` 渲染为从右向左移动的文字标签。
- 渲染层不调用 AI、不读取截图、不做调度。

## 8. 控制面板与托盘

控制面板位于：

```text
app/ui/control_panel.py
```

当前支持：

- 暂停/继续。
- 低/中/高密度切换。
- API Provider、Base URL、Model、API Key 输入。
- 保存配置。
- 退出应用。

托盘入口位于：

```text
app/ui/tray.py
```

当前提供：

- 显示控制面板。
- 退出应用。

## 9. 主流程整合

运行时控制器位于：

```text
app/ui/application.py
```

主流程：

```text
capture
-> analyze
-> privacy
-> cache/generate
-> enqueue
-> render
```

说明：

- 截屏和分析在定时器中触发。
- AI 生成在后台线程中执行，避免阻塞 UI。
- 暂停后停止采样，并阻止新增弹幕调度。
- 配置保存后会重建生成器并更新密度。

根目录入口 `main.py` 现在启动 PySide6 桌面应用。

## 10. 新增测试

新增测试覆盖：

- 配置缺失、损坏、保存读取。
- 静止画面识别为空闲。
- 大幅变化识别为高亮/快速。
- 采样策略在省电和快速变化状态下的行为。
- 缓存按场景读取和文本去重。
- AI JSON 解析。
- 无 API Key 降级到模拟生成。

执行结果：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

当前通过 25 个测试。

## 11. 当前完成状态

已完成：

- 阶段 1：模型与配置的本地读写。
- 阶段 2：截屏入口、本地帧差分析、采样策略。
- 阶段 3：模拟弹幕、隐私过滤、AI 服务、缓存与降级。
- 阶段 4：弹幕调度器。
- 阶段 5：透明弹幕窗口。
- 阶段 6：基础控制面板与托盘。
- 阶段 7：主流程整合。

仍未完成：

- 阶段 8：打包与发布准备。
- 真实长时间运行验收。
- 多屏适配。
- 更完整的 API 配置校验和错误提示 UI。

## 12. 下一步

下一步建议先手动运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

检查：

- 控制面板能打开。
- 桌面能看到透明弹幕。
- 暂停/继续能控制弹幕新增。
- 密度切换有效。
- 无 API Key 时能使用模拟弹幕。

手动验收通过后，再进入阶段 8：README、隐私说明、配置路径说明和 Windows 打包。
