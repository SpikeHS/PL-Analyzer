# 材料搜索窗口与科学边界

## 1. 文档用途

`config/materials.json` 为操作者提供可编辑的 PL 寻峰起点。窗口用于减少候选峰搜索范围，不是
材料鉴定数据库，也不是能带计算器。

必须遵守以下解释：

- 峰落入某材料窗口，只能说明“波长与该配置相容”。
- 同一峰可以同时属于多个候选窗口；软件会保留全部候选标签。
- 波长本身不能唯一确定材料、外延层、缺陷、激子、量子阱/量子点态或复合机制。
- 温度、成分、应变、掺杂、量子限域、激发功率、载流子占据、仪器响应和结构设计都可能移动
  或改变 PL 峰。
- 默认/扩展窗口是基于带隙锚点和实验文献制定的工程建议，不是论文直接规定的标准范围。

### 材料数据库版本与来源契约

`schema_version: 2` 的材料数据库必须声明非空 `database_version`。每个条目必须记录非空的
`window_basis`、`notes` 和至少一条引用；每条引用必须说明非空 `basis`，并提供 DOI 或
HTTPS 来源链接。程序在启动加载数据库时执行这些检查，避免无科学依据或无法追溯的搜索窗口
静默进入分析结果。`schema_version: 1` 仍可加载，以兼容早期工程，但不会获得 v2 的完整来源
保证。

`database_version` 标识材料目录内容修订，与用于解析结构的 `schema_version` 分开。调整默认
范围、科学边界或来源后，应同步递增数据库版本并更新本文件。

## 2. 能量—波长换算

对自由空间光子：

\[
\lambda_\mathrm{nm}=\frac{hc/e}{E_\mathrm{eV}}
=\frac{1239.841984}{E_\mathrm{eV}}
\]

