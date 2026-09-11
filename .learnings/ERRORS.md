# Errors Log

记录所有命令和操作失败的情况。

## 格式

```markdown
## [日期] 错误描述

**命令/操作**: 
执行的命令

**错误信息**: 
错误输出

**根本原因**: 
分析原因

**解决方案**: 
修复方法
```

## 2026-09-03 apply_patch 沙箱网络命名空间失败

**命令/操作**:
使用内置 apply_patch 更新美股扫描器。

**错误信息**:
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`

**根本原因**:
当前文件沙箱辅助进程无法创建 loopback 网络命名空间，并非补丁内容错误。

**解决方案**:
在用户批准后使用同一个 apply_patch 命令以工作区外层权限执行。
