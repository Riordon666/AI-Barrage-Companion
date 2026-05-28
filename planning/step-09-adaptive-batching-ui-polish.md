# 步骤 09：自适应弹性算法、UI 重构与功能完善

## 1. 本步骤目标

本步骤完成大规模功能增强与 UI 重构，将项目从"能跑"推向"好用"：

- **弹幕生成架构重构**：截屏与 AI 生成解耦，新增自适应弹性算法，根据 API 响应时间动态调节批次大小、并发数和缓冲区阈值
- **AI/模拟弹幕混合策略**：按成本模式控制比例，冷启动阶段持续注入模拟弹幕填补 AI 空档期
- **累积 OCR 模式**：两次 AI 请求之间收集全部 OCR 结果，一次性发送
- **UI 全面重写**：从深色主题切换为浅色紫黄配色，侧边栏 Logo 重构，导航栏新增 API 配置独立页面，滑块组件现代化，时间/星期显示修正
- **新增设置项**：不透明度、移动速度、字体大小/显示区域改为五档滑块
- **实时统计面板重做**：缓存池弹幕（仅 AI）、API 平均响应时间（EMA 平滑）、删除无效面板
- **许可证**：项目采用 GPL-3.0

## 2. 修改内容

### 2.1 弹幕生成核心重构

**问题**：原架构截屏和 AI 生成耦合在同一个函数中，`_generation_future` 未完成时直接跳过截屏，导致截屏频率无法保证。

**解决方案**（`app/ui/application.py`）：

- **截屏/AI 解耦**：`_capture_and_generate` 只负责截屏+分析+存储场景，不再阻塞等待 AI。AI 生成由 `_fill_buffer_tick` 独立触发
- **自适应弹性算法**：
  - 用 EMA（α=0.3）追踪 API 响应时间的平滑平均值 `_latency_ema_s`
  - 批次大小动态公式：`batch = clamp(6, lat × 1.3 + 3, 50)`
  - 缓冲区阈值动态公式：`threshold = batch × factor × density_scale`
  - 并发数根据延迟分四档：<3s 1并发 → 3-8s 2并发 → 8-20s 3并发 → >20s 4并发
  - 并发数乘以成本系数：沉浸×1.0、均衡×0.6、节省×0.3
- **MiMo 适配**：端点从 Anthropic 协议改回 OpenAI 兼容协议 `https://api.xiaomimimo.com/v1`，请求体注入 `thinking: {"type": "disabled"}`（参考 danmuAI 项目）
- **弹幕发送节奏**：缓冲区 > 25 条时自动拉长发送间隔（最多 4x），避免 AI 批次一次性倾泻

### 2.2 冷启动预热

**问题**：启动后 AI 首次响应需 10-40 秒，期间弹幕完全空白。

**解决方案**：

- 新增 `_ai_ever_responded` 标志，AI 首次成功响应前为 False
- 启动阶段：注入 16+ 条欢迎弹幕（"开播了！""来了来了"等），fill_tick 以 300-600ms 间隔持续补充模拟弹幕（缓冲目标 50 条）
- AI 首次响应到达后自动切换为 AI+模拟混合模式，日志输出 `首次 AI 响应到达`
- AI/模拟弹幕分池计数：`_ai_buf_count` 只统计 AI 弹幕，AI 触发阈值只看 AI 数量，模拟弹幕不干扰

### 2.3 成本模式比例

**问题**：原实现模拟弹幕占比极低（沉浸模式仅 4.6%），不符合预期。

**解决方案**：

| 模式 | 每 tick 模拟注入 | 预期比例 |
|---|---|---|
| 沉浸 | 0-1 条 | ≈ 3:1 (AI:Mock) |
| 均衡 | 0-2 条 | ≈ 1:1 |
| 节省 | 0-4 条 | ≈ 3:7 |

### 2.4 累积 OCR 模式

**问题**：OCR 结果只保留最新一条，AI 无法获取完整上下文。

**解决方案**（`app/ui/application.py`）：

- 新增 `_ocr_accumulator: list[str]`，两次 AI 请求之间收集所有去重后的 OCR 文字（最多 20 条）
- AI 请求时取最近 10 条用 ` | ` 拼接发送
- 请求发出后清空累加器，下一轮重新收集
- OCR 字数上限从 300 提升到 800

### 2.5 UI 浅色主题重写

**配色方案**（`app/ui/control_panel.py`）：

- 背景：白色 `#ffffff` / 浅灰 `#f8f7fc`
- 强调色：紫色 `#9F82FD` / 黄色 `#FBEA03`
- 卡片：半透明紫底 `rgba(159,130,253,0.07)`

**侧边栏**：

- 删除旧的 "A" 图标 + "AI BARRAGE / COMPANION" 文字
- 替换为紫→黄渐变圆角卡片：上行"AI 弹幕伴侣"、下行"AI BARRAGE COMPANION"
- 新增 API 配置独立导航页（第 2 位），内联表单替代弹窗
- 版本号改为 v0.1.0（开发版）

**设置页面**：

- 弹幕密度、显示区域、字体大小、不透明度、移动速度合并到一张卡片"弹幕设置"
- 显示区域和字体大小改为五档 `TickedSlider`，取消刻度标签，右侧显示当前值
- 新增不透明度（连续 0-100%）和移动速度（五档）滑块
- 所有滑块组件 `NoScrollSlider` / `TickedSlider` 禁用滚轮事件
- 滑块配色：透明背景、黄色边框/手柄、按下变紫
- 高级设置（隐私/成本/截屏间隔）改为三栏横向布局
- QDoubleSpinBox 上下按钮现代化（圆角、悬浮高亮）

