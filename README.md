# PL Analyzer Prototype

**当前版本：v1.1**

PL Analyzer Pro 是面向 MBE 与 III–V 族半导体研究的光致发光（PL）分析软件。
项目使用 Python、PySide6（Qt 6）、Matplotlib、NumPy、SciPy、openpyxl 和版本化 JSON，
预计长期维护。

当前仓库提供可运行的 v1.1 源码、受版本控制的 PyInstaller 构建链，以及本工作区内已通过
启动与可视化复核的 `dist/PL Analyzer Pro.exe`。该本机构建尚未代码签名，也不等同于干净
Windows 10/11 机器上的正式签发认证；验证证据见
[v1.1 发布验证记录](docs/release_v1.1.md)。

## v1.1 已实现功能

### 数据导入与多样品绘图

- 拖拽或文件选择批量导入 CSV、XLSX、XLSM 和旧版 XLS。
- Excel 中每个可识别 Sheet 独立导入为一个样品；坏文件或坏 Sheet 不会丢失同批成功结果。
- 根据中英文表头和数值结构自动识别波长列与强度列，无需指定列号。
- 左侧样品勾选、自动颜色、多样品同轴叠加，以及 Matplotlib 缩放、平移工具栏。
- Raw、Normalize、Offset、Linear、Log、Legend 和 Grid；显示变换不会覆盖原始数组。

`.xlsx/.xlsm` 由 `openpyxl` 读取；旧二进制 `.xls` 由隔离的 `xlrd` 适配器读取。

### 多材料 Raw Peak

- 可同时勾选多个材料窗口，并可在界面中分别修改每个窗口的最小/最大波长。
- 材料目录来自版本化的
  [`config/materials.json`](config/materials.json)，算法和 UI 不写死材料范围。
- 已配置 GaAs、Al₀.₄Ga₀.₆As、InP、晶格匹配 In₀.₅₃Ga₀.₄₇As/InP、
  InAs/GaAs QD、带应变降低层的 QD，以及需要用户定义范围的结构/合金条目。
- 同一采样峰被重叠窗口命中时，Peak Table 只显示一次，同时保留全部候选材料标签。
- 无拟合 Raw Peak 输出峰位、原始峰高、prominence、半 prominence 宽度及质量标记。
- Raw Peak Table 支持复制和 XLSX/CSV 导出。

材料标签只表示“该峰落入了哪些已选搜索窗口”，不能仅凭波长唯一识别材料、层或物理跃迁。
默认窗口、扩展窗口、计算依据、文献来源和适用限制见
[材料搜索窗口与科学边界](docs/material_windows.md)。

### v1.1 光谱拟合

- Gaussian、Lorentzian、Voigt 和 Pseudo-Voigt 线型。
- None、Constant、Linear 基线；基线与一个或多个峰联合优化。
- 可选 Savitzky–Golay 初始化辅助，窗口和多项式阶数可配置；仅接受近似等间隔波长轴。
- 峰数可手动设置，或在设定的最大峰数内自动比较。
- Auto 模式比较成功收敛的线型/峰数组合，并以最低 BIC 选择结果。
- 输出峰位、峰高、面积、FWHM、R²、调整 R²、AIC、BIC；适用时还导出
  Gaussian/Lorentzian 分量宽度和 Pseudo-Voigt 混合系数。
- 拟合曲线以虚线叠加在当前 Matplotlib 图中；Fit Table 支持复制和 XLSX/CSV 导出。

BIC 是自动选择准则；面积、FWHM、R² 和调整 R² 是结果与质量诊断，不是材料判定或自动选择
准则。不同搜索窗口、预处理或基线设定下的 BIC 不应直接作物理优劣比较。

### Layer Editor 与工程恢复

- Layer Editor 支持不限层数的新增、编辑、删除和上下移动。
- 每层保存 Material、Thickness (nm)、Composition、Doping Type 和
  Doping Concentration (cm⁻³)；物理量经过有限值和范围校验。
- `.plproj` 使用版本化 UTF-8 JSON，内嵌原始波长/强度数组，因此重新打开工程不依赖原始
  Excel/CSV 路径。
- 工程恢复样品、来源信息、颜色/显隐、绘图状态、材料选择与编辑窗口、Raw Peak 结果、
  拟合设置与完整拟合结果、外延层、主题和 Raw Peak 参数。
- 保存使用同目录临时文件、flush/fsync 和原子替换；加载失败不会替换当前工程。
- 打开较新且不支持的 schema 会明确拒绝；持久化层保留逐版本迁移入口。

### 桌面体验、导出与错误恢复

- Light/Dark 主题，Qt 与 Matplotlib 同步更新，并持久化用户选择。
- Preferences 可配置 Raw Peak prominence、噪声阈值、峰间距、峰数和数据间隙判定。
- 绘图导出 PNG、SVG、PDF；Raw Peak 与拟合表分别导出 XLSX、CSV。
- 底部可停靠日志、滚动日志文件、错误弹窗和统一异常边界；单个导入或分析失败后程序继续运行。
- File、Analysis、View、Tools、Help 菜单及常用快捷键均连接到实际功能，没有空菜单项。

## 安装与运行

建议使用 Python 3.12：

```powershell
cd "PL Analyzer Pro"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
```

运行验证：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -c "from main import main"
```

生成一文件、无控制台窗口的 Windows EXE：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```

脚本会依次执行全部测试、Ruff、受控清理和 PyInstaller，并输出
`dist\PL Analyzer Pro.exe` 的大小与 SHA-256。

## 使用方式

1. 拖入一个或多个数据文件，在左侧确认需要显示和分析的样品。
2. 在 Raw Peak 页同时勾选相关材料，按样品温度、成分和结构修订搜索窗口。
3. 运行 Raw Peak，先检查原始峰、质量标记和候选材料标签。
4. 在 Model Fit 页选择线型/Auto、基线、峰数和可选 Savitzky–Golay，再运行拟合。
5. 检查残差意义、BIC、R²、峰形与外延结构，而不是只接受自动模型名称。
6. 在 Layer Editor 记录外延结构，保存 `.plproj`，再导出图和结果表。

## 科学语义与当前边界

Raw Peak 始终读取原始线性强度。其 `FWHM` 是 SciPy prominence 基础上的半 prominence
宽度，并将 fractional-sample 交点映射到真实波长轴；它不是基线校正后的拟合 FWHM。边界
截断峰仍报告峰位和峰高，但 FWHM 留空并带质量标记。

模型拟合也从所选材料窗口内的原始线性强度开始。启用 Savitzky–Golay 时只创建用于峰初值
估计的处理副本；最终优化、残差、R²、AIC 与 BIC 始终以原始观测计算，避免把平滑引入的
相关残差误当作独立数据。联合拟合的基线、拟合曲线和残差均单独保存。拟合收敛及较高 R²
不证明模型具有唯一物理机制，也不证明材料归属。低于局部采样分辨率或彼此不可分辨的峰会
以稳定错误拒绝，不输出伪精确 FWHM/Area。

v1.1 尚不包含：

- v1.2 的 AI 物理机制分析或对话 Assistant；
- v2.0 的百文件批处理、统计和自动报告；
- 温度/激发功率序列、能量轴、仪器响应校正、反射率/DBR stopband 等高级光谱工作流；
- Word 报告导出；
- 代码签名、安装器，以及干净 Windows 10/11 机器上的跨机签发认证。

## 项目文档

- [架构与扩展边界](docs/architecture.md)
- [材料搜索窗口与科学边界](docs/material_windows.md)
- [开发与验证](docs/development.md)
- [v1.1 发布验证记录](docs/release_v1.1.md)
