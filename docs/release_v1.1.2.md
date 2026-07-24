# PL Analyzer Pro v1.1.2 Origin 原生导入发布说明

## English summary

PL Analyzer Pro v1.1.2 adds native, read-only Origin OPJ/OPJU worksheet import
to both standalone Windows editions. The application does not require Python,
Origin, or Origin/COM on the target computer. It vendors only the
workbook/worksheet reader subset of the Apache-2.0 licensed `quantized-lab`
v0.11.0 project; it does not use or contain GPL `liborigin` code.

Choose one executable:

- `PL-Analyzer-Pro-v1.1.2-Windows-x64-en-US.exe` — original English edition;
- `PL-Analyzer-Pro-v1.1.2-Windows-x64-zh-CN.exe` — Simplified Chinese edition.

Download `THIRD-PARTY-NOTICES.txt` with either executable and verify both files
against `SHA256SUMS.txt`. The executables are unsigned, so Windows may identify
the publisher as unknown.

## 发布身份

- 产品版本：1.1.2
- 发布类型：v1.1 功能与兼容性更新
- 发布日期：2026-07-24
- Windows 架构：x64
- 英文入口：`main.py`
- 中文入口：`main_zh.py`
- 构建规格：`PLAnalyzerPro.spec`
- 构建脚本：`build_release.ps1`
- 代码签名：未签名

## 本版本新增

两个桌面版本均可通过拖拽或 File → Open 原生读取 `.opj` 和 `.opju`。导入适配器：

- 按扩展名验证旧 OPJ 的 `CPYA` 与新 OPJU 的 `CPYUA` 文件签名；
- 枚举项目中的 workbook/worksheet，并将每个可识别 worksheet 交给统一列检测器；
- 保留列长名称、短名称、单位和可恢复的 X/Y designation；
- 对 `Wavelength + Signal + Baseline` 选择 Signal，不把 Baseline 拆成独立样品；
- 允许同批混合导入 OPJ、OPJU、CSV、XLSX 和 XLS；
- 将可检测的文件解析失败、坏 worksheet 或无法可靠恢复的 X 轴记录为可恢复错误，不中止
  同批成功项；
- 不修改源 Origin 工程，也不在源文件旁创建中间文件。

这是只读 worksheet 数据导入，不是 Origin 项目界面或项目对象的完整复刻。

## 开源实现与第三方合规

原生导入固定使用以下经过审计的 open-source reader：

