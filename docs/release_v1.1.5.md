# PL Analyzer Pro v1.1.5 修复发布说明

## 修复

- 拟合设置界面修改任意控件时不再弹出
  `settings_changed() only accepts 0 argument(s), 1 given`。
- 根因：`FitPanel.settings_changed` 为零参数信号，控件信号直接连接
  `settings_changed.emit` 会把控件值传入。现改为 lambda 包装后触发。
- 该修复恢复 v1.1.3 期间已验证的行为，v1.1.4 合并时被旧版覆盖。

## 验证

- 135 项 pytest 通过。
- Ruff lint 和 format 通过。
- 英文与中文 EXE 构建通过。
- 英文与中文 EXE smoke test 通过。
- 拟合设置界面改动无错误弹窗。

## 兼容性

- 科学算法、`.plproj` schema、导入导出契约不变。
- v1.1.4 全部能力保持可用。
