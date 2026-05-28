# AI Barrage Companion（ABC）

**AI 驱动的虚拟弹幕陪伴应用。** 轻量分析屏幕状态，生成 AI 或本地弹幕，在透明悬浮层中滚动显示，模拟"有人在看、有人在吐槽、有人在陪伴"的直播氛围。

![Python](https://img.shields.io/badge/python-3.9+-blue) ![License](https://img.shields.io/badge/license-GPL--3.0-green) ![Version](https://img.shields.io/badge/version-0.1.0-orange)

---

## 效果

透明弹幕层覆盖在桌面上方，弹幕从右向左滚动：

```
┌─────────────────────────────────────────────┐
│  ┌────────────────────────────────────────┐  │
│  │    这波可以          稳住稳住          │  │
│  │              有点东西    前面说得对    │  │
│  │  ─── 透明弹幕层（点击穿透）────────    │  │
│  └────────────────────────────────────────┘  │
│                   桌面                         │
└─────────────────────────────────────────────┘
```

---

## 功能

### 已完成（MVP）

- **屏幕截图** — 使用 `mss` 定时截取主屏，不上传、不保存
- **画面变化分析** — 缩略图帧差检测，识别静止/正常/快速/重复场景
- **屏幕文字识别（OCR）** — 可选启用 Tesseract OCR，提取屏幕文字作为 AI 上下文
- **屏幕上下文感知** — 自动检测活动窗口标题和应用类型，告诉 AI 用户正在做什么
- **隐私过滤** — 严格模式禁止截图、OCR、窗口标题、文件名、URL、聊天文本进入 AI 请求
- **模拟弹幕** — 无 API Key 时生成本地弹幕，内置 5 类人格 × 4 种场景模板
- **AI 弹幕** — 兼容 OpenAI 格式接口，可配合视觉模型根据截图内容生成弹幕
- **弹幕缓存** — 按场景+屏幕上下文缓存弹幕，减少 API 调用
- **弹幕调度** — 去重、密度限制（低/中/高）、轨道分配、优先级插队
- **透明窗口** — PySide6 置顶透明层，弹幕从右向左平滑动画
- **控制面板** — 暂停/继续、密度切换、显示区域调节、字体大小、API 配置
- **系统托盘** — 显示/隐藏控制面板、退出
- **配置持久化** — 设置保存到本地 JSON 文件
- **失败降级** — AI 超时或失败时自动切换模拟弹幕，不中断运行

### 内置人格

| 人格 | 说明 | 示例 |
|------|------|------|
| `troll` | 轻度吐槽 | "这也行啊" "别急" |
| `support` | 鼓励安慰 | "稳住稳住" "这波漂亮" |
| `sarcastic` | 阴阳怪气 | "主播醒了" "战略暂停" |
| `follower` | 跟风复读 | "前面说得对" "确实" |
| `fun` | 玩梗乐子 | "节目来了" "高能来了" |

### 支持的 AI 提供商

OpenAI、DeepSeek、阿里云百炼（Qwen）、Moonshot（Kimi）、智谱 GLM、SiliconFlow、OpenRouter、Ollama 本地、自定义 OpenAI 兼容接口。

---

## 快速开始

### 环境要求

- Python 3.9+
- Windows 10/11（主屏透明窗口）

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

> Python 3.9+ · OCR 使用 Windows 10/11 内置引擎，无需额外安装

### 运行

```powershell
python main.py
```

启动后：透明弹幕层覆盖桌面 → 控制面板弹出 → 默认模拟弹幕（无需 API Key）。

### 配置 API Key

在控制面板中：
1. 选择 AI 提供商（如 DeepSeek、OpenAI）
2. 填入 API Key
3. 点击"保存配置"

配置会自动保存到 `abc-settings.json`，下次启动自动加载。

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
      ai_service.py             # OpenAI 兼容 AI 弹幕
      barrage_cache.py          # 弹幕缓存
      barrage_manager.py        # 弹幕调度
      capture_scheduler.py      # 截屏策略调度
      screen_context.py         # 屏幕上下文（窗口标题 / 应用检测）
      ocr_engine.py             # OCR 屏幕文字提取
      logger.py                 # 日志系统
      utils.py                  # 共享工具

    ui/
      overlay.py                # 透明弹幕窗口
      control_panel.py          # 控制面板
      tray.py                   # 系统托盘
      application.py            # 应用主循环

    config/
      settings.py               # 默认配置
      settings_store.py         # 配置读写
      provider_presets.py       # AI 提供商预设

  tests/                        # 单元测试
  planning/                     # 项目文档和规划
```

### 核心数据流

```text
屏幕截图
    ↓
屏幕上下文提取（窗口标题 / 应用检测）
    ↓
OCR 屏幕文字识别（可选）
    ↓
帧差异分析 → FrameStats + SceneSummary
    ↓
隐私过滤 → 阻止敏感字段
    ↓
弹幕缓存 → 命中则直接返回
    ↓
AI 服务 / 模拟弹幕 → GenerationResult
    ↓
发送缓冲区（节奏分离）
    ↓
弹幕调度 → 去重 + 密度 + 轨道分配
    ↓
透明窗口渲染 → 右向左动画
```

### 模块设计原则

- **UI 不直接调用 AI** — `Application` 通过 `RuntimeController` 协调各模块
- **AI 服务不依赖 PySide6** — `ai_service.py` 纯 HTTP 逻辑
- **截屏模块不保存图片** — `MssScreenCapture` 只在内存中处理
- **跨模块通信统一使用 `models.py` 的数据结构** — 不使用散乱的字典
- **所有网络请求设置超时** — 避免卡死 UI

---

## 隐私说明

- 截图不上传、不保存，仅用于本地帧差分析和 OCR
- 默认仅发送粗粒度场景摘要（activity、pace、event、confidence）
- 用户主动启用「屏幕文字识别」后，OCR 提取的文字才会加入 AI 请求
- 用户主动启用「窗口标题检测」后，窗口标题/应用类型才会加入 AI 请求
- 严格模式禁止将截图、OCR 文本（非用户主动启用时）、窗口标题、文件名、URL、聊天文本发送给 AI
- API Key 不写入日志
- 用户可随时暂停，暂停时停止截屏和 AI 请求
- 配置文件 `abc-settings.json` 保存在本地

---

## 测试

```powershell
pytest -v
```

测试覆盖：帧分析、弹幕调度、AI 服务、隐私过滤、弹幕缓存、截屏策略、配置读写、OCR 引擎、屏幕上下文、RuntimeController 集成链路。（共 77 个测试）

---

## 开发状态

项目已完成 MVP 全部核心功能，正在进行稳定性打磨和体验优化。详见 `planning/` 目录下的规划文档。
