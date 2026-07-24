# PL Analyzer Pro v1.1.2 架构

## 1. 架构目标

v1.1 保持桌面 UI、领域状态、科学算法、文件适配器和持久化边界分离。新增拟合、Layer Editor
和 `.plproj` 时没有改变 Raw Peak 的科学语义，也没有让 Qt Widget 成为工程数据模型。

```text
main.py / main_zh.py（语言入口与组合根）
├── ui（Qt View + presentation controller）
│   ├── sample / peak / fit / layer panels
│   ├── preferences / theme / log / localization
│   └── main_window（用例编排与统一错误边界）
├── core
│   ├── importing（OPJ / OPJU / CSV / XLSX / XLSM / XLS adapters）
│   ├── models / workspace（光谱、显示状态、Raw Peak 状态）
│   ├── configuration（应用设置与材料目录）
│   └── project / persistence（领域工程与版本化 JSON）
├── analysis
│   ├── raw_peak（无拟合峰搜索）
│   ├── fitting（模型、基线、预处理与优化）
│   └── fit_session（材料标注结果与工程序列化）
├── plotting（Matplotlib Qt adapter）
└── export（Raw Peak / Fit XLSX、CSV adapters）
```

依赖原则：

- `main.py` 只完成 `QApplication`、配置、服务和主窗口的组合。
- `main.py` 与 `main_zh.py` 只选择默认显示语言；两者装配同一组领域服务和窗口类。
- 导入器不依赖 Qt；科学算法不感知 Widget、Matplotlib 或文件对话框。
- OPJ/OPJU 由内置只读解析器处理，不依赖 Origin、COM 或 Origin Automation Server。
- `core.models`、`core.workspace` 和 `core.project` 不依赖 PySide6、Matplotlib、openpyxl 或
  xlrd。
- `ui` 负责收集操作意图和呈现结果，不自行实现峰形、基线或表格文件格式。
- `core.persistence` 负责结构化 JSON 和原子文件操作；拟合模块通过带自身 schema 的 JSON
  payload 独立演进。

## 2. 模块职责

| 模块 | 单一职责 |
| --- | --- |
| `core/models.py` | 光谱、来源、显示状态、材料搜索窗口、Raw Peak 结果 |
| `core/configuration.py` | 验证应用设置和 schema v1/v2 材料数据库 |
| `core/importing/column_detector.py` | 共享列识别、数值清洗、排序和重复波长合并 |
| `core/importing/readers.py` | OPJ/OPJU、CSV、XLSX/XLSM、XLS 扩展名注册与格式隔离 |
| `core/importing/origin_backend.py` | 内置解析器数据到稳定 Origin worksheet 中间模型的适配 |
| `core/importing/origin_reader.py` | CPYA/CPYUA 签名校验与 Origin worksheet 表格化 |
| `core/importing/_origin_parser/` | 固定版本的 Apache-2.0 clean-room worksheet 解析子集 |
| `core/importing/service.py` | 多文件、多 Sheet、局部失败的导入用例 |
| `core/workspace.py` | 样品集合、颜色/显隐、绘图状态、材料标注 Raw Peak 结果 |
| `core/project.py` | Layer、项目材料窗口快照和完整工程领域对象 |
| `core/persistence.py` | `.plproj` schema、验证、迁移入口、事务式加载和原子保存 |
| `analysis/raw_peak.py` | 不平滑、不扣基线、不拟合的 Raw Peak 算法 |
| `analysis/fitting.py` | 四种峰形、三种基线、Savitzky–Golay、联合优化和统计量 |
| `analysis/fit_session.py` | 材料/样品标注的拟合结果、表格记录和版本化工程 payload |
| `plotting/plot_widget.py` | 非破坏显示变换、Raw Peak 标记、拟合叠加和图像导出 |
| `export/peak_table.py` | Raw Peak 的原子 XLSX/CSV 导出 |
| `export/fit_table.py` | 拟合参数与统计量的原子 XLSX/CSV 导出 |
| `ui/peak_panel.py` | 多材料选择、项目内窗口编辑、候选标签表 |
| `ui/fit_panel.py` | 拟合设置和只读结果表 |
| `ui/layer_editor.py` | 外延层增删改、排序与输入校验 |
| `ui/localization.py` | 支持语言、Qt/Application 翻译目录加载与失败边界 |
| `ui/main_window.py` | 菜单、用例编排、脏状态、工程恢复与异常边界 |

