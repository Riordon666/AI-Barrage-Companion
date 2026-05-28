# AI弹幕伴侣-AI Barrage Companion（ABC）

**AI 驱动的虚拟弹幕陪伴应用。** 轻量分析屏幕状态，调用 AI 或本地生成弹幕，在透明悬浮层中滚动显示，模拟"有人在看、有人在吐槽、有人在陪伴"的直播氛围。

![Python](https://img.shields.io/badge/python-3.9+-blue) ![License](https://img.shields.io/badge/license-GPL--3.0-green) ![Version](https://img.shields.io/badge/version-0.1.0-orange) ![Tests](https://img.shields.io/badge/tests-78%20passed-brightgreen)

---

## 效果

透明弹幕层覆盖在桌面上方，弹幕从右向左平滑滚动：

```
┌─────────────────────────────────────────────┐
│  ┌────────────────────────────────────────┐ │
│  │    这波可以          稳住稳住            │ │  
│  │              有点东西    前面说得对      │ │
│  │  ─── 透明弹幕层（点击穿透）────────       │ │
│  └────────────────────────────────────────┘ │
│                   桌面                       │
└─────────────────────────────────────────────┘
```

---

## 功能

### 已完成（v0.1.0）

- **屏幕截图** — 使用 `mss` 定时截取主屏，缩略图分析（最长边 800px），不上传、不保存
- **画面变化分析** — 帧差检测，识别静止/正常/快速/重复场景，生成粗粒度场景摘要
- **屏幕文字识别（OCR）** — Windows 10/11 内置 OCR 引擎，自动降级 Tesseract，累积模式收集上下文
- **屏幕上下文感知** — 自动检测活动窗口标题和应用类型（50+ 应用签名），告诉 AI 用户正在做什么
- **隐私过滤** — 严格模式禁止截图、OCR、窗口标题、文件名、URL、聊天文本进入 AI 请求；所有屏幕内容功能默认关闭
- **10 家 AI 提供商** — OpenAI / DeepSeek / 阿里云百炼 Qwen / Moonshot Kimi / 智谱 GLM / SiliconFlow / OpenRouter / 小米 MiMo / Ollama 本地 / 自定义接口
- **双协议支持** — OpenAI 兼容协议 + Anthropic Messages API
- **自适应弹性算法** — EMA 平滑追踪 API 响应时间，动态调节批次大小、并发数、缓冲区阈值
- **冷启动预热** — AI 首次响应前持续注入模拟弹幕，不出现空档期
- **AI/模拟混合比例** — 按成本模式（沉浸/均衡/节省）控制 AI 与模拟弹幕占比
- **弹幕缓存** — 按场景+屏幕上下文缓存 AI 弹幕，减少 API 调用
- **弹幕调度** — 去重、密度限制（低/中/高）、轨道分配、优先级插队
- **透明窗口** — PySide6 置顶透明层，弹幕从右向左平滑动画，支持不透明度/速度调节
- **控制面板** — 浅色紫黄配色侧边栏 UI，独立首页/弹幕设置/API 配置/关于页面
- **系统托盘** — 显示/隐藏控制面板、退出
- **配置持久化** — 设置保存到本地 JSON 文件，原子写入
- **失败降级** — AI 超时或失败自动切换模拟弹幕，不中断运行

### 内置人格

| 人格 | 说明 | 示例 |
|------|------|------|
| `troll` | 轻度吐槽 | "这也行啊" "别急" |
| `support` | 鼓励安慰 | "稳住稳住" "这波漂亮" |
| `sarcastic` | 阴阳怪气 | "主播醒了" "战略暂停" |
| `follower` | 跟风复读 | "前面说得对" "确实" |
| `fun` | 玩梗乐子 | "节目来了" "高能来了" |

---
## 发行版
可直接点击发行版下载可用的exe文件，打开即用

---
## 快速开始

### 环境要求

- Python 3.9+
- Windows 10/11

### 安装

```powershell
# 克隆仓库
git clone https://github.com/Riordon666/AI-Barrage-Companion.git
cd AI-Barrage-Companion

# 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> OCR 使用 Windows 10/11 内置引擎，无需额外安装。可选安装 Tesseract-OCR 作为降级后端。 可将Tesseract-OCR安装到根目录ocr文件夹（自行创建）

### 运行

```powershell
python main.py
```

启动后：透明弹幕层覆盖桌面 → 控制面板弹出 → 冷启动阶段注入模拟弹幕 → AI 就绪后自动切换混合模式。

### 配置 API Key

在控制面板中点击侧边栏 **API 配置**：
1. 选择 AI 提供商（如 DeepSeek、OpenAI、MiMo）
2. 填入 API Key
3. 点击"测试连接"验证
4. 点击"保存配置"

配置自动保存到 `abc-settings.json`，下次启动自动加载。

### 配置教程

#### 1. 获取 API Key

以 DeepSeek 为例（推荐，性价比高）：

1. 访问 [platform.deepseek.com](https://platform.deepseek.com) 注册账号
2. 进入「API Keys」页面，点击「创建 API Key」
3. 复制 Key 并妥善保存（只显示一次）

> 其他提供商操作类似：OpenAI 需境外访问，阿里云百炼需实名认证，MiMo 需小米账号申请。

#### 2. 配置 API

打开控制面板，点击左侧 **🔑 API 配置**：

1. **选择提供商** — 下拉框选择（如 DeepSeek），Base URL 和模型列表会自动填充
2. **填入 API Key** — 粘贴上一步获取的 Key
3. **测试连接** — 点击按钮验证网络和 Key 有效性
4. **保存配置** — 测试通过后点击保存

> 提示：配置历史会保留在右侧列表中，双击可快速切换。

#### 3. 弹幕设置

点击左侧 **⚙ 弹幕设置**：

| 设置项 | 说明 | 建议值 |
|--------|------|--------|
| 弹幕密度 | 同时显示弹幕数量 | 中（默认） |
| 显示区域 | 弹幕覆盖屏幕的高度比例 | 65%（默认） |
| 字体大小 | 弹幕文字大小 | 18px（默认） |
| 不透明度 | 弹幕层的透明程度 | 80-100% |
| 移动速度 | 弹幕滚动快慢 | 中（默认） |

调整后即时生效，无需重启。

#### 4. 高级设置

在同一页面下方「高级设置」区域：

| 设置项 | 说明 |
|--------|------|
| 隐私模式 | 严格（不发送任何屏幕内容）/ 均衡（按下方开关决定） |
| 成本模式 | 沉浸（AI 为主）/ 均衡 / 节省（模拟弹幕为主） |
| 截屏间隔 | 两次截屏之间的秒数（越大越省资源） |
| OCR 开关 | 开启后识别屏幕文字，让 AI 弹幕更贴切 |
| 窗口标题 | 开启后检测当前应用，AI 知道你在用什么软件 |

请根据需求自行设置，若有设置不合理，可能会短暂时间内出现弹幕延时、没弹幕的问题。
> 隐私建议：首次使用保持默认设置即可。如需"屏幕内容感知"弹幕，逐步开启 OCR 和窗口标题。

---

## 项目结构

```text
AI-Barrage-Companion/
  main.py                       # 应用入口

  app/
    models.py                   # 核心数据结构
    interfaces.py               # 模块协议接口
    constants.py                # 应用常量

    core/
      screen_capture.py         # mss 屏幕截图
      frame_analyzer.py         # 帧差异分析
      privacy_guard.py          # 隐私过滤
      mock_barrage_service.py   # 模拟弹幕生成
      ai_service.py             # AI 弹幕（OpenAI + Anthropic 协议）
      barrage_cache.py          # 弹幕缓存
      barrage_manager.py        # 弹幕调度
      capture_scheduler.py      # 截屏策略调度
      screen_context.py         # 屏幕上下文（窗口标题 / 应用检测）
      ocr_engine.py             # OCR 屏幕文字提取（WinRT + Tesseract 降级）
      logger.py                 # 日志系统
      utils.py                  # 共享工具

    ui/
      overlay.py                # 透明弹幕窗口
      control_panel.py          # 控制面板（浅色紫黄主题）
      tray.py                   # 系统托盘
      application.py            # RuntimeController 主循环

    config/
      settings.py               # 默认配置
      settings_store.py         # 配置读写（原子写入）
      provider_presets.py       # 10 家 AI 提供商预设

  tests/                        # 单元测试（78 个）
  planning/                     # 项目文档和规划
```

### 核心数据流

```text
屏幕截图
    ↓
屏幕上下文提取（窗口标题 / 应用检测）
    ↓
OCR 屏幕文字识别（累积模式，可选）
    ↓
帧差异分析 → FrameStats + SceneSummary
    ↓
隐私过滤 → 阻止敏感字段
    ↓
弹幕缓存 → 命中则直接返回
    ↓
AI 服务（自适应批次） / 模拟弹幕 → GenerationResult
    ↓
发送缓冲区（节奏分离，自动调速）
    ↓
弹幕调度 → 去重 + 密度 + 轨道分配
    ↓
透明窗口渲染 → 右向左动画
```

### 模块设计原则

- **UI 不直接调用 AI** — `Application` 通过 `RuntimeController` 协调各模块
- **AI 服务不依赖 PySide6** — `ai_service.py` 纯 HTTP 逻辑，支持 OpenAI 和 Anthropic 双协议
- **截屏模块不保存图片** — `MssScreenCapture` 只在内存中处理
- **跨模块通信统一使用 `models.py` 的数据结构**
- **所有网络请求设置超时**，避免卡死 UI
- **截屏与 AI 生成解耦**，截屏频率不受 AI 响应时间影响

---

## 隐私说明

- 截图不上传、不保存，仅用于本地帧差分析和 OCR
- 默认仅发送粗粒度场景摘要（activity、pace、event、confidence）
- 用户主动启用「屏幕文字识别」后，OCR 提取的文字才会加入 AI 请求
- 用户主动启用「窗口标题检测」后，窗口标题/应用类型才会加入 AI 请求
- 严格模式禁止任何屏幕内容进入 AI 请求
- API Key 不写入日志，`__repr__` 自动脱敏
- 用户可随时暂停，暂停时停止截屏和 AI 请求
- 配置文件 `abc-settings.json` 保存在本地，使用原子写入防止损坏

---

## 测试

```powershell
pytest -v
```

78 个测试全部通过。覆盖：帧分析、弹幕调度、AI 服务、隐私过滤、弹幕缓存、截屏策略、配置读写、OCR 引擎、屏幕上下文、RuntimeController 集成链路。

---

## 开发状态

v0.1.0 MVP 已完成全部核心功能。当前阶段聚焦稳定性打磨与体验优化。详见 `planning/` 目录下的规划文档。

### 技术栈

Python 3.9+ / PySide6 / mss / httpx / Pillow / pytesseract（可选）

### 许可证

[GPL-3.0](LICENSE)
