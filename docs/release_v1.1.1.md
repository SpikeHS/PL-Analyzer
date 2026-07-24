# PL Analyzer Pro v1.1.1 双语言发布说明

## English summary

PL Analyzer Pro v1.1.1 is a bilingual Windows maintenance release. It fixes
PySide6 `Qt.CheckState` compatibility for both material and sample checkboxes,
adds a complete Simplified Chinese desktop translation, and keeps all analysis,
material-database, and `.plproj` contracts unchanged.

Choose one standalone executable:

- `PL-Analyzer-Pro-v1.1.1-Windows-x64-en-US.exe` — original English edition;
- `PL-Analyzer-Pro-v1.1.1-Windows-x64-zh-CN.exe` — Simplified Chinese edition.

Both executables bundle Python and all required runtime dependencies. No Python
installation is required on the target Windows computer.

## 发布身份

- 产品版本：1.1.1
- 发布类型：v1.1 维护版
- 发布日期：2026-07-24
- Windows 架构：x64
- 英文入口：`main.py`
- 中文入口：`main_zh.py`
- 构建规格：`PLAnalyzerPro.spec`
- 构建脚本：`build_release.ps1`
- 代码签名：未签名

本版本修复了 PySide6 新版 `Qt.CheckState` 无法转换为 `int` 时，材料窗口及 Samples
勾选操作触发未处理异常的问题。修复只改变 Qt 模型对复选框状态的兼容处理，不改变
Raw Peak、拟合算法、材料数据库或 `.plproj` schema。

## Windows 独立产物

一次完整构建生成：

- `dist/PL-Analyzer-Pro-v1.1.1-Windows-x64-en-US.exe`
- `dist/PL-Analyzer-Pro-v1.1.1-Windows-x64-zh-CN.exe`
- `dist/SHA256SUMS.txt`

本次正式产物：

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| 英文原版 EXE | 109,544,163 | `8CEBE2BFB3025B8061BFDD629EEAE2E1E8E25C9D3939CF5D31D4177A805238E1` |
| 简体中文版 EXE | 109,543,656 | `D4F67DD04A16EA100D605E6E7D5B702963E9DEA90D8261E6B88A2A25B7A1F535` |

两个 EXE 均为 PyInstaller one-file/windowed 程序，包含 Python、PySide6、Matplotlib、
NumPy、SciPy、openpyxl 和 xlrd，目标机器无需安装 Python。两个语言版本使用同一领域模型、
科学算法和工程格式，只选择不同桌面入口与 Windows 版本资源。

## 可重复构建

在项目根目录使用项目 `.venv`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\build_release.ps1 -Language all
```

也可只构建一个语言：

```powershell
.\build_release.ps1 -Language en-US
.\build_release.ps1 -Language zh-CN
```

`all` 模式先执行完整 pytest、Ruff lint、Ruff format check 与 PyInstaller 可用性检查，
然后分别使用 `build/en-US` 和 `build/zh-CN` 工作目录构建。脚本验证 dist 中只能出现本次
选择的 EXE，对每个 EXE 执行带定时退出的启动 smoke test，最后生成按文件名稳定排序的
`SHA256SUMS.txt`。

`SHA256SUMS.txt` 是最终构建文件的权威校验清单。任何重新构建、签名或二进制修改都会改变
哈希，发布页面必须上传同一次构建产生的两个 EXE 与该清单，不能沿用 v1.1.0 的哈希。

## 发布验收

自动门槛：

1. 完整 pytest 通过；
2. `ruff check .` 通过；
3. `ruff format --check .` 通过；
4. 两个隔离 workpath 的 PyInstaller 构建通过；
5. 两个 EXE 均在无控制台模式下启动，并由
   `PL_ANALYZER_PRO_SMOKE_EXIT_MS` 定时正常退出；
6. Windows FileVersion、ProductVersion 与 Python `__version__` 均为 `1.1.1`；
7. 英文和中文 VersionInfo 的 OriginalFilename 分别匹配真实产物名称；
8. dist 中不存在未声明的 EXE，SHA-256 清单覆盖全部本次产物。

本次自动验收结果：完整测试套件 `100 passed`；Ruff lint、Ruff format check、双 EXE
构建与启动 smoke test 全部通过。

本次人工桌面验收结果：

1. 英文原版与简体中文版均可启动，版本号均为 1.1.1；
2. 两个版本的材料复选框均可取消与恢复，未出现 `CheckState` 错误；
3. 简体中文版实际导入 `tests/fixtures/packaged_smoke.csv`，正确识别 GaAs 与
   Al₀.₄Ga₀.₆As 两个材料窗口并生成峰表；
4. 简体中文版的 Samples 复选框可隐藏并恢复光谱曲线，日志无未处理异常；
5. 中文菜单、表头、对话框、Matplotlib 工具栏、坐标轴和日志均正确显示。

后续跨机发布验收仍应覆盖：

1. 在干净 Windows 10/11 机器运行两个版本；
2. 使用实验室代表性 CSV/XLSX/XLS 数据复核导入；
3. 复核 Raw Peak、Model Fit、工程保存恢复与全部导出格式。

## 已知签发边界

当前产物没有代码签名或安装器。Windows SmartScreen 可能显示“未知发布者”，使用者应从
GitHub Release 下载并先核对 `SHA256SUMS.txt`。开发机 smoke test 不等同于干净 Windows
10/11 跨机认证；正式科研使用前仍应使用实验室代表性 CSV/XLSX/XLS 与 PL 光谱复核导入、
Raw Peak、拟合参数、工程恢复和全部导出格式。
