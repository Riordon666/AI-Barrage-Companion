# 步骤 06：屏幕上下文感知与 OCR 文字识别

## 1. 本步骤目标

本步骤解决 MVP 之后最大的体验缺陷：**AI 不知道用户在干什么**。

改造前，AI 弹幕生成只接收抽象信号：

```text
场景: activity=active, pace=fast, event=highlight, confidence=0.85
```

模型只能猜测用户可能在打游戏、写代码还是看视频，无法生成贴合实际的弹幕。

改造后，AI 接收真正的屏幕信息：

```text
场景: activity=active, pace=fast, event=normal, confidence=0.65
屏幕内容: 屏幕文字: def process_data(data): | import numpy as np |
          正在 VS Code 中编写代码
```

模型知道用户正在 VS Code 里写 Python 代码，弹幕自然贴合——"缩进不对""numpy 版本太老了吧""这变量名犯规"。

---

## 2. 实现方案：两条互补路线

### 路线 A：窗口标题 / 应用检测（`screen_context.py`）

**原理**：通过 Windows API 获取活动窗口标题 → 50+ 签名匹配 → 输出人类可读描述。

**技术**：纯 `ctypes` 调用 `user32.dll`（无需额外依赖），可选 `psutil` 获取进程名。

**覆盖**：

| 类别 | 识别应用 |
|------|---------|
| 游戏 | LOL、VALORANT、CS、原神、Minecraft、Elden Ring … |
| 编程 | VS Code、PyCharm、IntelliJ、Cursor、Vim、Notepad++ … |
| 浏览器 | Chrome、Firefox、Edge |
| 媒体 | Premiere、DaVinci、Photoshop、Blender、Figma … |
| 聊天 | 微信、QQ、Discord、Slack、Telegram |
| 办公 | Word、Excel、Obsidian、Notion |
| 终端 | PowerShell、WSL、Terminal |

**开关**：控制面板 `enable_window_title`

### 路线 B：OCR 屏幕文字识别（`ocr_engine.py`）

**原理**：截图 → Tesseract OCR (chi_sim+eng) → 清洗 → 注入 AI prompt。

**技术栈**：`pytesseract` + Tesseract-OCR（用户需单独安装 Tesseract）。

**关键设计**：

```
截屏帧 → PIL Image → pytesseract.image_to_string()
    → _clean_ocr_text()       # 丢弃短行噪声、压缩空白、截断到 300 字符
    → OcrCache.should_send()  # 哈希去重，相同内容每 10 帧重发一次
    → scene.screen_context = "屏幕文字: ... | 正在 VS Code 中编写代码"
```

**开关**：控制面板 `enable_ocr`

**降级**：Tesseract 未安装时静默返回空字符串，管线正常运转。

---

## 3. 新增或更新的文件

### 新增

```
app/core/screen_context.py       # 屏幕上下文提取（窗口标题 / 应用分类）
app/core/ocr_engine.py           # OCR 引擎（Tesseract 封装 + 去重缓存）
app/core/utils.py                # 共享工具（raw_image_bytes、priority_for_event、类型窄化）
tests/test_screen_context.py     # 屏幕上下文测试（13 个）
tests/test_ocr_engine.py         # OCR 引擎测试（13 个）
tests/test_integration.py        # RuntimeController 集成测试（20 个）
abc-settings.example.json        # 安全配置模板（不含真实 Key）
planning/step-06-screen-context-and-ocr.md
```

### 更新

```
app/models.py                    # SceneSummary 新增 screen_context 字段；ApiConfig 新增安全 __repr__
app/core/ai_service.py           # _user_prompt 增加「屏幕内容」段落；_system_prompt 增强视觉模式指令
app/core/barrage_cache.py        # 缓存 key 从 3 元组 → 4 元组，按屏幕上下文区分
app/core/privacy_guard.py        # 透传 screen_context；enable_ocr 控制 OCR 文本发送
app/core/frame_analyzer.py       # _raw_bytes 提取到 utils.py；消除 type: ignore
app/core/mock_barrage_service.py # _priority_for_event 提取到 utils.py
app/core/barrage_manager.py      # _eligible_tracks 修复轨道重叠 bug；_ActiveEntry 新增 started_at
app/core/capture_scheduler.py    # 消除 type: ignore
app/core/__init__.py             # 新增 screen_context / ocr_engine / utils 导出
app/ui/application.py            # RuntimeController 依赖注入；_capture_and_generate 集成 OCR + 屏幕上下文
app/ui/control_panel.py          # 消除 type: ignore
app/config/settings_store.py     # 原子写入；消除 type: ignore；细化异常捕获
requirements.txt                 # 新增 pytesseract>=0.3
README.md                        # 新增功能说明、安装指南、更新数据流图
```

