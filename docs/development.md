# 开发与验证

## 支持环境

- Windows 10/11
- Python 3.12
- Qt 6 / PySide6

开发与验证应使用项目自己的 `.venv`，避免系统 Python 的依赖状态污染结果。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 每个增量的完成门槛

1. 先定义领域模型、单位化字段和错误协议，UI 只编排可测试服务。
2. 新功能包含正常路径、边界输入、失败恢复和持久化往返测试。
3. `pytest`、`ruff check` 与 `ruff format --check` 通过。
4. Qt offscreen 构造测试通过。
5. 在 Windows 上人工启动 `main.py`，检查导入、拖拽、分析、绘图、工程恢复、导出和错误后
   继续操作。
6. 接口、schema 或科学定义变化时，同步更新 README 和 `docs/`。
7. 科学默认值必须附可追溯来源，并明确测量条件和推断部分。

## 常用命令

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .

$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -c "from main import main"

.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main_zh.py
```

`python -c "from main import main"` 只检查导入，不替代 Qt 事件循环或人工桌面验收。

## 界面本地化

英文是源代码基准语言，简体中文由 Qt Linguist 目录
`resources/i18n/pl_analyzer_zh_CN.ts` 提供。UI 通过 `self.tr()` 或
`QCoreApplication.translate()` 获取显示文本；领域枚举值、材料 ID、错误码、JSON key、
`.plproj` schema 和导出数据契约不得翻译。

修改可见文本后应重新提取并编译目录：

```powershell
$sources = @("main.py", "main_zh.py")
$sources += Get-ChildItem ui,plotting -Filter *.py -File -Recurse |
  Sort-Object FullName |
  ForEach-Object FullName
.\.venv\Scripts\pyside6-lupdate.exe @sources `
  -ts resources\i18n\pl_analyzer_zh_CN.ts
.\.venv\Scripts\pyside6-lrelease.exe `
  resources\i18n\pl_analyzer_zh_CN.ts `
  -qm resources\i18n\pl_analyzer_zh_CN.qm
```

提交前必须确认 TS 中没有 `unfinished` 或空翻译，源文和译文的命名占位符集合一致，并运行
`tests/test_localization.py`。`qtbase_zh_CN.qm` 用于 Qt 标准按钮；Matplotlib
NavigationToolbar 的 Python 定义文本由 `SpectrumPlotWidget` 显式翻译。新增语言应增加独立
目录和构建目标，不得复制算法、材料配置或整套 UI 源码。

## v1.1 验证矩阵

| 范围 | 自动验证重点 |
| --- | --- |
| Column detector | 中英文表头、无表头数值回退、排序、重复波长合并 |
| Import service | GB18030 CSV、多 Sheet XLSX、XLS 适配器、局部失败 |
| Raw Peak | 精确峰、非等间隔 FWHM、平台峰、缺失值、边界峰、物理 nm 间距 |
| Material configuration | schema v2、默认/扩展窗口、空窗口结构条目 |
| Workspace/export | 唯一样品名/颜色、材料标签聚合、XLSX 结果往返 |
| Fitting | 四种峰形、自动 BIC、双峰、联合基线、非破坏 Savitzky–Golay、稳定错误码 |
| Project persistence | 完整往返、原子保存失败保护、损坏文件、较新 schema、迁移步长 |
| UI smoke | Qt offscreen 主窗口构造和核心依赖装配 |

人工验收还应覆盖：

- 同时选择 GaAs 和 Al₀.₄Ga₀.₆As 后，两组窗口均执行；
- 重叠窗口命中同一峰时表中只有一个峰，但候选材料标签完整；
- Raw/Normalize、Offset、Linear/Log 切换后 Raw Peak 与拟合输入不变；
- 四个固定线型和 Auto 均能运行，失败窗口只进入 Log 而不终止其他样品；
- 拟合虚线、Legend/Grid 和 Light/Dark 主题同步更新；
- Layer Editor 的增删改、顺序、厚度和掺杂浓度校验；
- 保存后关闭并重新打开 `.plproj`，核对数组、样品状态、窗口、层、Raw Peak、拟合、主题和
  Preferences；
- PNG/SVG/PDF、Raw Peak XLSX/CSV、Fit XLSX/CSV 均可由目标应用重新打开。

## 科学算法变更规则

### Raw Peak

