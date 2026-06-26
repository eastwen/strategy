# Stock 自动交易系统使用文档

> 版本: v2.2 (四源共振真实评分 + LLM 推理模型修复)  
> 最后更新: 2026-06-26

## 🆕 v2.2 变更摘要 (2026-06-25 ~ 06-26)

- **四源共振真实评分模块 v1.0** (`strategy/four_source_scorer.py`)
  - 公告维度：新增 `_announce_news_event`，识别财报 beat / 重大利好(+15) / 重大利空(-10)
  - 社区维度：美股新增 `_us_public_attention`（Yahoo Finance / Google News / Finnhub），不再只查中文源
  - 新闻维度：news.db 免底关键词正面情绪 +5
- **LLM 推理模型 token 修复** (`strategy/llm_stock_analyzer.py`)
  - 推理模型 (deepseek-v4-pro 等) 自动抬到 800 tokens
  - `content` 空时从 `reasoning_content` 末尾抽答案，避免误判为调用失败
- **门槛分级**：交易时段 `min_score=80` 自动下单 / 非交易时段 `opp_alert_score=90` 仅推送
- **验证案例 MU**：51 → 83 (news 27 / ann 15 / com 20 / inst 24 - LLM 3)

---

## 📋 目录

1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [核心模块](#核心模块)
4. [配置说明](#配置说明)
5. [运行方式](#运行方式)
6. [定时任务](#定时任务)
7. [数据文件](#数据文件)
8. [常见问题](#常见问题)

---

## 系统概述

Stock 是一个基于 **四源共振** 策略的自动交易系统，支持港股和美股市场。

### 核心特性

- 🔄 **自动交易** - 策略触发自动买卖
- 📊 **四源共振** - 国际资讯、监管公告、国内社区、海外社交
- 🧠 **LLM增强** - 智能评分和预测
- 📰 **新闻情绪** - 实时新闻采集和情绪分析
- 📈 **技术分析** - MA、RSI、ATR等指标
- 🛡️ **风险管理** - 自动止损止盈
- 📱 **飞书通知** - 交易信号实时推送

### 支持市场

| 市场 | 账户 | 策略版本 |
|------|------|----------|
| 🇭🇰 港股 | 15270899 (CASH) | v2.1 + 四源共振 v1.0 |
| 🇺🇸 美股 | 15270898 (MARGIN) | v1.7 + 四源共振 v1.0 + LLM 修复 |

---

## 快速开始

### 前置要求

1. **Futu OpenD** - 必须运行在 `127.0.0.1:11111`
2. **Python 3.14** - 使用 `futu-venv` 虚拟环境
3. **API密钥** - 配置在 `strategy/.api-keys.json`

### 启动系统

```bash
# 1. 启动Futu OpenD（如果未运行）
# 在Futu客户端中启动OpenD

# 2. 测试连接
/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/auto-trader.py

# 3. 启动守护进程
/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/auto-trader.py --daemon
```

### 查看日志

```bash
# 自动交易日志
tail -f /home/admin/.openclaw/workspace-stock/logs/auto-trader.log

# 新闻采集日志
tail -f /home/admin/.openclaw/workspace-stock/logs/news-pipeline.log

# 日报日志
tail -f /home/admin/.openclaw/workspace-stock/logs/hk-daily.log
```

---

## 核心模块

### 1. 自动交易 (`auto-trader.py`)

**功能**: 自动扫描、评分、买卖、止损止盈

**运行方式**:
```bash
# 单次运行（测试）
python3 auto-trader.py

# 守护进程模式
python3 auto-trader.py --daemon
```

**核心流程**:
```
1. 检查交易时间
2. 获取账户信息
3. 检查止损/止盈
4. 获取机会列表
5. 筛选高评分股票
6. 检查技术指标
7. 执行交易
8. 发送飞书通知
```

---

### 2. 新闻采集 (`news_pipeline.py`)

**功能**: 全市场新闻采集 + 情绪分析

**数据源**:
| 来源 | 类型 | 数量 |
|------|------|------|
| Finnhub | 美股资讯 | 20条 |
| Yahoo Finance | 财经新闻 | 14条 |
| 东方财富 | A股/港股 | 20条 |
| 新浪财经 | A股/港股 | 20条 |
| 港交所 | 港股公告 | 8条 |
| SEC EDGAR | 持仓公告 | 按需 |

**运行方式**:
```bash
# 单次运行
python3 news_pipeline.py

# 定时任务模式
python3 news_pipeline.py --cron
```

**数据存储**: `data/news/news.db`

---

### 3. 港股扫描器 (`hk-scanner.py`)

**功能**: 港股四源共振扫描

**策略**: v2.1 新闻增强版

**核心规则**:
- 四源共振：国际资讯(30%) + 港股公告(20%) + 国内社区(25%) + 海外社交(25%)
- 开仓条件：评分≥70分，MA20>MA50，成交量≥1.5x，RSI 20-80
- 仓位控制：2-5% 单票，最多10只
- 止损：浮亏≥6% 强制止损
- 止盈：收益≥15% 分批止盈

---

### 4. 美股扫描器 (`us-scanner.py`)

**功能**: 美股四源共振扫描

**策略**: v1.7 LLM增强版

**核心规则**:
- 四源共振：国际资讯(35%) + 监管公告(20%) + 国内社区(25%) + 海外社交(20%)
- LLM分析：基础评分≥70触发
- 严格择时：MA20>MA50，技术信号≥2，成交量≥1.8x，RSI<65
- 仓位控制：12% 单票，总仓位≤40%
- 止损：ATR动态止损(1.8-2.0x)，浮亏≥6% 强制止损
- 止盈：ATR动态止盈(4.0-4.5x)，最大持仓6天

---

### 5. 日报生成器 (`daily-report-to-feishu.py`)

**功能**: 生成日报并上传飞书Wiki

**日报内容**:
1. 账户核心数据
2. 当前持仓明细
3. 本日策略收益
4. 当前策略说明
5. 当日交易记录
6. 核心新闻与市场分析
7. 财报与业绩预测
8. 风险提示与操作建议

**运行方式**:
```bash
# 港股日报
python3 daily-report-to-feishu.py

# 美股日报
python3 daily-report-to-feishu.py --us
```

**飞书Wiki**: https://www.feishu.cn/wiki/FkKBwRmOuimBJvkBFVkcSWBbnwc

---

## 配置说明

### API密钥配置 (`strategy/.api-keys.json`)

```json
{
  "tushare": {
    "api_key": "xxx",
    "description": "A股/港股行情和基本面数据"
  },
  "finnhub": {
    "api_key": "xxx",
    "description": "美股实时行情、新闻、舆情数据"
  },
  "alphavantage": {
    "api_key": "xxx",
    "description": "美股技术数据"
  },
  "feishu": {
    "appId": "cli_xxx",
    "appSecret": "xxx"
  }
}
```

### 策略配置

**港股策略** (`config/hk-strategy.json`):
```json
{
  "version": "2.1",
  "min_score": 70,
  "position_size": 0.03,
  "max_positions": 10,
  "stop_loss_pct": 0.06,
  "take_profit_pct": 0.15
}
```

**美股策略** (`config/us-strategy.json`):
```json
{
  "version": "1.7",
  "min_score": 70,
  "position_size": 0.12,
  "max_positions": 8,
  "stop_loss_atr": 1.8,
  "take_profit_atr": 4.0,
  "max_holding_days": 6
}
```

### 交易时间配置

**港股** (已在 `strategy/auto-trader.py` 中硬编码)：
- 交易时间: 09:30-16:00
- 午休: 12:00-13:00

**美股** (已在 `strategy/auto-trader.py` 中硬编码)：
- 盘前: 04:00-09:30
- 盘中: 09:30-16:00
- 盘后: 16:00-20:00

---

## 运行方式

### 单次运行（测试）

```bash
# 测试自动交易
python3 auto-trader.py

# 测试港股扫描
python3 hk-scanner.py

# 测试美股扫描
python3 us-scanner.py

# 测试新闻采集
python3 news_pipeline.py

# 测试日报生成
python3 daily-report-to-feishu.py
```

### 守护进程模式

```bash
# 启动自动交易守护进程
nohup python3 auto-trader.py --daemon >> logs/auto-trader.log 2>&1 &

# 查看进程
ps aux | grep auto-trader

# 停止进程
pkill -f "auto-trader.py"
```

### 使用cron定时任务

当前cron配置:
```bash
# 港股扫描 (每分钟)
*/15 9-16 * * 1-5 python3 hk-scanner.py

# 美股扫描 (每10分钟)
*/10 21-4 * * 2-6 python3 us-scanner.py

# 新闻采集 (每分钟)
*/1 * * * * python3 news_pipeline.py --cron

# 港股日报 (16:10)
10 16 * * 1-5 python3 daily-report-to-feishu.py

# 美股日报 (04:30)
30 4 * * 2-6 python3 daily-report-to-feishu.py --us
```

---

## 定时任务

### 查看定时任务

```bash
crontab -l
```

### 编辑定时任务

```bash
crontab -e
```

### 定时任务列表

| 任务 | 时间 | 频率 |
|------|------|------|
| 港股扫描 | 09:00-16:00 | 每15分钟 |
| 美股扫描 | 21:00-04:00 | 每10分钟 |
| 新闻采集 | 全天 | 每分钟 |
| 港股日报 | 16:10 | 周一到周五 |
| 美股日报 | 04:30 | 周二到周六 |
| 港股优化 | 17:00 | 周一到周五 |
| 美股优化 | 05:00 | 周二到周六 |
| 周报生成 | 15:00 | 周六 |
| 月报生成 | 16:10 | 月末 |
| 心跳检查 | 全天 | 每3分钟 |

---

## 数据文件

### 数据目录结构

```
data/
├── news/
│   └── news.db              # 新闻数据库 (SQLite)
├── trades.json              # 交易数据
├── closed-trades.json       # 已平仓交易
├── open-positions.json      # 当前持仓
├── hk-opportunities.json    # 港股机会
├── us-opportunities.json    # 美股机会
└── alerts.json              # 预警数据
```

### 主要数据文件

**trades.json** - 交易数据:
```json
{
  "accounts": [
    {
      "acc_id": "15270898",
      "total_asset": 1014402.82,
      "cash": -806834.45,
      "positions": [...]
    }
  ]
}
```

**closed-trades.json** - 已平仓交易:
```json
{
  "trades": [
    {
      "symbol": "US.TTD",
      "action": "SELL",
      "quantity": 5340,
      "price": 20.70,
      "pnl": -4561.80,
      "timestamp": "2026-04-08T22:43:41"
    }
  ]
}
```

---

## 常见问题

### 1. Futu OpenD 连接失败

**错误**: `ERROR. No one available account!`

**解决方案**:
1. 检查Futu客户端是否运行
2. 检查OpenD是否启动 (127.0.0.1:11111)
3. 重新登录Futu账户
4. 重启OpenD

### 2. 新闻采集失败

**错误**: `获取新闻失败`

**解决方案**:
1. 检查API密钥是否有效
2. 检查网络连接
3. 查看日志: `tail -f logs/news-pipeline.log`

### 3. 港股整手交易失败

**错误**: `下单失败: 碎股`

**原因**: 港股需要整手交易

**解决方案**: 系统已自动处理，根据股票代码调整数量

### 4. 止损未执行

**可能原因**:
1. 不在交易时间
2. Futu账户未登录
3. API频率限制

**检查**:
```bash
# 查看日志
tail -f logs/auto-trader.log | grep "止损"

# 检查进程
ps aux | grep auto-trader
```

### 5. 日报未生成

**检查**:
```bash
# 查看cron日志
grep CRON /var/log/syslog | tail -20

# 手动运行测试
python3 daily-report-to-feishu.py
```

---

## 维护命令

### 查看系统状态

```bash
# 查看所有进程
ps aux | grep -E "auto-trader|scanner|news_pipeline"

# 查看日志大小
du -sh logs/*.log

# 查看数据库大小
du -sh data/news/news.db
```

### 清理日志

```bash
# 清理7天前的日志
find logs/ -name "*.log" -mtime +7 -delete

# 清理新闻数据库（保留15天）
sqlite3 data/news/news.db "DELETE FROM news WHERE timestamp < date('now', '-15 days');"
```

### 备份数据

```bash
# 备份数据
tar -czf backup_$(date +%Y%m%d).tar.gz data/ config/

# 备份日报
tar -czf reports_$(date +%Y%m%d).tar.gz daily-reports/
```

---

## 技术支持

- **文档位置**: `/home/admin/.openclaw/workspace-stock/README.md`
- **日志位置**: `/home/admin/.openclaw/workspace-stock/logs/`
- **配置位置**: `/home/admin/.openclaw/workspace-stock/config/`
- **策略位置**: `/home/admin/.openclaw/workspace-stock/strategy/`

---

**Stock 自动交易系统** - 让数据驱动交易决策 🚀