## 3. 核心不变量

1. `SpectrumSeries.wavelength_nm` 与 `intensity_au` 是只读、一维、等长数组；字段名带单位。
2. 波长存储前严格递增；重复波长按强度均值合并并记录诊断。
3. Normalize、Offset、Log、颜色和主题只改变显示，不污染 Raw Peak 或拟合输入。
4. 一个坏文件、坏 Sheet 或失败的材料窗口分析不会销毁同批成功结果。
5. Raw Peak 永远不执行 Savitzky–Golay、基线扣除或模型拟合。
6. 拟合永远从材料窗口内的原始线性强度开始；可选平滑只生成初值估计副本，优化与统计量仍
   使用原始观测。
7. 材料范围来自 `config/materials.json` 或项目内编辑，不得在分析算法中写死。
8. 搜索窗口标签是候选归属，不是成分或跃迁的唯一识别结果。
9. 层厚使用 `thickness_nm`，掺杂浓度使用 `doping_concentration_cm3`；持久化键明确写为
   `doping_concentration_cm^-3`。
10. 工程只有在全部解析、schema 验证和领域校验成功后才替换当前 UI/工作区状态。
11. 语言只影响显示文本；中英文 EXE 共用材料 ID、算法、导出契约和 `.plproj` schema。

## 4. Origin 原生导入边界

内置解析器来自 Apache-2.0 `quantized-lab` v0.11.0，并固定到提交
`c34980b82947af3f82f7a9a4ff5692610ba5398f`。私有 facade 只暴露 workbook/worksheet
数据，不允许 UI、Workspace 或分析模块直接依赖上游 `DataStruct`。格式层严格区分旧 OPJ
的 `CPYA ` 签名与 OPJU 的 `CPYUA ` 签名，因此同样使用 `.opj` 扩展名的非 Origin 文件不会
进入科学分析。

一个项目可返回多个 workbook/worksheet；解析器先产生稳定的 `OriginWorksheet` 中间模型。
X 轴已安全恢复的 worksheet 转换为 `TabularSheet`，否则转换为
`TabularSheetError`；只有通过共享 `ColumnDetector` 的 worksheet 才成为一个
`SpectrumSeries`。同一 worksheet 的所有数值列保持在同一表内，不会按每个 Y designation
自动拆样品。因而 `Wavelength + Signal + Baseline` 只产生一个 Signal 光谱，不会把 Baseline
变成第二个样品。解析失败按文件或 worksheet 进入 `ImportBatchReport.issues`，同项目其他
worksheet 和同批其他文件继续导入。

此边界只负责只读 worksheet 数据。图、矩阵、Notes、Results Log、模板、嵌入附件、Project
Explorer 文件夹树、Origin 公式重算和项目写入均不在支持范围。完整的来源、真实数据对照、
限制和发布要求见
[Origin OPJ/OPJU 原生导入](origin_import.md)。

## 5. 多材料 Raw Peak 边界

每个已选材料窗口独立调用 `RawPeakAnalyzer`。峰中心受该窗口约束，但峰宽在峰所在的完整连续
数据段计算，避免窗口边缘人为截断。缺失强度和异常大的波长间隙会拆分连续段。

`scipy.signal.find_peaks` 产生候选峰，`peak_widths(rel_height=0.5)` 在半 prominence 高度
给出 fractional-sample 交点，再映射回真实波长。因此 Raw `FWHM`：

- 支持不等间隔波长；
- 不是简单的“点数 × 平均步长”；
- 不是基线校正后的传统半峰高拟合宽度；
- 在边界或数据缺口导致无法求宽时为 `None`，并带质量标记。

重叠窗口在同一个采样位置得到峰时，`Workspace` 合并显示记录并保留所有材料名称。当前合并
依据是相同的峰位数值，不试图通过波长、强度或外延层自动裁决材料。更复杂的概率归属属于后续
经过物理验证的模块。

## 6. v1.1 拟合边界

`SpectrumFitter` 在一个样品的一个材料窗口内工作，支持：

