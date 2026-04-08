# 自我优化机制

## 🎯 优化原则

1. **主动优化**：不需要等待指令，主动发现问题和改进点
2. **提前沟通**：优化方案先跟用户确认，不擅自行动
3. **记录过程**：每次优化都要记录到 `memory/optimization-log.md`
4. **保存版本**：优化后的文件要保存，避免重复工作

---

## 📅 定期优化计划

### 港股优化（每日17:00 运行）

**触发条件**：港股收盘后1小时（16:00 + 1小时 = 17:00）

**执行流程**：
1. 通过OpenClaw获取港股策略数据（持仓、信号、评分）
2. 获取最新港股日报数据
3. 分析策略表现：
   - 持仓盈亏情况
   - 信号质量评分
   - 行业权重表现
   - 技术指标有效性
4. 生成优化方案（保存到 `data/hk-optimization-proposal.json`）
5. 发送优化方案到OpenClaw（飞书）
6. **等待用户确认**后才能执行

**用户确认方式**：
```
用户回复 "同意 001" → 执行方案001
用户回复 "同意 002" → 执行方案002
用户回复 "全部同意" → 执行所有方案
用户回复 "拒绝" → 不执行
```

---

### 美股优化（每日05:00 运行）

**触发条件**：美股收盘后1小时（美股16:00 EST = 北京时间次日05:00）

**执行流程**：
1. 通过OpenClaw获取美股策略数据（持仓、信号、评分）
2. 获取最新美股日报数据
3. 分析策略表现：
   - 持仓盈亏情况
   - 信号质量评分
   - 技术指标配置（MA/RSI/成交量/ATR）
   - 止损止盈执行情况
4. 生成优化方案（保存到 `data/us-optimization-proposal.json`）
5. 发送优化方案到OpenClaw（飞书）
6. **等待用户确认**后才能执行

**用户确认方式**：
```
用户回复 "同意 US001" → 执行方案US001
用户回复 "同意 US002" → 执行方案US002
用户回复 "全部同意" → 执行所有方案
用户回复 "拒绝" → 不执行
```

---

## 📋 优化系统文件

```
strategy/
├── hk-optimizer.py        # 港股自我优化系统
├── us-optimizer.py       # 美股自我优化系统
├── llm_analyzer.py       # LLM股票分析模块
```

## 🧠 LLM评分增强系统

### 方案确认
- **时机**：下单前分析（减少token消耗，更精准）
- **阈值**：基础评分 ≥ 70分时触发LLM分析
- **模型**：OpenClaw已配置的LLM（百度/火山引擎）

### 评分权重
- 基础评分（技术指标+四源新闻）：70%
- LLM分析：30%

### 执行流程
```
扫描股票 → 基础评分 → 基础评分≥70? 
    → 是：调用LLM分析 → 调整评分 
    → 否：跳过LLM分析
→ 最终评分 → 下单决策
```

### hk-optimizer.py 功能

```python
class HKOptimizer:
    def run():
        # 1. 获取数据
        - 港股策略配置 (hk-strategy-dynamic-v2.0.json)
        - 港股日报 (daily-reports/)
        - 交易数据 (data/trades.json)
        
        # 2. 分析
        - 持仓盈亏分析
        - 信号质量分析
        - 行业权重分析
        
        # 3. 生成方案
        - 止损调整
        - 信号优化
        - 行业权重调整
        
        # 4. 等待确认
        - 保存方案到 data/hk-optimization-proposal.json
        - 发送到OpenClaw
```

### us-optimizer.py 功能

```python
class USOptimizer:
    def run():
        # 1. 获取数据
        - 美股策略配置 (us-strategy-v1.6.json)
        - 美股日报 (daily-reports/)
        - 交易数据 (data/trades.json)
        
        # 2. 分析
        - 持仓盈亏分析
        - 信号质量分析
        - 技术指标配置检查
        
        # 3. 生成方案
        - 止损调整
        - 技术指标优化
        - 扫描器优化
        
        # 4. 等待确认
        - 保存方案到 data/us-optimization-proposal.json
        - 发送到OpenClaw
```

---

## 🔄 定时任务配置

```bash
# 港股优化：每天17:00（周一到周五）
0 17 * * 1-5 /home/admin/.openclaw/workspace-arashi/futu-venv/bin/python3 /home/admin/.openclaw/workspace-arashi/strategy/hk-optimizer.py >> /home/admin/.openclaw/workspace-arashi/logs/hk-optimizer.log 2>&1

# 美股优化：每天05:00（周二到周六）
0 5 * * 2-6 /home/admin/.openclaw/workspace-arashi/futu-venv/bin/python3 /home/admin/.openclaw/workspace-arashi/strategy/us-optimizer.py >> /home/admin/.openclaw/workspace-arashi/logs/us-optimizer.log 2>&1
```

---

## 📝 优化方案格式

### 港股方案示例
```json
{
  "id": "001",
  "category": "止损调整",
  "issue": "持仓 HK.09868 亏损-6.5%",
  "suggestion": "检查是否触发止损条件，考虑减仓",
  "priority": "高"
}
```

### 美股方案示例
```json
{
  "id": "US001",
  "category": "止损调整",
  "issue": "持仓 US.COP 亏损-5.25%",
  "suggestion": "检查是否触发止损条件",
  "priority": "高"
}
```

---

## ✅ 优化执行流程

```
定时触发 → 获取数据 → 分析 → 生成方案 → 发送确认 → 用户确认 → 执行 → 记录
```

1. **定时触发**：crontab每天定时运行
2. **获取数据**：读取配置文件、日报、交易数据
3. **分析**：检查持仓、信号、技术指标
4. **生成方案**：输出优化建议JSON
5. **发送确认**：通过OpenClaw发送消息
6. **用户确认**：等待用户回复"同意 XXX"
7. **执行**：用户确认后执行优化
8. **记录**：更新optimization-log.md

---

## 📊 监控指标

### 核心指标
| 指标 | 目标值 | 当前值 | 状态 |
|------|--------|--------|------|
| 港股平均收益 | ≥2% | +2.45% | ✅ |
| 美股平均收益 | ≥1.5% | +1.91% | ✅ |
| 港股胜率 | ≥60% | 100% | ✅ |
| 美股胜率 | ≥50% | 100% | ✅ |

### 触发优化条件
- 收益率低于目标值 → 立即优化
- 胜率低于50% → 立即优化
- 连续亏损3次 → 暂停交易，分析原因
- 信号数量过少 → 调整筛选条件

---

## 📝 优化记录格式

```markdown
## YYYY-MM-DD 优化记录

### 发现的问题
- 问题描述
- 影响范围

### 优化方案
- 方案内容
- 预期效果
- 风险评估

### 用户确认
- [ ] 用户已确认
- [ ] 用户未确认（暂不执行）

### 执行结果
- 优化前：XXX
- 优化后：XXX
- 效果评估：XXX

### 文件变更
- 文件1：XXX
- 文件2：XXX
```

---

*更新时间：2026-03-27*
