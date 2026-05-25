# AI Barrage Companion（ABC）项目拆分与实施规划

## 1. 现状与目标

当前项目已完成第一步工程骨架。仓库中已有 `app/`、`tests/`、`requirements.txt`、核心数据模型、接口协议和根目录入口 `main.py`。问题原因是项目刚从示例脚本阶段进入正式工程阶段，目前只完成了结构和接口边界，还没有实现截屏、AI 调用、弹幕调度或 PySide6 窗口。

当前已验证：

- `python main.py` 可以运行。
- `python -m compileall app tests` 可以通过。
- 文档类文件统一放在 `planning/`。
- Python 缓存文件已加入 `.gitignore`。

本规划目标是把项目拆成可连续实现、可测试、接口清晰的阶段，优先完成 MVP：

- 本地截屏，但不上传截图。
- 本地生成粗粒度场景摘要。
- 支持模拟弹幕和 AI 弹幕两种来源。
- 透明置顶弹幕窗口右向左滚动。
- 支持暂停、继续、密度调节、API 配置。
- 所有模块之间通过明确数据结构通信，避免 UI、AI、截屏逻辑耦合。

## 2. 同类项目调研结论

本节基于 2026-05-25 的联网调研，链接和功能描述可能随项目更新变化。真实性判断：这些项目与 ABC 不完全相同，但分别覆盖了“屏幕上下文采集”“桌面 AI 陪伴”“弹幕渲染”三个关键问题，可以作为架构参考。

参考项目：

- Screenpipe：开源本地优先的屏幕与音频记忆项目，强调本地存储、隐私默认、事件驱动采集，避免无意义地连续处理重复画面。参考：https://github.com/screenpipe/screenpipe
- Flicky：桌面语音 AI 伴侣，支持“看屏幕再回答”、自带用户 API Key、本地保存对话、密钥本地保护。参考：https://flicky.dev/
- Open LLM VTuber：开源 AI 伴侣/VTuber 项目，支持语音或文本、多模型、屏幕视觉、透明桌面宠物模式、记忆代理。参考：https://docs.llmvtuber.com/en/
- DPlayer：成熟 HTML5 弹幕播放器，说明弹幕渲染应作为独立引擎能力，和数据来源解耦。参考：https://github.com/DIYgod/DPlayer
- CommentCoreLibrary：通用弹幕核心库，提供 `load`、`insert`、`send`、`start`、`stop`、`time` 等典型弹幕控制接口。参考：https://jabbany.github.io/CommentCoreLibrary/docs/Tutorial.html

对 ABC 的直接改进：

- 截屏策略从“固定 2 到 5 秒截图”升级为“定时采样 + 事件节流”。MVP 仍可定时采样，但接口预留 `CapturePolicy`，后续接入窗口切换、输入停顿、鼠标点击等事件触发。
- 隐私设计从“只是不上传截图”升级为独立 `PrivacyGuard`。所有发送给 AI 的内容先过隐私过滤，第一版禁止 OCR、窗口标题、文件名、聊天文本进入请求。
- AI 接入采用 OpenAI 兼容接口，但抽象为 `BarrageGenerator`。这样 DeepSeek、OpenAI、本地 Ollama、模拟弹幕都可以复用同一调用边界。
- 弹幕渲染借鉴弹幕引擎思路，拆成 `BarrageManager` 和 `OverlayRenderer`。前者只负责队列、轨道、限流；后者只负责 PySide6 动画和窗口。
- 体验上不引入语音、TTS、长期记忆、24 小时记录等重功能。原因是这些项目证明“陪伴感”可以扩展很远，但 ABC 第一版的核心是虚拟观众弹幕，不应被 AI 助手全家桶拖慢。

## 3. 推荐项目结构

```text
AI-Barrage-Companion/
  app/
    __init__.py
    models.py
    interfaces.py
    constants.py

    core/
      __init__.py
      screen_capture.py
      frame_analyzer.py
      privacy_guard.py
      ai_service.py
      mock_barrage_service.py
      barrage_cache.py
      barrage_manager.py
      rate_limiter.py
      scheduler.py

    ui/
      __init__.py
      overlay.py
      control_panel.py
      tray.py

    config/
      __init__.py
      settings.py
      settings_store.py

  tests/
    test_frame_analyzer.py
    test_barrage_manager.py
    test_ai_service.py

  planning/
    project-plan.md
    implementation-roadmap.md
    step-01-scaffold-and-interfaces.md

  requirements.txt
  main.py
  README.md
```

说明：

- `app/models.py` 放跨模块共享的数据结构。
- `app/interfaces.py` 放核心协议和抽象接口，便于后续替换实现。
- `core/` 只处理业务逻辑，不依赖具体 UI 控件。
- `ui/` 只处理窗口、控件、动画和用户操作。
- `config/` 只处理配置默认值、读取和保存。
- `planning/` 只存放策划、审查、规划、记录等非项目运行必需文档。

