# 步骤 01：工程骨架与接口说明

## 1. 本步骤目标

本步骤的目标是把项目从 PyCharm 示例脚本状态，整理成可以继续开发的正式 Python 桌面应用结构。

这一步不实现真实截屏、AI 调用、弹幕调度或 PySide6 透明窗口，只完成后续开发需要依赖的工程骨架、数据模型和接口边界。

## 2. 完成的内容

### 2.1 创建项目结构

新增了以下目录：

```text
app/
  core/
  ui/
  config/

tests/
```

作用：

- `app/`：应用主包。
- `app/core/`：后续放截屏、分析、AI、弹幕调度等业务逻辑。
- `app/ui/`：后续放 PySide6 透明窗口、控制面板、托盘等界面代码。
- `app/config/`：后续放配置读取、保存和默认配置。
- `tests/`：后续放单元测试和集成测试。

### 2.2 创建最小入口

整理：

```text
main.py
```

当前入口只做最小启动验证，运行：

```powershell
python main.py
```

预期输出：

```text
AI Barrage Companion scaffold ready
density=medium, cost_mode=balanced
```

这说明 Python 包结构、入口模块和基础配置模型可以正常导入。

说明：

项目入口统一只保留根目录 `main.py`。原先临时创建的 `app/main.py` 已删除，避免后续出现两个 main 入口导致启动方式混乱。

### 2.3 定义核心数据模型

新增：

```text
app/models.py
```

其中定义了后续模块共享的数据结构：

- `ApiConfig`：AI API 配置。
- `AppSettings`：应用配置。
- `CapturedFrame`：截屏结果。
- `FrameStats`：画面变化统计。
- `SceneSummary`：场景摘要。
- `CapturePolicy`：截屏策略。
- `PrivacyDecision`：隐私过滤结果。
- `BarrageItem`：单条弹幕。
- `GenerationRequest`：弹幕生成请求。
- `GenerationResult`：弹幕生成结果。
- `TrackAssignment`：弹幕轨道分配结果。

原因：

这些模型是项目后续模块之间的共同语言。先定义它们，可以避免 UI、AI、截屏、调度逻辑互相传递散乱的字典。

### 2.4 定义接口协议

新增：

```text
app/interfaces.py
```

其中定义了核心模块协议：

- `ScreenCapture`
- `FrameAnalyzer`
- `CaptureScheduler`
- `PrivacyGuard`
- `BarrageGenerator`
- `BarrageCache`
- `BarrageManager`
- `OverlayRenderer`

原因：

ABC 后续会同时涉及截屏、AI、缓存、调度和 UI。如果不先规范接口，后续很容易出现 UI 直接调用 AI、AI 直接依赖 PySide6、截屏模块保存隐私图片等问题。

### 2.5 创建常量文件

新增：

```text
app/constants.py
```

当前包含：

- 应用名称
- 默认截屏间隔
- 默认弹幕持续时间
- 默认 API 超时时间

原因：

常用默认值集中管理，避免后续散落在多个模块中。

### 2.6 创建依赖文件

新增：

```text
requirements.txt
```

当前内容：

```text
PySide6>=6.7
mss>=9.0
httpx>=0.27
pytest>=8.0
```

说明：

- `PySide6`：后续用于桌面 UI 和透明弹幕窗口。
- `mss`：后续用于屏幕截图。
- `httpx`：后续用于调用 OpenAI 兼容接口。
- `pytest`：后续用于测试。

当前这些依赖对工程骨架足够，但完整 MVP 做帧差分析时，建议再加入：

```text
numpy>=1.26
Pillow>=10.0
```

打包阶段再考虑加入：

```text
pyinstaller>=6.0
```

### 2.7 更新忽略规则

更新：

```text
.gitignore
```

新增忽略：

```text
__pycache__/
*.py[cod]
```

原因：

运行和编译 Python 代码会生成缓存文件，这些不是项目源码，不应该提交。

## 3. 验证结果

已执行：

```powershell
python main.py
```

结果正常。

已执行：

```powershell
python -m compileall app tests
```

结果正常。

这说明当前项目骨架没有基础语法错误，模块导入关系也能正常工作。

## 4. 遇到的问题与原因

### 4.1 `dataclass(slots=True)` 不兼容当前 Python

最初数据模型使用了：

```python
@dataclass(slots=True)
```

但当前环境是 Python 3.9，`slots=True` 是 Python 3.10+ 才支持的参数。

处理方式：

- 移除 `slots=True`
- 保留普通 `@dataclass`

原因：

优先保证项目能在当前本地环境运行。

### 4.2 pip 安装命令写法错误

错误命令：

```powershell
pip install -t requirements.txt
```

错误原因：

`-t` 表示 `--target`，意思是把包安装到指定目录。这里 `requirements.txt` 是文件，不是目录，所以 pip 报错：

```text
Target path exists but is not a directory
```

正确命令：

```powershell
pip install -r requirements.txt
```

如果要先升级 pip：

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 5. 当前完成状态

已完成：

- 工程目录结构
- 最小运行入口
- 核心数据模型
- 核心接口协议
- 基础依赖文件
- Python 缓存忽略规则
- 基础运行验证

未完成：

- 截屏实现
- 画面变化分析
- 隐私过滤实现
- 模拟弹幕生成
- AI 弹幕生成
- 弹幕调度
- PySide6 透明窗口
- 控制面板

## 6. 下一步建议

下一步建议实现“模拟弹幕生成 + 隐私过滤基础实现”。

原因：

模拟弹幕不依赖 API Key 和网络，可以先验证弹幕数据生成链路；隐私过滤是 AI 请求前的安全边界，应尽早实现，避免后续功能绕过它。
