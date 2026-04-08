# Learnings Log

记录重要的学习内容，包括用户的纠正、错误的修复、更好的方法等。

## 使用方法

当发生以下情况时，记录学习内容：

- 用户纠正了你（"No, that's wrong...", "Actually..."）
- 命令或操作意外失败
- 用户请求不存在的功能
- 外部API或工具失败
- 你发现自己的知识过时或不正确
- 发现了更好的方法

## 记录格式

```markdown
## [日期] 事件标题

**类别**: correction | error | feature_request | knowledge_gap | best_practice

**发生了什么**: 
描述事件

**应该怎么做**:
改进方案

**相关文件**:
- 文件路径
```

## 示例

### 2026-03-25 修复数据同步路径问题

**类别**: best_practice

**发生了什么**: 
sync-futu-account.py使用相对路径导致cron执行失败

**应该怎么做**:
使用绝对路径: `os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')`

**相关文件**:
- strategy/sync-futu-account.py

