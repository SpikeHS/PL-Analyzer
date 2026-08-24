# PL Analyzer Pro v1.1.4 DAT 与参考样式导出发布说明

## 1. 变更范围

v1.1.4 将原先独立的仪器 DAT→PNG 快速流程兼容到现有 PySide6 应用，同时保持 v1.1.3 的
OPJ/OPJU、CSV、Excel、多材料 Raw Peak、模型拟合、工程恢复、双语言和 Windows 构建能力。
本次没有复制旧 Tkinter 前端，也没有替换既有 Raw Peak 或拟合算法。

## 2. 仪器 DAT 导入

- Reader registry 新增 `.dat`，拖拽、文件对话框和批量导入使用同一服务边界。
- 只接受带 `Wavelength, Signal, Baseline` 三列、至少三个有效数值点的仪器 ASCII 结构。
- 导入强度明确计算为 `Signal − Baseline`，并记录
  `INSTRUMENT_BASELINE_SUBTRACTED` 诊断。
- `Folder` 末级用于推断样品显示名；Laser、Power、Temperature 等文件头元数据随
  `SourceInfo` 和 `.plproj` 保存。
- `.plproj` 递增到 schema v3；内置 v2 → v3 迁移为旧工程补充空来源元数据对象。

真实用户 DAT 不进入仓库。自动测试使用合成、脱敏的最小仪器文本；本地端到端复核另外读取
原始 1,024 点 QW 光谱，但只保留汇总结果，不提交源文件。

## 3. 参考样式 PNG 与配套文件

当恰好一条光谱可见时，`File → Export → Export reference-style PNG` 可输出默认
2400×1500、300 dpi PNG。视觉规范来自原始参考页：白底、深蓝标题、青绿色短线、红色
光谱、蓝色主峰/半高宽标记和灰色次峰/肩峰说明。

操作者可同时导出：

- `*_PL_metrics.json`：版本、指标语义、来源元数据、主峰、能量、展示半高宽、积分、质心、
  噪声/SNR 和次峰；
- `*_PL_processed.csv`：波长、导入强度、显示平滑强度、展示基线校正强度、归一化强度和
  光子能量。

三个目标均采用同目录临时文件和原子替换；目标扩展名或写入失败返回稳定的应用错误。
面向分享的 JSON 仅写源文件名，并主动排除 `Folder` 与 `Operator`，避免泄露本机目录和人员
信息；完整来源仍可在本地 `.plproj` 中追溯。

## 4. 科学语义

`Presentation FWHM` 的定义是：完整光谱轻度 Gaussian 平滑后，主峰相对估计低光谱基线的
半高交点距离。该名称刻意区别于：

1. Raw Peak 的半 prominence 宽度；
2. Gaussian/Lorentzian/Voigt/Pseudo-Voigt 联合拟合得到的模型 FWHM。

展示平滑只创建只读副本，不回写 `SpectrumSeries.intensity_au`，也不进入 Workspace 的
Raw Peak/Fit 结果。展示峰位、FWHM、肩峰或较高 SNR 不能单独证明材料、量子阱跃迁或缺陷
机制；峰强和积分的跨样品比较仍要求测量条件和仪器响应一致。

## 5. 本地验证记录

在 macOS、Python 3.12 的项目虚拟环境完成：

- 全部 `135` 项 pytest 通过；
- `ruff check .` 通过；
- `ruff format --check .` 通过；
- Qt offscreen 英文/中文主窗口与翻译目录测试通过；
- 合成 1200×750 PNG 像素尺寸、PNG 签名、JSON/CSV 内容测试通过；
- 真实 1,024 点 QW DAT 端到端得到样品 `QW-12`、主峰 `761.9 nm`、
  Presentation FWHM `27.98 nm`、峰能量 `1.627 eV` 和弱肩峰 `876.9 nm`。

本地未在 macOS 交叉生成 Windows EXE。正式发布仍须在 Windows 使用
`build_release.ps1 -Language all` 运行完整门槛、分别启动英文/中文一文件 EXE，并复核 DAT
导入和参考样式 PNG/JSON/CSV。产物仍未代码签名，不应描述为完成跨机签发认证。

## 6. 兼容性结论

- v1.1.3 的已有文件格式、领域算法、工程 schema 版本和导出入口保持不变；
- 新 DAT 元数据由 schema v3 保存，旧 schema v2 工程经内置迁移继续读取；
- 旧独立工具的 DAT→PNG、样品名推断、基线扣除、峰/FWHM/肩峰和 JSON/CSV 能力已经由现有
  PySide6/Matplotlib 架构承接；
- 不再维护第二套 Tkinter/Pillow GUI 或单独的 PyInstaller spec。