换算常数来自
[NIST 2022 CODATA fundamental constants](https://physics.nist.gov/cuu/pdf/wall_2022.pdf)。
计算出的带隙波长只是窗口锚点；实际 PL 峰不必与理想 bulk 带隙完全重合。

## 3. 当前材料目录

下表与 `config/materials.json` schema v2 一致。Default 是界面初始搜索范围；Extended 是数据库
中记录的排障/探索建议。v1.1 不会自动切换到 Extended，操作者必须在材料表中明确修改上下限。

| 配置 | 类型/参考条件 | 名义锚点 | Default (nm) | Extended (nm) | 适用边界 |
| --- | --- | ---: | ---: | ---: | --- |
| GaAs (300 K) | bulk，300 K | 1.424 eV → 870.676 nm | 860–900 | 850–920 | 近带边 PL；掺杂、应变、缺陷和温度可产生位移或附加带 |
| Al₀.₄Ga₀.₆As (300 K) | alloy，Al fraction \(x=0.40\)，300 K | 1.9228 eV → 644.811 nm | 620–670 | 610–690 | 只适合约 40% Al；靠近 Γ–X 交叉，不能代表所有 AlGaAs |
| InP (300 K) | bulk，300 K | 1.344 eV → 922.501 nm | 890–970 | 870–1000 | 近带边 PL；温度、掺杂与缺陷会改变峰位和线宽 |
| In₀.₅₃Ga₀.₄₇As / InP (300 K) | bulk/厚层，近晶格匹配，300 K | 0.750 eV → 1653.123 nm | 1550–1800 | 1500–1850 | 不适用于其他 In fraction、明显应变层或量子阱 |
| InAs/GaAs QD (1.3 µm family) | 自组装 QD 经验族，约 300 K | 名义 1300 nm，不是 bulk 带隙 | 950–1400 | 900–1800 | 尺寸、In/Ga 互扩散、盖层、应变和退火高度相关 |
| InAs/InGaAs SRL QD | 应变降低层/DWELL 经验族，约 300 K | 名义 1500 nm | 1250–1600 | 900–1800 | 必须根据实际 SRL 成分、厚度和 QD 生长条件编辑 |
| InAs/GaAs QD Laser active region | 1.3 µm 器件族，约 300 K | 名义 1300 nm | 1150–1400 | 900–1800 | 只是器件族便利配置，不是通用材料峰 |
| InₓGa₁₋ₓAs (custom) | 成分/应变/温度未知 | 无 | 无 | 无 | 必须先根据实际结构、温度或实测范围输入 |
| DBR structure (custom) | 光学多层结构 | 无 | 无 | 无 | DBR 有反射 stopband，不存在通用内禀 PL 峰 |

如果实测波长轴没有覆盖窗口，扩大配置不会创造数据；应先确认光栅、探测器、滤光片和仪器校准
覆盖目标范围。特别是 1.5–1.85 µm 条目，需要相应的近红外探测链路。

## 4. 各材料依据与限制

### GaAs

Ioffe 半导体参数库给出 300 K 能隙 1.424 eV，并提供温度依赖式：
[GaAs band structure and carrier concentration](https://www.ioffe.ru/SVA/NSM/Semicond/GaAs/bandstr.html)。
据此换算名义波长为 870.676 nm。860–900 nm 保留为实验室初始窄窗口，850–920 nm 用于样品
状态未知时的扩展检查。

降低温度通常使带隙增大并使近带边 PL 蓝移。因此 77 K、低温 µ-PL 等数据不能继续无条件使用
300 K 默认窗口。高掺杂还会带来带隙收窄、带尾或载流子填充效应。

### Al₀.₄Ga₀.₆As

Ioffe 参数库给出直接区近似 \(E_g=1.424+1.247x\) eV，并给出约 \(x=0.41\) 的 Γ–X
交叉：
[AlGaAs band structure and carrier concentration](https://www.ioffe.ru/SVA/NSM/Semicond/AlGaAs/bandstr.html)。
取 \(x=0.40\) 得 1.9228 eV，即 644.811 nm。

该成分正靠近直接—间接交叉；参数化方法、实际 Al fraction、温度和应变会影响峰位与辐射
效率。仅 \(\Delta x=0.01\) 就对应约 12.5 meV 的直接带隙变化，所以数据库条目必须明确写出
`Al₀.₄Ga₀.₆As`，不能简称为任意成分的 `AlGaAs` 默认。

### InP

Ioffe 参数库给出 300 K 能隙 1.344 eV：
[InP band structure and carrier concentration](https://www.ioffe.ru/SVA/NSM/Semicond/InP/bandstr.html)。
换算为 922.501 nm。890–970 nm 是兼顾室温线宽和样品漂移的操作窗口，不是对所有温度的限制。

### In₀.₅₃Ga₀.₄₇As / InP

Ioffe 数据库列出 Ga₀.₄₇In₀.₅₃As 在 300 K 约 0.74 eV：
[GaInAs basic parameters](https://www.ioffe.ru/SVA/NSM/Semicond/GaInAs/basic.html)。
Takeda 等对 InP 上均匀 In₀.₅₃Ga₀.₄₇As 测得室温能隙 0.750 eV，即 1653.123 nm：
[DOI 10.1063/1.322570](https://doi.org/10.1063/1.322570)。

1550–1800 nm 条目只表示近晶格匹配 bulk/厚层。In fraction 改变、残余应变或原子有序会移动
能隙；量子阱还会因限域显著蓝移，应建立独立结构 profile，而不是扩大 bulk 窗口来混用。

### InAs/GaAs QD

QD 发光不是由 InAs bulk 带隙单独决定。公开实验展示了结构敏感性：

- 直接 GaAs 盖层的 InAs/GaAs QD 在 300 K 可达到约 1.35 µm，且生长温度会使 PL 红移：
  [DOI 10.1016/j.jcrysgro.2003.12.066](https://doi.org/10.1016/j.jcrysgro.2003.12.066)。
- 宽谱 1.3 µm InAs/GaAs QD 会随 InGaAs 应变降低层成分和 InAs 沉积量变化：
  [DOI 10.1002/pssa.201026232](https://doi.org/10.1002/pssa.201026232)。
- In₀.₄₅Ga₀.₅₅As 应变降低层曾实现 300 K、1.52 µm 发光，并明确指出峰位可由 SRL In
  成分调节：
  [DOI 10.1016/S0022-0248(01)02048-6](https://doi.org/10.1016/S0022-0248(01)02048-6)。

因此 950–1400 nm 和 1250–1600 nm 是两类常见结构的经验入口，不是 InAs QD 的普适上下限。
已知 layer stack 时应优先使用该批外延的设计值或实测先验。

## 5. DBR 与 QD Laser

### DBR

DBR 是由高/低折射率层的光学厚度决定的反射结构。其 Bragg 中心近似满足四分之一波光学厚度
\(n_Hd_H=n_Ld_L=\lambda_B/4\)，因此同一材料体系可通过厚度设计成不同 stopband。

一项 AlAs/(GaAs/AlAs) DBR 实验得到约 810 nm 中心，并通过调整层厚模拟了 1.3 µm 中心：
[DOI 10.1016/j.jlumin.2006.01.303](https://doi.org/10.1016/j.jlumin.2006.01.303)。
这说明 DBR 不应拥有“材料默认 PL 峰”。当前 `dbr_structure` 故意没有窗口；如需分析，应输入
实际发光层/腔模范围。反射 stopband 的定量分析属于后续反射率/高级光谱模块。

### QD Laser

QD Laser 是包含 QD active region、波导、包层、腔和可能的 DBR/光栅的器件，不是单一材料。
1.3 µm InGaAs/GaAs QD ensemble 已有 300 K、1.31 µm 基态激光报道：
[DOI 10.1063/1.122534](https://doi.org/10.1063/1.122534)。这只能支持一个具体器件族的名义
目标，不能成为所有 QD Laser 的固定 PL 窗口。

自发 PL、受激发射和腔模还可能因载流子占据、激发态激射、温度与腔损耗而不同。当前
`qd_laser_1300_active_region` 必须视为可编辑的 1.3 µm 家族便利项；设计未知时不要用它自动
宣称材料或激光态归属。

## 6. 多材料结果的正确使用

1. 同时选择与 layer stack 有关的多个窗口，例如 GaAs cap 与 Al₀.₄Ga₀.₆As layer。
2. 先确认参考温度和成分，再编辑窗口。
3. 对同一峰出现多个材料标签时，将其视为候选集合，而不是软件冲突。
4. 结合外延层、相对峰强、温度/功率依赖、参考样品和拟合残差作进一步判断。
5. 不应根据窗口命中自动生成“已确定为某材料”的报告语句。

## 7. 通用参数参考

III–V 二元/三元材料的带隙、合金 bowing、温度和应变参数可参考：

- I. Vurgaftman, J. R. Meyer, L. R. Ram-Mohan,
  “Band parameters for III–V compound semiconductors and their alloys,”
  [DOI 10.1063/1.1368156](https://doi.org/10.1063/1.1368156)。
- [Ioffe Institute NSM semiconductor property archive](https://www.ioffe.ru/SVA/NSM/Semicond/)。

这些参数可用于构造新的候选窗口，但从带隙公式到软件上下限仍是工程推断，必须记录假设并允许
操作者修改。