## 4. 核心数据结构与接口规范

### 4.1 配置模型

```python
@dataclass
class ApiConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 20.0
    max_retries: int = 1


@dataclass
class AppSettings:
    capture_interval_seconds: float = 4.0
    density: Literal["low", "medium", "high"] = "medium"
    cost_mode: Literal["immersive", "balanced", "saving"] = "balanced"
    api: ApiConfig | None = None
    use_mock_when_api_missing: bool = True
    privacy_mode: Literal["strict", "balanced"] = "strict"
    enable_ocr: bool = False
    enable_window_title: bool = False
```

约束：

- API Key 不写入日志。
- 第一版配置可保存到本地 JSON。
- 如果没有 API Key，默认使用模拟弹幕服务，保证应用可演示。
- `privacy_mode = "strict"` 时，禁止把截图、OCR、窗口标题、文件名、URL、聊天文本发送给模型。

### 4.2 截屏与分析模型

```python
@dataclass
class CapturedFrame:
    width: int
    height: int
    timestamp: float
    image: Any


@dataclass
class FrameStats:
    change_ratio: float
    static_seconds: float
    repeat_score: float
    pace: Literal["idle", "slow", "normal", "fast"]


@dataclass
class SceneSummary:
    activity: Literal["idle", "active", "repeated", "unknown"]
    pace: Literal["idle", "slow", "normal", "fast"]
    event: Literal["normal", "highlight", "stuck", "idle"]
    confidence: float


@dataclass
class CapturePolicy:
    min_interval_seconds: float
    max_interval_seconds: float
    event_trigger_enabled: bool
    reason: Literal["timer", "activity_change", "manual", "resume"]
```

接口：

```python
class ScreenCapture:
    def capture(self) -> CapturedFrame: ...


class FrameAnalyzer:
    def analyze(self, frame: CapturedFrame) -> tuple[FrameStats, SceneSummary]: ...


class CaptureScheduler:
    def next_policy(self, last_stats: FrameStats | None, settings: AppSettings) -> CapturePolicy: ...
```

第一版分析规则：

- `change_ratio < 0.02` 且持续超过 10 秒：`event = "idle"`。
- `change_ratio > 0.25`：`pace = "fast"`。
- 高重复度且变化不大：`event = "stuck"`。
- 高变化且不是重复：`event = "highlight"`。
- 其他情况：`event = "normal"`。

### 4.3 隐私过滤接口

```python
@dataclass
class PrivacyDecision:
    allowed: bool
    sanitized_scene: SceneSummary
    blocked_fields: list[str]
    reason: str | None = None
```

接口：

```python
class PrivacyGuard:
    def sanitize(self, scene: SceneSummary, settings: AppSettings) -> PrivacyDecision: ...
```

第一版规则：

- 永远不传截图对象。
- `enable_ocr = False` 时，不允许 OCR 文本进入请求。
- `enable_window_title = False` 时，不允许窗口标题进入请求。
- 如果后续加入应用名识别，密码管理器、银行、聊天软件默认触发暂停或只使用模拟弹幕。

### 4.4 弹幕模型

```python
@dataclass
class BarrageItem:
    id: str
    text: str
    persona: Literal["troll", "support", "sarcastic", "follower", "fun"]
    priority: int
    created_at: float
    duration_seconds: float
```

约束：

- `text` 第一版限制 1 到 12 个中文字符，超长则截断或丢弃。
- 同一批次中相同文本只保留一条。
- 连续 10 秒内同一文本不重复展示。
- `priority` 用于高能事件插队，普通弹幕默认 0，高能弹幕默认 10。

### 4.5 AI 生成接口

```python
@dataclass
class GenerationRequest:
    scene: SceneSummary
    density: Literal["low", "medium", "high"]
    personas: list[str]
    count: int


@dataclass
class GenerationResult:
    items: list[BarrageItem]
    source: Literal["ai", "mock", "cache"]
    error: str | None = None
```

接口：

```python
class BarrageGenerator:
    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class BarrageCache:
    def get(self, scene: SceneSummary, count: int) -> list[BarrageItem]: ...
    def put(self, scene: SceneSummary, items: list[BarrageItem]) -> None: ...
```

AI 返回 JSON 格式：

```json
[
  {"persona": "troll", "text": "这波有点慌"},
  {"persona": "support", "text": "稳住能赢"},
  {"persona": "fun", "text": "节目效果来了"}
]
```

失败处理：

- JSON 解析失败：尝试从纯文本中按行提取短句。
- API 超时：返回模拟弹幕，不阻塞 UI。
- API Key 缺失：直接使用 `MockBarrageService`。
- 返回脏话、人身攻击、隐私内容：过滤该条。

