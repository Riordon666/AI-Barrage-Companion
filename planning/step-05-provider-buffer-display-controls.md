# 步骤 05：提供商预设、发送缓冲与显示控制

## 1. 本步骤目标

本步骤根据运行体验补强 MVP：

- AI 提供商改为下拉选择。
- 选择提供商后自动填充 Base URL，并联动模型列表。
- AI 采样生成弹幕和实际发送弹幕拆成两个节奏。
- 新增弹幕发送缓冲区，最多保留 10 条待发送弹幕。
- 弹幕缓存每个场景最多保留 10 条。
- 控制面板增加显示区域百分比和字体大小。
- 控制面板视觉样式从临时表单升级为分组式桌面工具界面。

## 2. 新增或更新的文件

新增：

```text
app/config/provider_presets.py
planning/step-05-provider-buffer-display-controls.md
```

更新：

```text
app/models.py
app/constants.py
app/config/settings.py
app/config/settings_store.py
app/core/ai_service.py
app/core/barrage_cache.py
app/core/barrage_manager.py
app/ui/application.py
app/ui/control_panel.py
app/ui/overlay.py
tests/test_ai_service.py
tests/test_barrage_cache.py
tests/test_settings_store.py
planning/implementation-roadmap.md
```

## 3. 提供商与模型联动

提供商预设位于：

```text
app/config/provider_presets.py
```

当前支持的 OpenAI 兼容提供商：

- OpenAI
- DeepSeek
- 阿里云百炼 / Qwen
- Moonshot / Kimi
- 智谱 GLM
- SiliconFlow
- OpenRouter
- Ollama 本地
- 自定义 OpenAI 兼容

控制面板行为：

- 提供商使用下拉框选择。
- 选择提供商后自动填充 Base URL。
- 模型下拉框随提供商切换。
- 模型框可编辑，用户仍可输入未列出的新模型名。
- Ollama 本地默认不需要 API Key。
- 自定义 OpenAI 兼容提供商允许用户输入 Base URL、模型和 API Key。

说明：

当前后端实现的是 OpenAI-compatible `/chat/completions` 协议。Anthropic、Gemini 等非同协议模型可先通过 OpenRouter、SiliconFlow 等兼容层接入；直接原生协议适配留到后续版本。

## 4. 生成节奏与发送节奏分离

之前的行为是：AI 或模拟生成一批弹幕后，立即交给调度器。

现在的行为是：

```text
截屏/分析/AI 生成
-> 放入发送缓冲区
-> 固定发送定时器逐条送入 BarrageManager
-> BarrageManager 按轨道和密度渲染
```

关键约束：

- 截屏和 AI 生成仍按采样策略执行。
- 弹幕发送用独立定时器执行。
- 发送缓冲区最多保存 10 条待发送弹幕。
- 缓冲区满时，新产生的弹幕不会继续堆积。
- 暂停后停止采样和发送。

这样可以避免 AI 一次返回多条弹幕后瞬间刷屏，同时保证弹幕能以稳定节奏出现。

## 5. 缓存上限

`InMemoryBarrageCache` 增加 `max_items_per_scene`，默认每个场景最多保存 10 条弹幕。

原因：

- 防止长期运行时缓存无限增长。
- 避免相同场景积累过多旧弹幕。
- 符合“缓存里的弹幕数量不超过 10 条”的产品约束。

## 6. 显示区域与字体大小

`AppSettings` 新增：

```python
display_area_percent: int = 65
barrage_font_size: int = 18
```

控制面板新增：

- 显示区域滑条：0% 到 100%。
- 字体大小输入：12 到 48。

覆盖层行为：

- `display_area_percent` 控制弹幕可出现的垂直区域高度。
- 0% 时不消耗待显示弹幕。
- 字体大小会影响实际渲染字号。
- 字号变化会同步更新调度器的轨道高度。

## 7. 控制面板视觉升级

控制面板改为分组布局：

- 标题区
- 运行设置
- 显示设置
- AI 提供商设置
- 操作按钮区

样式使用更清晰的边框、按钮、输入框和滑条状态，让它更像一个小型桌面控制台，而不是临时调试表单。

## 8. 新增测试

新增或更新的测试覆盖：

- 无 API 配置和缺少必需 API Key 时的降级差异。
- Ollama 等无 Key 提供商不会被 API Key 逻辑阻断。
- 弹幕缓存每个场景最多保留 10 条。
- 配置读写保存显示区域和字体大小。
- 配置加载时会夹住显示区域和字号的合法范围。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall app tests
```

当前通过 28 个测试。

## 9. 当前状态

除打包发布外，MVP 运行时继续保持可用：

- 可选择提供商和模型。
- 可保存 API 配置。
- 无 API Key 可回退模拟弹幕。
- AI 生成与弹幕发送节奏已分离。
- 弹幕缓冲和缓存均有上限。
- 可调节弹幕显示区域和字体大小。

后续建议：

- 做一次真实桌面手动验收。
- 根据实际模型供应商文档继续扩展原生协议适配。
- 阶段 8 再补 README、隐私说明和打包发布。
