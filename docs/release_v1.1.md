# PL Analyzer Pro v1.1 发布验证记录

## 构建身份

- 构建日期：2026-07-23
- 产品版本：1.1.0
- 入口：`main.py`
- 规格：`PLAnalyzerPro.spec`
- 构建脚本：`build_release.ps1`
- Python：3.12.10
- PyInstaller：6.21.0
- 构建系统：Windows 11，64-bit
- 产物：`dist/PL Analyzer Pro.exe`
- 大小：109,467,697 bytes
- SHA-256：`7C3EE72CE1B8CC303CD3951D5271FC4B3AED919391129091B1642007EBDE7ECE`
- 代码签名：未签名

## 自动验证

构建脚本在生成 EXE 之前完成以下门槛：

- 90 项 pytest 全部通过；
- Ruff lint 与 format check 全项目通过；
- `compileall` 与源码离屏启动通过；
- PyInstaller one-file/windowed 构建成功；
- EXE Windows 版本资源为 ProductVersion `1.1.0`；
- 单文件从独立 `dist` 目录启动并以退出码 0 完成定时 smoke test；
- PyInstaller 解包环境成功读取内置 `config/default_settings.json` 与
  `config/materials.json`。

源码级端到端演练还验证了：

- 同一合成谱中的 Al₀.₄Ga₀.₆As 与 GaAs 两个材料窗口同时执行；
- Raw Peak 得到两个材料标注结果；
- 两个窗口分别完成 Gaussian + Linear baseline 拟合，R² 均高于 0.999；
- `.plproj` 保存后恢复一条原始光谱及两条完整拟合 assignment。
- schema 1 工程自动迁移到 schema 2，并同时恢复旧材料 ID、自定义范围与选中状态；
- 非均匀轴 Savitzky–Golay、亚采样/同中心不可分辨峰及非法配置均返回稳定错误，
  不输出伪精确拟合指标。

## Windows 可视化复核

实际启动打包后的 EXE，并检查：

- File、Analysis、View、Tools、Help 菜单和主工具栏；
- Raw Peak 与 Fit 侧栏标签；
- GaAs、Al₀.₄Ga₀.₆As 默认同时勾选；
- Material、Min、Max 三列在默认窗口中同时可见；
- InP、In₀.₅₃Ga₀.₄₇As/InP 与 QD 条目从内置材料数据库加载；
- Matplotlib 导航工具栏；
- Layer Editor 的 Add/Edit/Remove/Move 控件和全部字段；
- 底部 Log；
- 无未保存变更时正常关闭。

打包版真实计算复核还完成了：

- 通过桌面文件对话框导入 `tests/fixtures/packaged_smoke.csv`（62 个数据点）；
- 同时使用 GaAs 与 Al₀.₄Ga₀.₆As 两个材料窗口执行 Raw Peak，得到
  645 nm 与 875 nm 两个峰；
- 在 EXE 内调用 SciPy 自动拟合链路，两个材料窗口均成功，合计输出
  2 个可分辨 Gaussian 峰、拟合曲线与结果表，0 个窗口跳过；
- GaAs 结果为 875 nm、FWHM 12 nm、R² 1；Al₀.₄Ga₀.₆As 结果为
  645 nm、FWHM 10 nm、R² 1，Area 与全部信息准则可复制；
- 日志记录数据导入、Raw Peak 和模型拟合全部完成。

## 签发边界

此产物是本工作区的可运行 v1.1 Windows 交付物，不是已签名安装包。正式对外签发前仍需：

1. 在干净 Windows 10 与 Windows 11 机器上执行真实 CSV/XLSX/XLS 数据验收；
2. 复核 PNG/SVG/PDF、XLSX/CSV 产物与目标办公软件兼容性；
3. 使用代表性 MBE 实测光谱复核自动模型选择、残差和参数稳定性；
4. 配置最终产品图标、代码签名和病毒扫描误报处理；
5. 记录签发后新产物的 SHA-256；签名会改变本记录中的未签名哈希。