---

## 4. 数据流变更

```
改造前：
  截图 → 帧差分析 → SceneSummary(activity/pace/event) → AI

改造后：
  截图 ─┬─ 屏幕上下文提取 → "正在 VS Code 中编写代码"
        ├─ OCR 文字识别    → "def main(): | import numpy"
        └─ 帧差分析        → activity/pace/event
           ↓
  SceneSummary(activity, pace, event, screen_context)
           ↓
  隐私过滤（screen_context 随 enable_ocr/enable_window_title 控制）
           ↓
  弹幕缓存（key 含 screen_context，不同应用不共享缓存）
           ↓
  AI prompt: "屏幕内容: 屏幕文字: def main(): | 正在 VS Code 中编写代码"
           ↓
  AI → "这函数名有意思""import 顺序不对" ✨
```

---

## 5. Prompt 变更

### 改造前（抽象信号）

```
场景: activity=active, pace=fast, event=highlight, confidence=0.85
人格可选: troll, support, sarcastic, follower, fun
数量: 3
格式: [{"persona":"fun","text":"有点意思"}]
```

### 改造后（真实上下文）

```
场景信号: activity=active, pace=normal, event=normal, confidence=0.70
屏幕内容: 屏幕文字: def process_data(data): | import numpy as np |
          正在 VS Code 中编写代码
请根据上述屏幕内容生成弹幕，弹幕要和用户正在做的事相关。
人格可选: troll, support, sarcastic, follower, fun
数量: 3
格式: [{"persona":"fun","text":"有点意思"}]
```

---

## 6. 隐私控制

| 设置 | 默认值 | 行为 |
|------|--------|------|
| `privacy_mode = "strict"` | ✅ | 禁止截图、OCR 文本、窗口标题进入 AI 请求 |
| `enable_window_title` | ❌ | 用户手动开启后，窗口标题 / 应用类型才加入 prompt |
| `enable_ocr` | ❌ | 用户手动开启后，OCR 提取的文字才加入 prompt |
| `enable_vision` | ❌ | 用户手动开启后，截图才作为 JPEG 发送给 AI |

**设计原则**：所有涉及屏幕内容上传的功能均默认关闭，用户必须主动勾选才能启用。

---

## 7. 新增测试

| 测试文件 | 数量 | 覆盖范围 |
|----------|------|----------|
| `test_screen_context.py` | 13 | 应用分类（VS Code/Chrome/LOL）、Prompt 包含/不包含上下文、空标题回退 |
| `test_ocr_engine.py` | 13 | 文本清洗（去噪/截断/空白压缩）、哈希去重、缓存策略、Tesseract 缺失降级 |
| `test_integration.py` | 20 | 截屏→分析→缓存→AI→渲染全链路、AI 失败降级、暂停恢复、密度切换、缓冲上限 |

全部测试：**77 个通过，0 失败**。

---

## 8. 安装说明

```powershell
# Python 依赖
pip install -r requirements.txt

# Tesseract-OCR（可选——OCR 功能需要）
winget install UB-Mannheim.TesseractOCR
# 或手动下载安装 → 勾选 Chinese (Simplified) 语言包
```

---

## 9. 当前完成状态

### 已完成

- 屏幕上下文感知（窗口标题 / 应用类型）
- OCR 屏幕文字识别（Tesseract 封装 + 去重缓存）
- AI Prompt 增强（屏幕内容注入）
- 弹幕缓存按屏幕上下文区分
- 隐私控制（所有屏幕内容功能默认关闭）
- 完整测试覆盖（77 个测试）
- 代码质量修复（消除 type: ignore、提取重复代码、细化异常、修复轨道重叠 bug）
- API Key 安全加固（__repr__ 脱敏、写入原子化）

### 未完成

- 多显示器支持
- 游戏专项适配（DirectX 截图 / OBS 虚拟摄像头）
- 原生 Anthropic / Gemini 协议适配
- 打包发布（PyInstaller）
