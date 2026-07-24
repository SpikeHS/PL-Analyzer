# Origin OPJ/OPJU 原生导入

## 支持范围

PL Analyzer Pro 内置 Origin worksheet/workbook 读取器，可以直接导入：

- 旧格式 `.opj`，文件签名为 ASCII `CPYA `；
- Unicode `.opju`，文件签名为 ASCII `CPYUA `。

导入过程不启动或自动化 Origin，不使用 COM、Origin Automation Server 或 Origin Viewer。
从源码运行时仍需要本项目的 Python 环境；PyInstaller 发布版把解析代码和 NumPy 一并封装，
最终用户不需要安装 Python、Origin 或 OriginPro。

`.opj` 也可能是 OrCAD 等其他软件的文件扩展名，因此软件同时检查扩展名和容器签名。扩展名与
签名不匹配时会以可恢复错误拒绝，不会把任意二进制文件交给光谱列识别器。

## 解析器来源与固定版本

内置解析器是
[`quantized`](https://github.com/pquarterman17/quantized) 的 clean-room Origin worksheet
读取子集，采用 Apache License 2.0：

- Python 包：`quantized-lab`
- 上游版本/标签：`v0.11.0`
- 固定提交：
  `c34980b82947af3f82f7a9a4ff5692610ba5398f`
- 本地清单：`core/importing/_origin_parser/UPSTREAM.md`
- 上游许可证与署名：
  `core/importing/_origin_parser/LICENSE`、`core/importing/_origin_parser/NOTICE`

本地副本只保留 worksheet/workbook 解码所需模块。上游解析算法和 `DataStruct` 数据契约保持
不变；对上游文件的代码级修改仅限把绝对包导入改写为本私有包的相对导入，并在相关文件头部
保留修改说明。`core.importing._origin_parser` 的 facade 负责按扩展名分派 OPJ/OPJU。

解析器不是 liborigin，也不包含或链接 GPL 解析代码。升级时不得跟随未固定的分支或重新手写
解析逻辑；必须从经过审查的上游发布标签重新取回清单中的文件，更新固定提交，保留
`LICENSE`/`NOTICE`，然后重新执行本页全部验证门槛。

## 导入语义

导入链路保持格式适配器与 PL 领域模型分离：

```text
OPJ/OPJU
  → bundled parser（Origin workbook/worksheet + 列元数据）
  → BundledOriginBackend（私有 DataStruct → OriginWorksheet）
  → OriginProjectReader（OriginWorksheet → TabularSheet）
  → ColumnDetector（波长/强度自动识别与清洗）
  → SpectrumImportService
  → SpectrumSeries / Workspace
```

一个项目可以包含多个 workbook 和 worksheet；附加 worksheet 由解析器以 `Book@N` 形式枚举。
解析器先把它们规范化为 `OriginWorksheet`；X 轴已安全恢复的 worksheet 转换为
`TabularSheet`，否则转换为带 `E_IMPORT_ORIGIN_X_COLUMN` 的 `TabularSheetError`。只有包含
可用数值列并通过统一列检测的 worksheet 才形成 `SpectrumSeries`。同一 OPJ/OPJU 因而可以
一次导入多个光谱。来源名称保留可恢复的 workbook 显示标题和 sheet 后缀，多结果显示名继续
由导入服务按“项目文件名 / worksheet”组成，并由 Workspace 处理重名。

一个 worksheet 始终作为一个表交给共享 `ColumnDetector`，而不是把每个 Y designation
机械拆成样品。典型仪器表同时含：

```text
Wavelength [nm] | Signal [mV] | Baseline [mV]
```

这种表只产生一条 PL 光谱：`Wavelength` 是横轴，`Signal` 是强度，`Baseline` 保留为同表辅助
列但不会变成第二个样品。该约束避免把基线、误差列或分析结果列误报成独立测量。如果一个
worksheet 实际保存多条独立 PL Signal，目前仍只导入自动识别出的一个波长/强度对；以后增加
显式列选择时应扩展导入契约，不得在格式适配器中按所有 Y 列静默扩张样品数。

列长名称、单位、短名称和可恢复的 X/Y designation 先进入格式中间模型，再组合成普通表头，
例如 `Wavelength [nm]`。后续排序、非有限值过滤、重复波长合并和至少三个有效点等规则继续
由所有格式共用的 `ColumnDetector` 执行。

## 验证证据

真实 PL 数值验证使用一份本地 `PL DATA.opju` 和它引用的五份原始 DAT。每份 DAT 含
1,215 个有效采样点以及 `Wavelength`、`Signal`、`Baseline` 三列。验证结果为：

- 恢复 5 个 worksheet，共 `5 × 1,215` 个波长/Signal 数据点；
- 每个 worksheet 只生成一个样品，Baseline 没有被拆成样品；
- 与五份 DAT 的对应数值逐点比较，最大绝对误差为 `1.78 × 10⁻¹⁵`。

这些仪器文件只用于本地对照，没有提交到公开仓库，也不得加入 Git 历史、Release 附件或公开
测试夹具。若以后需要可再分发的真实仪器回归样本，必须先完成数据脱敏和明确授权。

当前仓库运行的是代码生成的最小 CPYA 合成回归样本，用于验证旧格式 OPJ 的容器解码、
工作簿枚举和失败边界；它不是公开真实 OPJ fixture，也不是 PL 仪器数据的科学验收证据。
若以后引入可再分发的公开旧 OPJ fixture，它仍只能作为容器兼容验证，不能替代上述
OPJU/DAT 数值对照。

## 限制与错误恢复

当前原生导入是只读的 worksheet/workbook 数据功能，不等同于 Origin 项目完整复刻。以下内容
不在支持范围内：

- 写入、修改或另存 OPJ/OPJU；
- 图、图层样式、矩阵页、Notes、Results Log、模板和嵌入附件；
- Project Explorer 文件夹树的完整复原；
- 依赖 Origin 公式重新计算或第三方插件才能生成的数据；
- 对任意未验证 Origin 版本或损坏/截断的私有容器承诺完整恢复；
- 在一个 worksheet 中自动拆分多条独立 Y 光谱。

解析器不能确认 X 轴时不会猜测波长列。该 worksheet 会形成可恢复的 sheet issue；同项目其他
有效 worksheet、同批 CSV/XLSX/XLS 以及其他 OPJ/OPJU 仍继续导入。主要错误码为：

| 错误码 | 含义 |
| --- | --- |
| `E_IMPORT_ORIGIN_SIGNATURE` | 扩展名对应的 CPYA/CPYUA 签名不匹配 |
| `E_IMPORT_ORIGIN_COMPONENT` | 内置解析组件缺失，发布包不完整 |
| `E_IMPORT_ORIGIN_READ` | 容器损坏、版本/结构不支持或解析失败 |
| `E_IMPORT_ORIGIN_NO_WORKSHEETS` | 没有找到可用的数值 worksheet |
| `E_IMPORT_ORIGIN_X_COLUMN` | 某个 worksheet 的 X 轴无法安全恢复，已跳过该表 |
| `E_IMPORT_COLUMNS_NOT_FOUND` | 某个 worksheet 无法可靠识别 X/强度列 |

所有错误继续走 `ImportBatchReport`、底部 Log 和 UI 弹窗边界。导入不会修改源 OPJ/OPJU，也
不会在源目录旁写中间文件。

## PyInstaller 与发布门槛

源代码测试通过不代表一文件 EXE 已具备 OPJ/OPJU 能力。每次正式发布必须：

1. 固定并审计 `UPSTREAM.md` 中的上游版本和完整提交哈希；
2. 保留 vendored 文件头部的修改说明；
3. 保留源码内 `core/importing/_origin_parser/LICENSE` 和
   `core/importing/_origin_parser/NOTICE`；当前 PyInstaller 配置会把它们收集到冻结应用的
   `licenses/quantized-origin`，发布时还须确认最终用户能够访问这些第三方声明；
4. 确认 PyInstaller 实际收集 `_origin_parser` 的全部运行模块，而不是只通过源码环境测试；
5. 在没有 Python、Origin 和 Origin COM 注册的干净 Windows 10/11 机器上，分别用英文版和
   简体中文版 EXE 导入 OPJ 与 OPJU；
6. 对冻结版重新执行多 workbook/worksheet、Signal+Baseline、错误签名、损坏文件和批量局部
   失败测试；
7. 记录 EXE 哈希、解析器固定提交、许可证清单和跨机验证结果。

如果 EXE 未包含解析组件或 `LICENSE`/`NOTICE`，即使 CSV/XLSX 导入和启动 smoke test 通过，
也不得发布为具有“OPJ/OPJU 原生导入”能力的版本。