- `gaussian`
- `lorentzian`
- `voigt`
- `pseudo_voigt`
- `none`、`constant`、`linear` baseline
- 可选 Savitzky–Golay
- 固定峰数或自动峰数

峰与基线在同一次最小二乘优化中求解。结果保留原始窗口数据、处理副本、拟合曲线、基线曲线、
残差、峰参数和统计量；这些数组在结果对象中同样只读。

Auto 模式枚举成功收敛的线型和允许峰数，以最低 BIC 选择；参数更少的候选和固定模型优先级
仅用于 BIC 完全相同的稳定排序。Savitzky–Golay 仅帮助构造初值，所有候选的残差与信息准则
均在同一原始观测上计算。R²、调整 R²、AIC、面积和 FWHM 是结果/诊断字段，不替代 BIC
选择。BIC 只适合比较同一数据窗口的候选，不能跨材料窗口直接排名。

Gaussian、Lorentzian 和 Pseudo-Voigt 使用物理 FWHM 参数化；Voigt 同时保存 Gaussian 与
Lorentzian 分量宽度，并报告组合线型的 FWHM。面积是所选峰形去除联合基线后的模型积分量，
单位为 a.u.·nm，不是 Raw Peak 的输出。

## 7. 材料数据库边界

材料目录是只读加载的版本化 JSON。schema v2 可保存：

- 稳定材料 ID、显示名、别名和类别；
- 参考温度、名义跃迁能量/波长；
- 默认窗口和扩展窗口；
- 窗口依据、科学说明和来源 URL。

界面以 `default_peak_window_nm` 初始化可编辑范围。`extended_peak_window_nm` 当前是目录元数据
和排障建议，不是自动扩展开关；操作者需要时应在界面明确修改上下限。项目保存的是本工程的
材料选择和编辑后窗口，不会反写全局 `config/materials.json`。

无成分/温度就没有可靠通用范围的条目允许窗口为空。DBR 和变量成分 InGaAs 属于此类；
选择后 UI 会要求先输入有效范围。详细限制见
[材料搜索窗口与科学边界](material_windows.md)。

## 8. `.plproj` 持久化

当前顶层格式为：

```text
format_id = "pl-analyzer-pro-project"
schema_version = 2
project
├── workspace
│   ├── plot_settings
│   └── spectra[]（原始数组、来源、颜色、显隐、诊断）
├── layers[]
├── material_windows[]
├── analysis_results
│   ├── raw_peak
│   └── fit（自带 fit schema_version）
└── extensions
    ├── theme
    ├── fit_ui_settings
    └── raw_peak_preferences
```

原始数组内嵌，工程恢复不依赖原数据路径；禁止 pickle 和非有限 JSON 数值。保存使用目标目录内
临时文件、flush、fsync、`os.replace`。加载先构造独立 `PLProject`，完成格式、版本、数组、
ID 和领域约束验证后再由主窗口一次性替换。

较新 schema 被只读拒绝，防止旧程序覆写丢字段。迁移注册表要求每次只前进一个 schema 版本，
为后续 v1.2–v5.0 保留纯函数迁移路径。内置 v1 → v2 迁移将旧材料 ID `gaas` 和
`algaas_al040` 规范为材料数据库 v2 的稳定 ID，并同步迁移工程窗口、Raw Peak assignment
和 Fit assignment；未知自定义材料 ID 保持不变。

## 9. 后续版本扩展方式

- v1.2 AI 只消费外延层、带来源的材料上下文、Raw Peak/拟合结果和操作者问题，不直接访问
  Qt Widget，也不把语言模型结论写回原始数据。
- v2.0 Batch 复用无 UI 的 importer、analyzer、fitter 和 exporter，在任务层增加队列、
  进度、取消、资源限制和批级审计记录。
- v3.0 Advanced Spectroscopy 可增加能量轴、温度/功率序列、校准、反射率和 DBR stopband
  模块，不改变现有 PL reader 或把 DBR 当作固定材料 PL 峰。
- 新峰形实现统一拟合结果协议；Raw Peak 的无拟合定义保持不变。
- 新工程字段优先进入明确 schema；试验性、可忽略字段可先进入 `extensions`，稳定后通过迁移
  提升为正式字段。