- 上游项目：[`pquarterman17/quantized`](https://github.com/pquarterman17/quantized/tree/v0.11.0)
- 发布包：`quantized-lab`
- 上游版本：`v0.11.0`
- 固定提交：`c34980b82947af3f82f7a9a4ff5692610ba5398f`
- 许可证：Apache-2.0

仓库只 vendored workbook/worksheet reader subset，没有引入上游 Web 应用或服务，也没有使用、
链接或包含 GPL `liborigin` 代码。为纳入私有 Python 包所做的修改限于：将绝对包导入改为
相对导入、增加 OPJ/OPJU 调度 facade，以及增加不改变算法的 Ruff 兼容标注。解析算法和数据
契约保持不变。

受版本控制的完整 `LICENSE`、`NOTICE`、上游固定版本、提交以及本地修改记录位于：

- `core/importing/_origin_parser/LICENSE`
- `core/importing/_origin_parser/NOTICE`
- `core/importing/_origin_parser/UPSTREAM.md`

PyInstaller 将这些文件嵌入冻结应用的 `licenses/quantized-origin`。此外，
`build_release.ps1` 会逐字收集上述内容，生成可直接公开阅读的
`dist/THIRD-PARTY-NOTICES.txt`。该文件与两个 EXE 一起进入 `SHA256SUMS.txt`，Release
必须上传它，不能只把许可证藏在 one-file EXE 内。

## 支持边界

### OPJU

真实仪器金标准目前仅覆盖 OPJU。用于本地验证的 `PL DATA.opju` 含 5 个 worksheet，每个
worksheet 有 1,215 个 `Wavelength`、`Signal`、`Baseline` 数据点。恢复的五组波长与 Signal
和对应五份仪器 DAT 逐点一致，最大绝对误差为 `1.78 × 10⁻¹⁵`。这些实验室文件没有上传到
公开仓库或 Release。

### 旧 OPJ

旧 OPJ 仅在解析器能够可靠恢复真实 X 列时导入。不能确认 X 轴时，软件会跳过该 worksheet
并报告 `E_IMPORT_ORIGIN_X_COLUMN`，不会把行号或任意 Y 列猜成波长。

仓库中的旧 OPJ 自动测试使用代码生成的最小 CPYA 容器，只证明已覆盖基本容器解码、
workbook 枚举和错误边界。它不是真实仪器金标准。目前不保证旧 OPJ 中以下存储形式：

- `float32` 数值列；
- 整数编码数值列；
- 以文本保存、运行时再转换的 numeric 列；
- 依赖 Origin 公式、插件或项目运行时重新计算的列。

因此，本版本不能表述为兼容所有 Origin 版本或所有 OPJ 数值编码。

旧 OPJ 容器没有端到端完整性校验。某些从尾部截断的文件可能仍能恢复前段 workbook，而不会
被识别为损坏文件；这不是完整项目已恢复的证据。科研使用时必须将导入后的 workbook 数量、
worksheet 数量、列数、点数和波长范围与仪器记录核对，不能只依据“无错误”判断项目完整。

### 不支持的 Origin 对象

本版本不读取、复刻或写回：

- Graph、图层样式和绘图模板；
- Matrix、Image 和嵌入附件；
- Notes、Results Log 和 Project Explorer 文件夹树；
- Origin 分析对象、公式依赖和第三方插件状态；
- OPJ/OPJU 写入、编辑或另存；
- 一个 worksheet 中多条独立 Y 光谱的自动拆分。

## Windows 独立产物

一次最终 `-Language all` 构建必须生成并共同上传：

- `PL-Analyzer-Pro-v1.1.2-Windows-x64-en-US.exe`
- `PL-Analyzer-Pro-v1.1.2-Windows-x64-zh-CN.exe`
- `THIRD-PARTY-NOTICES.txt`
- `SHA256SUMS.txt`

`SHA256SUMS.txt` 必须有前三个文件的三条记录，不包含自身哈希。两个 EXE 均为 PyInstaller
one-file/windowed 程序，包含 Python 和运行依赖；目标计算机无需安装 Python 或 Origin/COM。

## 签发数据来源

本文件不复制容易随重建而变化的产物字节数、哈希或测试计数。精确字节数以同次 GitHub
Release 的 asset 元数据为准；权威机器可读哈希是与 EXE 同次生成并上传的
`SHA256SUMS.txt`。测试、静态检查和构建门槛见下节，实际签发结果以最终构建日志与公开
Release 状态为准。

## 自动与人工验收

`build_release.ps1 -Language all` 执行：

1. 完整 pytest；
2. Ruff lint 与 format check；
3. 受控清理项目内 `build` 和 `dist`；
4. 英文、中文隔离 workpath 的 PyInstaller 构建；
5. 两个 EXE 的定时启动 smoke test；
6. 公开第三方声明生成；
7. 两个 EXE 与第三方声明的 SHA-256 清单生成。

启动 smoke 只证明冻结程序能初始化和退出，不证明每种 Origin 容器都能导入。发布前仍应让
最终英文和中文 EXE 分别读取代表性 OPJU，并检查多 worksheet、Signal+Baseline 和局部失败
语义。真实旧 OPJ 金标准仍是公开的后续验证缺口。

## 已知签发边界

当前 EXE 未代码签名，也没有安装器。Windows SmartScreen 可能显示“未知发布者”。开发机
构建、启动和真实 OPJU 验证不等同于在没有开发工具的干净 Windows 10/11 计算机上完成跨机
认证。科研使用者应从 GitHub Release 下载、先核对 `SHA256SUMS.txt`，再使用自己的代表性
仪器数据复核导入、Raw Peak、拟合、工程保存恢复和导出结果。
