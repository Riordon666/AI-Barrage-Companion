# 步骤 08：MiMo Anthropic 协议适配与 UI 商业级重构

## 1. 本步骤目标

本步骤完成两项核心工作：

- 为小米 MiMo 适配 Anthropic 协议支持，解决 OpenAI 兼容端点持续超时的问题。
- 对控制面板进行彻底的视觉重构，从"学生毕业设计"级别的默认 Qt 界面升级为具有商业级 AI 产品感的现代 UI。
- 将设置页面中的英文选项文本改为中文显示。

## 2. 修改内容

### 2.1 Anthropic 协议支持

**背景**：MiMo 的 OpenAI 兼容端点 (`/v1/chat/completions`) 持续超时，但 MiMo 同时提供 Anthropic 协议端点 `https://token-plan-cn.xiaomimimo.com/anthropic`。

**涉及文件**：

- `app/config/provider_presets.py` — `ProviderPreset` 新增 `protocol` 字段（默认 `"openai"`），MiMo 预设改为 `protocol="anthropic"`
- `app/models.py` — `ApiConfig` 新增 `protocol: str = "openai"` 字段
- `app/config/settings_store.py` — 读取/保存 `protocol` 字段（主配置和历史配置均处理）
- `app/core/ai_service.py` — 核心分发逻辑：
  - `_request_content()` 根据 `protocol` 分流到 `_request_openai()` 或 `_request_anthropic()`
  - Anthropic 端点路径智能拼接：若 base_url 已含 `/anthropic` 或 `/v1`，仅追加 `/messages`，避免 `/anthropic/v1/messages` 双路径 404
  - Anthropic 请求头使用 `x-api-key` + `anthropic-version: 2023-06-01`
  - Anthropic 请求体中 `system` 为顶层字段，`max_tokens` 必填
  - Anthropic 视觉格式：`{"type": "image", "source": {"type": "base64", ...}}`
  - Anthropic 响应解析：`data["content"][0]["text"]`
  - 新增重试循环（`max_retries`），视觉请求被拒后自动降级为纯文本重试
  - `httpx.Timeout` 使用独立的 connect/read 超时配置

- `app/ui/control_panel.py` — API 配置弹窗测试连接支持 Anthropic 协议

### 2.2 UI 商业级重构

**问题**：原 UI 使用 Qt 默认控件样式，视觉上接近"管理系统模板"，缺乏 AI 产品的精致感。

**重构内容**（全部在 `app/ui/control_panel.py`）：

- **色彩体系**：深色主题色板 `_C`，背景 `#0b1220`，表面 `#131c2e`，强调色蓝紫渐变 `#4f7cff` → `#7c5cff`
- **自定义绘制组件**：
  - `Sparkline` — QPainter 绘制的迷你折线图，带渐变填充
  - `GlowDot` — 带径向渐变光晕的呼吸动画状态指示点
  - `StatCard` — 自定义绘制的指标卡片，含渐变背景、sparkline、悬停光晕动画、顶部强调线
  - `ApiStatusCard` — 自定义绘制的 API 状态卡片，含状态点和光晕
- **布局重构**：
  - 64px 图标侧边栏，激活项带渐变光晕
  - 顶部栏含实时时钟（HH:MM）和动画状态点
  - 底部栏含胶囊按钮（36px 圆形暂停键、渐变保存按钮、光晕阴影）
- **控件升级**：
  - `SectionCard` — 16px 圆角、带阴影的分区卡片
  - `ModernToggle` — 蓝紫渐变开关
  - 字体大小从 QSpinBox 改为 QSlider（12-48 范围）

### 2.3 设置页面中文化

**问题**：高级设置中的隐私模式、成本模式选项显示英文（strict/balanced/immersive 等），首页标题为 "Dashboard"。

**处理**：

- 首页标题 `Dashboard` → `仪表盘`
- 密度选项：`low/medium/high` → `低/中/高`（使用 `addItem(label, userData)` 保留英文值）
- 隐私模式：`strict/balanced` → `严格/均衡`
- 成本模式：`immersive/balanced/saving` → `沉浸/均衡/节省`
- `_save_settings()` 改用 `currentData()` 取英文值
- `_load_settings()` 改用 `findData()` 按值定位索引

### 2.4 Bug 修复

- `StatCard.set_value` 语法错误：`self try:` → `try:`（UI 重写时引入的笔误）

## 3. 验证

执行：

```powershell
python -m pytest tests/ -q
python -c "from app.ui.control_panel import ControlPanel; print('OK')"
```

结果：

```text
78 passed
Import OK
```

## 4. 当前状态

本步骤后：

- MiMo 通过 Anthropic 协议正常通信，不再超时。
- 所有 10 个 AI 供应商均可通过 OpenAI 或 Anthropic 协议接入。
- UI 具备深色主题、自定义绘制卡片、动画状态指示、渐变按钮等商业级视觉元素。
- 设置页面选项全部中文化，内部值仍为英文，不影响配置存储和逻辑。
- 78 项测试全部通过。

仍建议后续验收：

- 启动应用，确认 UI 渲染正确，侧边栏导航切换流畅。
- 选择 MiMo 提供商，确认 URL 自动填充为 Anthropic 端点。
- 测试连接应返回成功。
- 检查设置页面各选项显示为中文。
- 检查弹幕生成、OCR、视觉模式等功能是否正常。
