# PL Analyzer Pro

**当前版本：v1.1.4**

PL Analyzer Pro 是面向 MBE 与 III–V 族半导体研究的光致发光分析软件。
项目基于 Python、PySide6、Matplotlib、NumPy、SciPy 和 openpyxl，长期维护。
英文与简体中文使用同一套科学算法、材料数据库和 `.plproj` 工程格式。

## 功能

### 数据导入

- 支持 DAT、OPJ、OPJU、CSV、XLSX、XLSM、XLS。
- 支持批量导入、拖拽导入和多 Sheet 拆分。
- DAT 强度计算为 `Signal - Baseline`，保留激光、功率、温度等元数据。
- OPJ/OPJU 使用内置只读解析器，无需 Origin、COM 或 GPL liborigin。
- 坏文件、坏 Sheet 不会阻断同批成功数据。

### 分析与绘图

- 多样品同轴显示，支持 Raw、Normalize、Offset、Linear、Log。
- Raw Peak 输出峰位、峰高、半高宽、prominence 和质量标记。
- 支持多材料搜索窗口和重叠窗口去重。
- 支持 Gaussian、Lorentzian、Voigt、Pseudo-Voigt 和自动 BIC 模型选择。
- 拟合支持常量、线性、无基线和 Savitzky-Golay 初始化。

### 导出与工程

- 导出 PNG、SVG、PDF。
- Raw Peak 与拟合表可导出 XLSX、CSV。
- 单光谱可导出参考样式 PNG，并附带 JSON 指标、CSV 数据。
- `.plproj` 使用版本化 JSON，内嵌原始数组，可独立恢复。
- Layer Editor 记录层结构、厚度、成分和掺杂。

## 安装与运行

从 [Releases](https://github.com/SpikeHS/PL-Analyzer/releases) 下载最新版本即可使用。

源码运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main_zh.py
```

## 使用流程

1. 拖入数据文件，确认样品显隐。
2. 选择材料窗口，修订波长范围。
3. 运行 Raw Peak，检查峰位和质量标记。
4. 选择拟合模型、基线、峰数，运行 Model Fit。
5. 记录外延结构，保存 `.plproj`，导出图和结果表。

## 发布

正式构建命令：

```powershell
.\build_release.ps1 -Language all
```

产物包含英文 EXE、中文 EXE、`THIRD-PARTY-NOTICES.txt` 和 `SHA256SUMS.txt`。
脚本运行完整测试、Ruff 检查、双语言构建、启动测试和 SHA-256 校验。

## 文档

- [架构与扩展边界](docs/architecture.md)
- [开发与验证](docs/development.md)
- [Origin 导入](docs/origin_import.md)
- [材料搜索窗口](docs/material_windows.md)
- [v1.1.4 发布说明](docs/release_v1.1.4.md)

## 许可证

Origin 解析子集基于 Apache-2.0，固定于
[quantized-lab](https://github.com/pquarterman17/quantized/tree/v0.11.0) v0.11.0。
完整声明见 `THIRD-PARTY-NOTICES.txt`。
