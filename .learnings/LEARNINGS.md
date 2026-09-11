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

## 2026-09-03 美股流动性限制应在第一层统一执行

**类别**: correction

**发生了什么**:
排查低流动性股票 ADXN 后，一度考虑把流动性限制继续传入自动下单仓位。用户明确要求改为在第一层直接过滤。

**应该怎么做**:
把历史流动性作为候选资格，在所有第一层备用行情路径汇总后、五源第二层之前统一过滤；不要在自动交易器重复增加同一套限制。

**相关文件**:
- strategy/us-scanner.py
- strategy/test_us_liquidity_filter.py