### 4.6 弹幕调度接口

```python
@dataclass
class TrackAssignment:
    item: BarrageItem
    track_index: int
    start_x: int
    y: int
    speed_px_per_second: float
```

接口：

```python
class BarrageManager:
    def enqueue(self, items: list[BarrageItem]) -> None: ...
    def tick(self, now: float, viewport_width: int, viewport_height: int) -> list[TrackAssignment]: ...
    def set_density(self, density: str) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
```

调度规则：

- 低密度：最多 3 条同时显示。
- 中密度：最多 6 条同时显示。
- 高密度：最多 10 条同时显示。
- 轨道高度按字体高度加间距计算。
- 新弹幕优先放入最早空闲轨道。
- 无空闲轨道时，低优先级弹幕延后，高优先级弹幕可插队。

### 4.7 渲染接口

```python
class OverlayRenderer:
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def render(self, assignments: list[TrackAssignment]) -> None: ...
    def set_click_through(self, enabled: bool) -> None: ...
    def close(self) -> None: ...
```

约束：

- 渲染器不直接调用 AI。
- 渲染器不读取截图。
- 所有弹幕运动参数由 `BarrageManager` 给出。
- 第一版只要求主屏可用，多屏支持放到后续版本。

## 5. 开发阶段拆分

### 阶段 0：项目基础搭建

状态：已完成基础骨架，后续只需要在进入阶段 1 前补充必要的 README 或开发说明。

需要完成：

- 已创建 `app/`、`app/core/`、`app/ui/`、`app/config/`、`tests/` 目录。
- 已新增 `requirements.txt`，包含 PySide6、mss、httpx、pytest。
- 已用根目录 `main.py` 作为唯一应用入口。
- 已定义 `models.py` 中的核心数据结构。
- 已新增 `interfaces.py`，定义 `BarrageGenerator`、`OverlayRenderer`、`PrivacyGuard` 等协议边界。
- 已更新 `.gitignore`，忽略 `__pycache__/` 和 `*.py[cod]`。

验收：

- 执行 `python main.py` 后输出 scaffold ready。
- 执行 `python -m compileall app tests` 通过。
- 当前阶段不要求实现弹幕窗口、截屏或 AI 请求。

### 阶段 1：模型与配置

需要完成：

- 实现 `models.py` 中的数据结构。
- 实现默认配置。
- 实现本地配置读写。
- 控制台或简单 UI 能显示当前配置。

验收：

- 无配置文件时使用默认值。
- 配置文件损坏时回退默认值并提示。
- API Key 不出现在日志或异常输出中。

### 阶段 2：截屏与本地分析

需要完成：

- 使用 `mss` 获取当前主屏截图。
- 将连续两帧缩小后计算差异。
- 生成 `FrameStats` 和 `SceneSummary`。
- 不保存截图，不上传截图。
- 实现 `CaptureScheduler`，第一版先按定时策略执行，后续可接入事件触发。

验收：

- 静止桌面能识别为 `idle` 或 `normal`。
- 快速切换窗口或播放视频时能识别为 `fast`。
- 分析模块有单元测试覆盖阈值逻辑。

### 阶段 3：弹幕生成服务

需要完成：

- 实现 `MockBarrageService`。
- 实现 `AIService`，兼容 OpenAI 风格接口。
- 实现 `BarrageCache`，普通场景优先复用缓存。
- 实现 `PrivacyGuard`，AI 请求前必须过滤场景摘要。
- 实现 Prompt 构造、JSON 解析、失败降级。
- 根据 `SceneSummary` 选择不同人格和语气。

验收：

- 无 API Key 时返回模拟弹幕。
- API 正常时返回结构化 `BarrageItem`。
- API 失败时不崩溃，返回模拟或缓存弹幕。

### 阶段 4：弹幕调度器

需要完成：

- 实现弹幕队列。
- 实现去重、限流、密度控制。
- 实现轨道分配和优先级插队。
- 实现暂停、继续。

验收：

- 同一文本不会短时间重复出现。
- 低/中/高密度上限符合规则。
- 暂停后不新增运动弹幕，继续后恢复。

### 阶段 5：透明弹幕窗口

需要完成：

- 使用 PySide6 创建透明、置顶、无边框窗口。
- 弹幕从右向左平滑移动。
- 支持多轨道显示。
- 不抢占鼠标焦点，默认点击穿透或尽量减少干扰。

验收：

- 桌面上能看到弹幕滚动。
- 弹幕不会明显重叠。
- 关闭应用后窗口完全退出。

### 阶段 6：控制面板与托盘

需要完成：

- 提供暂停/继续按钮。
- 提供密度选择。
- 提供 API 配置入口。
- 提供退出应用入口。
- 可选实现系统托盘。

