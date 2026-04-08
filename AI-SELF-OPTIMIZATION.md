# AI主动自我优化系统

## 🎯 系统概述

这个系统让OpenClaw能够**主动**发现自身问题并提出优化方案，**等待你确认**后才执行。

## 🔄 工作流程

```
AI发现问题 → 生成优化方案 → 发送飞书通知 → 等待你确认 → 执行优化
```

## 📋 监控内容

### 1. 文件健康
- 大文件检测 (>10MB)
- 日志错误分析
- 关键文件完整性

### 2. 策略表现
- 胜率监控 (<50%告警)
- 回撤监控 (>-6%告警)
- 连续亏损检测

### 3. 系统状态
- 记忆文件整理
- 资源使用情况
- 系统健康检查

## 🚀 使用方法

### 自动运行（定时任务）
```bash
# 每天自动检查
crontab -e
# 添加: 0 9 * * * python3 ai-self-optimizer.py
```

### 手动运行
```bash
# 运行自我检查
cd /home/admin/.openclaw/workspace-arashi
python3 ai-self-optimizer.py

# 查看待处理问题
python3 ai-self-optimizer.py list

# 执行特定优化
python3 ai-self-optimizer.py apply <issue_id>
```

## 📱 飞书通知示例

```
🚨 AI自我优化报告

港股策略胜率过低

问题描述:
港股策略胜率 45%，低于50%阈值

详情:
{
  "win_rate": 0.45,
  "total_trades": 20,
  "total_return": -0.02
}

建议优化方案:
1. 提高港股评分阈值
2. 增加技术确认条件
3. 调整止损止盈参数
4. 优化选股标准

预计影响:
- 修复后系统稳定性提升
- 减少潜在错误
- 优化资源使用

请回复以下指令之一:
- 确认 OPT-20240324-001 - 执行优化
- 忽略 OPT-20240324-001 - 跳过此问题
- 查看详情 OPT-20240324-001 - 了解更多信息
```

## 📁 文件位置

- **主程序**: `ai-self-optimizer.py`
- **状态文件**: `data/ai_self_opt_state.json`
- **待处理问题**: `data/ai_pending_issues.json`
- **优化日志**: `memory/ai-optimization-log.md`

## ⚙️ 配置阈值

在 `ai-self-optimizer.py` 中修改:

```python
self.thresholds = {
    'max_file_size_mb': 10,      # 大文件阈值(MB)
    'min_win_rate': 0.50,        # 最低胜率
    'max_drawdown': -0.06,       # 最大回撤
    'max_consecutive_losses': 3, # 最大连续亏损
}
```

## 🎛️ 指令说明

| 指令 | 说明 |
|------|------|
| `确认 <issue_id>` | 执行该问题的优化方案 |
| `忽略 <issue_id>` | 跳过此问题，不再提醒 |
| `查看详情 <issue_id>` | 获取该问题的详细信息 |

## 📝 优化记录

所有优化都会被记录到 `memory/ai-optimization-log.md`:
- 发现的问题
- 应用的优化
- 执行时间
- 优化效果

## 🎓 设计理念

**主动但不越权**:
- ✅ 主动发现问题
- ✅ 提出优化方案
- ✅ 详细说明影响
- ❌ 不擅自执行（需你确认）

这样可以确保:
1. 你不会错过重要问题
2. 你始终掌握决策权
3. 优化过程透明可控