**首页**：

- 问候卡片：修正星期映射（`'一二三四五六日'`），移除"Barrager"字样，时间高度增大
- 统计卡片：删除所有折线图（Sparkline），数值居中显示
- 右侧实时状态面板删除；新增"缓存池弹幕"卡片（仅显示 AI 弹幕数）
- 统计刷新间隔从 2 秒改为 1 秒
- API 响应时间显示 EMA 平滑平均值（非最后一次瞬时值）

**弹幕速度统一**：

- 人格倍率从 0.65–1.2 收紧到 0.85–1.05
- 随机抖动从 ±15% 缩减到 ±5%

### 2.6 截屏性能优化

**问题**：原图直接分析，高分辨率屏幕导致卡顿。

**解决方案**（`app/ui/application.py`）：

- 新增 `_shrink_frame()` 方法，用 Pillow 将截图画缩放到最长边 800px 后再分析
- OCR 仍使用原始分辨率（独立预处理至 1920px）
- OCR 预处理 `autocontrast` 增加 `cutoff=2` 参数减少噪声

### 2.7 截屏调度修正

**问题**：`BasicCaptureScheduler` 按成本模式强制覆盖截屏间隔（节省≥8s、沉浸≥1s），用户设置形同虚设。

**解决方案**（`app/core/capture_scheduler.py`）：

- 删除成本模式对截屏间隔的覆盖
- 截屏间隔严格按用户设置执行，`max(500, interval_ms)` 保证最低 500ms

### 2.8 弹幕密度速率

| 密度 | 普通场景 | 高亮场景 | 约每秒条数 |
|---|---|---|---|
| 低 | 667–2000ms | 250–1000ms | 0.5–1.5 |
| 中 | 333–1000ms | 125–500ms | 1–3 |
| 高 | 167–500ms | 60–250ms | 2–6 |

### 2.9 Tesseract OCR 修复

**问题**：Windows 版 Tesseract（UB-Mannheim）将 `TESSDATA_PREFIX` 理解为 tessdata 目录本身（非父目录），导致语言包找不到。

**解决方案**（`app/core/ocr_engine.py`）：

- `TESSDATA_PREFIX` 环境变量指向 `tessdata/` 子目录
- 新增 `_get_bundled_dir()` 函数，支持 PyInstaller 打包时查找项目内捆绑的 Tesseract
- 查找优先级：捆绑目录 > PATH > 固定路径 > 环境变量

### 2.10 其他修复

- **时间显示修正**：Python `tm_wday` 0=周一，中文星期数组改为 `'一二三四五六日'`
- **缓存命中阈值**：从 30 条降至 5 条，同一场景有 5 条缓存即复用
- **缓存容量**：`max_items_per_scene` 从 10 提升到 50
- **缓冲区上限**：从 10 → 80 → 120
- **AiConfigDialog**：弹窗改为 API 页面内联表单（提供商/URL/模型/Key + 测试/保存 + 历史列表）
- **日志增强**：配置更新日志输出完整参数（来源/密度/成本/隐私/截屏间隔/显示区域/不透明度/速度）
- **页面标题重构**：每页标题由顶部共享栏统一显示（左侧粗体标题 + 右侧副标题）
- **关于页面**：标签改用换行文字防溢出，禁用水平滚动

## 3. 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `app/constants.py` | 修改：密度速率、速度快慢、缓冲区上限 |
| `app/models.py` | 新增：font_size_level、opacity_percent、speed_level |
| `app/core/ai_service.py` | 修改：MiMo 端点/协议、系统提示词 |
| `app/core/application.py` | 重写：生成架构、自适应算法、并发控制、累积OCR、冷启动、图片压缩 |
| `app/core/barrage_cache.py` | 修改：缓存容量 10→50 |
| `app/core/capture_scheduler.py` | 修改：移除成本模式对间隔的覆盖 |
| `app/core/ocr_engine.py` | 修改：TESSDATA_PREFIX、OCR上限300→800、预处理参数、Windows OCR容错 |
| `app/config/provider_presets.py` | 修改：MiMo 端点/协议/模型 |
| `app/ui/control_panel.py` | 重写：配色、导航、首页卡片、设置页、API页、关于页、滑块组件、SpinBox |
| `app/ui/overlay.py` | 新增：不透明度、移动速度支持 |
| `tests/test_capture_scheduler.py` | 修改：匹配新的调度逻辑 |
| `tests/test_integration.py` | 修改：匹配新的生成架构、FakePanel新增信号 |
| `tests/test_ocr_engine.py` | 修改：OCR上限测试值 |

## 4. 验证

```powershell
python -m pytest tests/ -q
```

结果：

```text
78 passed
```

## 5. 当前状态

本步骤后：

- 9 个 AI 供应商均可正常接入（OpenAI / DeepSeek / Qwen / Kimi / GLM / SiliconFlow / OpenRouter / MiMo / Ollama）
- 弹幕生成采用自适应弹性算法，自动适应从 Groq（<1s）到 MiMo（35s+）的各类 API 延迟
- 冷启动不再空档，AI 到达前持续模拟弹幕
- AI 与模拟弹幕按成本模式混合比例
- OCR 累积模式提供更完整的屏幕上下文
- 浅色紫黄配色 UI，滑块式设置，实时统计卡片
- 截屏间隔真正按用户设置运行
- 弹幕速度统一，不再出现速度差异过大
- 78 项测试全部通过