验收：

- 用户不用改代码就能切换密度。
- API 配置错误时有明确提示。
- 退出后没有残留进程。

### 阶段 7：主流程整合

需要完成：

- 用 `scheduler.py` 串联截屏、分析、生成、调度、渲染。
- 按成本模式控制调用频率。
- 将流程固定为 `capture -> analyze -> privacy -> generate/cache -> enqueue -> render`。
- 确保 AI 请求不阻塞 UI。
- 增加基础日志。

验收：

- 应用连续运行 30 分钟不崩溃。
- 网络失败不影响弹幕窗口运行。
- 用户暂停后停止截屏和 AI 请求。

### 阶段 8：打包与发布准备

需要完成：

- 补充 README 使用说明。
- 补充隐私说明。
- 用 PyInstaller 或同类工具打包 Windows 可执行文件。
- 明确配置文件存放路径。

验收：

- 新机器上可以按 README 启动。
- 打包版可运行、可退出、可配置。
- 不把 `.venv`、`.idea`、API Key、缓存截图打包进发布物。

## 6. MVP 执行顺序

建议按以下顺序执行，避免过早陷入复杂 AI 或 UI 细节：

1. 建立项目结构和数据模型。（已完成）
2. 定义接口协议和隐私过滤边界。（接口已完成，隐私实现待做）
3. 实现模拟弹幕生成。
4. 实现透明窗口和弹幕滚动。
5. 实现弹幕调度和密度控制。
6. 接入截屏与本地变化分析。
7. 接入 AIService 和缓存池。
8. 增加控制面板。
9. 做 30 分钟稳定性测试。

原因：先用模拟弹幕跑通视觉和调度闭环，可以尽早验证产品核心体验；AI 接入放到后面，能避免网络、Key、模型返回格式问题阻塞 UI 基础建设。

## 7. 测试计划

单元测试：

- `FrameAnalyzer`：验证静止、快速变化、重复场景的分类。
- `BarrageManager`：验证去重、轨道分配、密度限制、暂停继续。
- `AIService`：验证正常 JSON、非法 JSON、超时、空结果的处理。
- `PrivacyGuard`：验证截图、OCR、窗口标题、文件名不会进入 AI 请求。
- `BarrageCache`：验证同类场景可复用弹幕，且不会重复刷屏。

集成测试：

- 模拟模式启动完整链路。
- AI 失败后自动降级到模拟弹幕。
- 控制面板修改密度后，弹幕数量上限立即变化。

手动验收：

- 打开应用后，桌面出现透明弹幕层。
- 弹幕从右向左移动，无明显重叠。
- 暂停后弹幕停止新增。
- 继续后恢复生成。
- 无 API Key 时仍可演示。
- 不保存截图，不上传截图。

## 8. 开发规范

代码规范：

- UI 代码不直接调用大模型。
- AI 服务不依赖 PySide6。
- 截屏模块不保存图片文件。
- 所有跨模块通信使用 `models.py` 中的数据结构。
- 抽象接口放在 `interfaces.py`，具体实现放在 `core/` 或 `ui/`。
- 网络请求必须设置超时。
- API Key 必须脱敏显示。

日志规范：

- 记录启动、暂停、恢复、AI 请求成功/失败、降级原因。
- 不记录 API Key。
- 不记录截图内容。
- 第一版不记录窗口标题和 OCR 文本。

隐私规范：

- 默认不做 OCR。
- 默认不上传截图。
- 默认不保存截图。
- 用户暂停时停止截屏和 AI 请求。

## 9. 风险与处理

- 透明窗口兼容性风险：先支持 Windows 主屏，后续再扩展多屏。
- AI 输出不稳定：强制 JSON，失败时按行提取，仍失败则用模拟弹幕。
- 成本失控：默认平衡模式，低变化时降频，API 失败不重试过多。
- 弹幕烦人：密度默认中等，支持暂停和退出。
- 隐私风险：第一版不上传截图、不保存截图、不做 OCR。
- 截屏性能风险：第一版固定间隔采样，后续改为事件驱动采样；低变化时自动降频。
- 项目范围膨胀风险：语音、TTS、长期记忆、24 小时记录、自动操作都不进入 MVP。

## 10. 第一版完成定义

第一版完成时，必须满足：

- 应用可以一键启动。
- 无 API Key 也能运行模拟弹幕。
- 有 API Key 时能生成 AI 弹幕。
- 截图只用于本地变化分析。
- AI 请求经过 `PrivacyGuard`。
- 弹幕能稳定滚动且不明显重叠。
- 用户能暂停、继续、调节密度、退出。
- 至少覆盖 `FrameAnalyzer`、`BarrageManager`、`AIService`、`PrivacyGuard` 的关键测试。
