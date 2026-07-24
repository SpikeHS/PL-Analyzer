# PL Analyzer Pro v1.1.3 旧版 Origin OPJ 兼容发布说明

## 发布目标

v1.1.3 是 v1.1.2 原生 Origin 导入的兼容性补丁，重点支持部分仪器仍在生成的旧版
`CPYA 4.2930` OPJ 工程。CSV、Excel、`.plproj`、Raw Peak、拟合、材料数据库和双语言 UI
契约不变。

构建目标：

- `PL-Analyzer-Pro-v1.1.3-Windows-x64-en-US.exe`
- `PL-Analyzer-Pro-v1.1.3-Windows-x64-zh-CN.exe`
- `THIRD-PARTY-NOTICES.txt`
- `SHA256SUMS.txt`

## 修复内容

- dataset header 通过格式中的结构化名称字段识别，不再用块长能否被 10 整除判断；
- 支持 CPYA 4.2930 的 140-byte dataset header；
- 支持 341-byte `Pd<Name>` sheet header 和 493-byte column property；
- Origin 短列名上限与数据集规则统一为 16 字符；
- `Book@N` 使用对应 sheet 自身的 X/Y designation、Long Name 和 Unit；
- graph reference 中类似数据集的字符串不会被误识别成 worksheet header；
- 少于 3 个有限 X/Y 对的 Graph/Note 辅助页不会进入 PL 导入层，也不会产生误导性警告；
- 波长轴仍必须来自显式 X designation、`Wavelength`/`nm` 语义等可靠证据，不按数值范围
  猜测。

本补丁没有扩大所有 Origin 对象的支持范围：matrix、graph 绘图对象、notes、分析树以及
无法可靠解码的 int/float32/text worksheet storage 仍按既有安全策略跳过，不输出伪造数值。

## 真实仪器文件验证

验证文件：

- 签名：`CPYA 4.2930 90#`
- 大小：1,048,411 bytes
- SHA-256：
  `C2DB4871674E42B554F05BDAB210C13CCEBB10E0DA29AC994B5C201D2E9E765F`

结果：

- 成功导入 7 条 PL 光谱，0 个导入 issue；
- 4 条为 401 点，3 条为 4,001 点；
- 所有波长轴均为 1000–1400 nm；
- 恢复 `A: X / Wavelength / nm`；
- 恢复 `DSSIGA190: Y / DSS-IGA-(1-9)010L_R / Microvolts`；
- 辅助 `PdGraph`、`PdNote` sheet 未作为 PL 样品显示。

真实文件只用于本机回归，没有提交到仓库或 Release。

## 解析器来源与本地修改

Origin OPJ/OPJU 读取仍基于
[`pquarterman17/quantized`](https://github.com/pquarterman17/quantized)
的 `quantized-lab` v0.11.0 worksheet/workbook reader subset，固定提交：

`c34980b82947af3f82f7a9a4ff5692610ba5398f`

上游许可证为 Apache-2.0。v1.1.3 在 vendored `opj.py` 与 `windows.py` 中加入上述定向、
有回归测试的 CPYA 4.2930 兼容修改；`DataStruct` 契约不变。完整 `LICENSE`、`NOTICE`、
固定版本、提交和逐项本地修改记录位于
`core/importing/_origin_parser/`，并进入 EXE 与公开的
`THIRD-PARTY-NOTICES.txt`。本项目没有包含或链接 GPL `liborigin` 代码。

## 验证门槛

正式构建前必须通过：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\build_release.ps1 -Language all
```

除自动测试外，还应分别启动英文和中文 EXE，导入上述真实 OPJ，确认 7 个样品显示、绘图与
日志均正常。当前开发机产物未代码签名，也不代表已完成干净 Windows 10/11 跨机认证。
