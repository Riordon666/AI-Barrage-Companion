# 步骤 03：弹幕调度器

## 1. 本步骤目标

本步骤在弹幕生成和未来 UI 渲染之间添加调度层。

在此步骤之前，项目可以生成 `BarrageItem` 对象，但无法决定：

- 哪些弹幕应该优先显示
- 同时可以显示多少条弹幕
- 每条弹幕应该使用哪个轨道
- 是否应该抑制重复文本
- 暂停和恢复时应该发生什么

## 2. 新增或更新的文件

新增：

```text
app/core/barrage_manager.py
tests/test_barrage_manager.py
planning/step-03-barrage-manager.md
```

更新：

```text
app/constants.py
main.py
planning/project-plan.md
planning/implementation-roadmap.md
planning/step-02-privacy-and-mock-generator.md
```

## 3. 实现

`BasicBarrageManager` 添加在：

```text
app/core/barrage_manager.py
```

它实现了现有的 `BarrageManager` 协议接口：

- `enqueue(items)` — 入队
- `tick(now, viewport_width, viewport_height)` — 时钟推进
- `set_density(density)` — 设置密度
- `pause()` — 暂停
- `resume()` — 恢复

`tick()` 返回新调度的 `TrackAssignment` 对象。未来的 PySide6 弹幕窗口可以使用这些分配结果来渲染和动画弹幕。

## 4. 调度规则

密度上限：

```text
低密度 -> 最多 3 条同时显示
中密度 -> 最多 6 条同时显示
高密度 -> 最多 10 条同时显示
```

轨道行为：

- 轨道数量也受视口高度限制。
- 新弹幕使用最低可用的轨道索引。
- 活跃轨道在 `item.duration_seconds` 后释放。
- 每条分配结果包含 `track_index`、`start_x`、`y` 和 `speed_px_per_second`。

去重逻辑：

- 空文本被忽略。
- 重复的待处理文本被忽略。
- 重复的活跃文本被忽略。
- 最近显示过的文本在 `DEFAULT_DUPLICATE_WINDOW_SECONDS` 内被阻止。

优先级逻辑：

- 待处理项按优先级降序排列。
- 优先级相同时，`created_at` 更早的优先调度。

暂停和恢复：

- `pause()` 阻止新的轨道分配。
- `resume()` 允许待处理弹幕再次被调度。

## 5. 入口更新

根目录 `main.py` 现在演示这条最小链路：

```text
SceneSummary
-> BasicPrivacyGuard
-> MockBarrageService
-> BasicBarrageManager
-> TrackAssignment 输出
```

运行：

```powershell
python -B main.py
```

预期输出：

```text
AI Barrage Companion scaffold ready
density=medium, cost_mode=balanced
privacy_allowed=True
mock_barrages=...
scheduled_tracks=0, 1, 2
```

具体的弹幕文本可能变化，因为模拟生成从本地模板中随机选取。

## 6. 新增测试

`tests/test_barrage_manager.py` 覆盖：

- 低密度最多调度 3 条弹幕
- 活跃轨道在持续时间结束后释放
- 轨道释放后继续调度待处理弹幕
- 重复文本被抑制
- 重复窗口过期后重复文本可再次显示
- 暂停阻止新分配
- 恢复后继续调度待处理弹幕
- 高优先级弹幕优先调度
- 视口高度限制轨道数量
- 无效密度抛出 `ValueError`

## 7. 当前完成状态

已完成：

- 队列管理
- 去重
- 密度限制
- 轨道分配
- 暂停和恢复
- 优先级排序
- 调度行为的单元测试

仍未完成：

- 真实截屏
- 帧差异分析
- AIService
- BarrageCache
- PySide6 透明窗口
- 控制面板

## 8. 重要说明

本步骤故意不实现视觉效果。`BasicBarrageManager` 只决定应该渲染什么以及从哪里开始。后续的 UI 层负责绘制和动画这些分配结果。

原因：

将调度逻辑与 PySide6 分离，可以防止 UI 代码、AI 生成和队列逻辑耦合在一起。

## 9. 下一步

下一步建议实现一个最小化的 PySide6 弹幕渲染窗口。

原因：

项目现在可以生成和调度弹幕，但用户还无法在屏幕上看到它们。一个最小化的透明窗口将在添加截屏或真实 AI 之前，验证核心产品体验。