Raw Peak 的无拟合定义是稳定契约。不得为了复用 v1.1 拟合代码而在 `RawPeakAnalyzer` 中隐式
加入平滑或基线。若宽度定义改变，必须：

1. 增加算法版本；
2. 保留旧工程结果的可读性；
3. 增加不等间隔、边界和缺口回归测试；
4. 同步更新 UI 提示、导出列说明和文档。

### Model Fit

新增峰形时应实现统一模型评估、初始值、参数边界、物理指标提取和候选失败诊断，而不是在 UI
中复制一条拟合路径。Auto 候选必须在同一原始观测和基线假设上计算残差与信息准则；BIC 仅
在该候选集合内有效。

Savitzky–Golay 参数必须满足窗口为奇数、窗口不超过数据点数、多项式阶数小于窗口。任何预处理
都只能产生新数组，不能回写 `SpectrumSeries.intensity_au`。当前实现还要求波长轴近似等间隔，
并只用平滑副本估计初始峰位/基线；最终优化、R²、AIC 和 BIC 必须回到原始线性观测。

合成峰测试用于验证数值实现，不等于真实 PL 样品上的模型有效性。发布新的自动默认前，应补充
代表性实测光谱、残差检查、参数稳定性和跨操作者复核。

## 材料数据库维护

编辑 `config/materials.json` 时：

1. 使用稳定、不可复用的 `id`；修改显示名不应破坏工程恢复。
2. 所有波长字段使用 nm，能量使用 eV，温度使用 K。
3. 默认窗口必须注明参考温度、成分、结构类型和依据。
4. 文献应优先使用原始论文 DOI、出版社页面或权威技术数据库 URL。
5. 合金成分、应变、量子限域或器件设计未知时，窗口应为空或明确标为经验范围。
6. 不得把 DBR stopband、腔模或 QD Laser 设计波长描述成通用材料 PL 峰。
7. 增加/修改条目后同步
   [材料搜索窗口与科学边界](material_windows.md)，并运行配置测试。

界面中修改窗口只属于当前工程快照，不会写回全局数据库。若未来增加数据库编辑器，应采用独立
验证、显式保存和 schema 迁移，而不是直接修改加载中的对象。

## `.plproj` schema 变更

- 禁止 pickle、Python 对象标签、NaN 和 Infinity。
- 新正式字段需要递增 `PROJECT_SCHEMA_VERSION`，并为每个旧版本注册一步迁移。
- 迁移函数必须复制输入、只前进一个版本且可独立测试。
- schema v2 内置 v1 → v2 材料 ID 迁移；测试必须同时覆盖工程窗口、Raw Peak、Fit 结果，
  并验证用户自定义选中状态、窗口范围和未知自定义 ID 均不丢失。
- 读取较新版本继续拒绝，除非实现了明确的只读兼容模式。
- 加载过程不得在完全验证前改变当前工作区。
- 保存继续使用同目录临时文件、flush/fsync 和原子替换。
- 大数据压缩或外部数据块属于未来格式设计，不能破坏当前“工程可独立恢复”的保证。

## 文档轻量检查

没有引入额外 Markdown 工具依赖。至少检查所有 Markdown 可按 UTF-8 读取、相对链接目标存在，
HTTP(S) 链接具有合法绝对 URI；如开发机安装了 markdownlint，可再运行其默认规则并人工检查
表格和公式渲染。

## PyInstaller 发布门槛

`build_release.ps1 -Language all` 与 `PLAnalyzerPro.spec` 提供可重复的英文/简体中文
一文件 Windows 构建。两个目标使用隔离 workpath，并在生成后分别执行定时启动 smoke test；
详情见 [v1.1.1 双语言发布说明](release_v1.1.1.md)。正式对外签发仍需：

1. 最终产品图标、代码签名和可验证的发布证书链；
2. 将 `config/materials.json`、`config/default_settings.json` 等运行资源正确打入包；
3. 干净 Windows 10/11 环境启动；
4. CSV/XLSX/XLS 导入、Raw Peak、四模型拟合、`.plproj` 往返和全部导出格式验收；
5. 无开发环境时的错误日志、崩溃恢复和杀毒软件误报检查；
6. 记录构建工具版本、产物哈希和签名状态。

开发机 EXE 可作为 v1.1.1 可运行交付物，但不得把它描述为已签名或已完成跨机认证的正式
安装包。
