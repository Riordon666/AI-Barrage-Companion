# 步骤 02：隐私过滤与模拟弹幕生成

## 1. 本步骤目标

本步骤在工程骨架基础上，实现第一条可运行的生成链路：

- 在生成弹幕之前，通过隐私边界过滤场景上下文。
- 不依赖 API Key 和网络，生成本地模拟弹幕。
- 添加测试，锁定预期行为。

本步骤仍然不实现真实截屏、帧差异分析、AI API 调用、弹幕调度或 PySide6 渲染。

## 2. 新增或更新的文件

新增：

```text
app/core/privacy_guard.py
app/core/mock_barrage_service.py
tests/test_privacy_guard.py
tests/test_mock_barrage_service.py
planning/step-02-privacy-and-mock-generator.md
```

更新：

```text
main.py
planning/project-plan.md
planning/implementation-roadmap.md
planning/step-01-scaffold-and-interfaces.md
```

## 3. PrivacyGuard 实现

`BasicPrivacyGuard` 添加在：

```text
app/core/privacy_guard.py
```

它接收 `SceneSummary` 和 `AppSettings`，返回一个 `PrivacyDecision`。

默认严格模式阻止以下敏感上下文字段进入 AI 请求：

```text
screenshot
ocr_text
window_title
file_name
url
chat_text
```

当前的 `SceneSummary` 只包含粗粒度字段：

- activity
- pace
- event
- confidence

因此隐私守卫会放行经过清理的场景摘要，同时明确记录哪些富上下文字段在 MVP 中不得进入 AI 生成。

原因：

项目的承诺不仅仅是"不上传截图"。OCR 文本、窗口标题、文件名、URL 和聊天文本同样可能泄露隐私。隐私守卫为未来的 AI 调用创建了一道强制边界。

## 4. MockBarrageService 实现

`MockBarrageService` 添加在：

```text
app/core/mock_barrage_service.py
```

它基于以下条件实现本地弹幕生成：

- `SceneSummary.event`
- 请求的人格列表
- 请求的数量

支持的事件类型：

- `normal`
- `highlight`
- `stuck`
- `idle`

支持的人格：

- `troll`（吐槽）
- `support`（鼓励）
- `sarcastic`（阴阳）
- `follower`（跟风）
- `fun`（乐子人）

行为：

- 返回 `GenerationResult(source="mock")`。
- 请求数量上限为 5 条。
- 生成适合弹幕显示的短文本。
- `highlight` 事件优先级为 `10`，`stuck` 为 `5`，普通或空闲事件为 `0`。
- 生成唯一弹幕 ID。

原因：

模拟生成让项目可以在没有 API Key、网络请求、Prompt 设计和模型返回解析之前，先验证弹幕生成链路的正确性。

## 5. 入口更新

根目录 `main.py` 现在运行一条小型集成链路：

```text
SceneSummary
-> BasicPrivacyGuard
-> MockBarrageService
-> 控制台输出
```

运行：

```powershell
python main.py
```

预期输出：

```text
AI Barrage Companion scaffold ready
density=medium, cost_mode=balanced
privacy_allowed=True
mock_barrages=...
```

具体的弹幕文本可能变化，因为模拟服务会从本地模板中随机选取。

## 6. 新增测试

新增隐私测试：

- 严格模式禁止截图、OCR 文本、窗口标题、文件名、URL 和聊天文本。
- 场景置信度被限制在 `0.0` 到 `1.0` 之间。
- 平衡模式尊重可选的 OCR 和窗口标题开关。

新增模拟生成测试：

- 生成请求指定数量的弹幕。
- 返回 `source="mock"`。
- 返回预期的人格值。
- highlight 事件分配高优先级。
- 数量上限为 5。
- stuck 事件使用中等优先级。

## 7. 当前完成状态

已完成：

- 基础隐私过滤
- 本地模拟弹幕生成
- `main.py` 中的最小集成
- 隐私和模拟生成的单元测试

仍未完成：

- 真实截屏
- 帧差异分析
- AIService
- BarrageCache
- BarrageManager
- PySide6 透明窗口
- 控制面板

## 8. 下一步

下一步建议实现 `BarrageManager`。该步骤已在步骤 03 中完成，详见 `step-03-barrage-manager.md`。

原因：

项目现在可以生成弹幕项，但还不能排队、去重、限制密度、分配轨道、暂停或恢复。在构建 PySide6 弹幕窗口之前，`BarrageManager` 是下一个必需的层。
