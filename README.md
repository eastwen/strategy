# Stock 自动交易系统

> 版本: v2.5 (五源共振 + 动态仓位风控 + 股票池周更)
> 最后更新: 2026-07-29

## 🆙 v2.5 变更摘要 (2026-07-29)

- **五源共振评分系统** (`four_source_scorer.py`) — 新增资金异动维度（10分），总分100分重新分配权重：资讯25 / 公告20 / 社区25 / 机构20 / 资金10
- **LLM 推理模型适配** (`llm_stock_analyzer.py`) — 自动检测 `reasoning_content`，max_tokens 动态调整；推理模型自动抬到 800 tokens，content 空时从 reasoning_content 末尾抽答案
- **飞书推送增强** (`feishu-pusher.py`) — 买卖通知含五源分数 + 资金方向 + 社区多空比；机会推送含完整五源分解
- **富途社区接入** — `news_type=1/2/3` 覆盖新闻/公告/研报，comment sentiment 合成社区情绪
- **统一配置管理** (`runtime_config.py`) — 路径、API密钥、运行时参数集中管理，支持环境变量覆盖
- **系统启动检查** (`system-preflight.py`) — 启动前环境验证（路径、密钥、状态文件、数据库、模块导入、Futu连接）
- **门槛分级** — 交易时段 `min_score=75` 自动下单 / 美股非交易时段 `opp_alert_score=85` 仅推送
- **股票池周更** — 港股每周日08:00更新恒指+恒科；美股08:15更新标普500+NASDAQ，多源核对补漏并按代码去重

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
9. [维护命令](#维护命令)

---

## 系统概述

Stock 是一个基于 **五源共振** 策略的自动交易系统，支持港股和美股市场。

### 核心特性

- 🔄 **自动交易** — 策略触发自动买卖，含 ATR 动态止损止盈、分批止盈、持仓天数控制
- 📊 **五源共振** — 国际资讯、官方公告、社区情绪、机构观点、资金异动五维独立评分
- 🧠 **LLM 增强** — 多模型 fallback 链（主模型 + 7个备用），支持推理模型 `reasoning_content`
- 📰 **新闻管道** — 全市场新闻采集 + SQLite 存储 + 情绪分析 + 股票关联
- 📈 **技术分析** — MA/RSI/MACD/ATR/布林带，美股用 yfinance、港股用 Futu/LongBridge
- 🛡️ **风险管理** — ATR 动态止损、分批减仓、每日/每周亏损限制
- 📱 **飞书通知** — 交易信号、机会推送、日报/周报/月报上传飞书 Wiki
- 💓 **心跳检查** — 每3分钟检查系统状态、机会数量、数据同步
- 🔧 **自我优化** — 港股/美股优化器每日分析策略表现并生成调参建议

### 支持市场

| 市场 | 账户 | 策略版本 | 扫描范围 |
|------|------|----------|----------|
| 🇭🇰 港股 | 15270899 (CASH) | v2.2 | 恒生指数 + 恒生科技指数（当前104只） |
| 🇺🇸 美股 | 15270898 (MARGIN) | v1.7 | 标普500 + NASDAQ上市非ETF（当前4639只） |

---

## 快速开始

### 前置要求

1. **Futu OpenD** — 运行在 `127.0.0.1:11111`，富途客户端需登录
2. **Python 3.14** — 使用 `futu-venv` 虚拟环境
3. **API 密钥** — 配置在 `strategy/.api-keys.json`
4. **依赖锁定** — `pip install -r strategy/requirements.lock`

### 目录结构

```
workspace-stock/
├── strategy/              # 策略代码（所有 .py 脚本）
│   ├── .api-keys.json     # API 密钥（不提交版本控制）
│   ├── .env.example       # 环境变量示例
│   ├── cron-tasks.txt     # 定时任务配置说明
│   ├── requirements.lock  # Python 依赖锁定
│   └── *.py               # 所有策略脚本
├── config/                # 策略配置 JSON
│   ├── hk-strategy.json   # 港股策略配置
│   ├── us-strategy.json   # 美股策略配置
│   ├── report-template.md # 日报模板
│   └── strategy-config.md # 策略说明文档
├── data/                  # 运行时数据
│   ├── news/news.db       # 新闻数据库 (SQLite)
│   ├── trades.json        # 账户/持仓数据
│   ├── open-positions.json # 当前持仓
│   ├── closed-trades.json  # 已平仓交易
│   ├── us-opportunities.json # 美股机会列表
│   ├── hk-opportunities.json # 港股机会列表
│   └── ...
├── logs/                  # 日志文件
├── daily-reports/         # 日报输出
├── runtime/               # 运行时状态
└── futu-venv/             # Python 虚拟环境
```

### 启动系统

```bash
# 1. 环境检查
/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/system-preflight.py --futu

# 2. 同步账户数据
/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/sync-futu-account.py

# 3. 测试自动交易（单次）
/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/auto-trader.py

# 4. 启动守护进程
nohup /home/admin/.openclaw/workspace-stock/futu-venv/bin/python3 \
  /home/admin/.openclaw/workspace-stock/strategy/auto-trader.py --daemon \
  >> /home/admin/.openclaw/workspace-stock/logs/auto-trader.log 2>&1 &
```

---

## 核心模块

### 1. 自动交易 (`auto-trader.py`)

**功能**: 自动扫描、评分、买卖、止损止盈、分批减仓

**核心流程**:
```
1. 检查交易时间（trading_calendar.py 判断交易日/时段）
2. 获取账户信息和持仓
3. 检查止损/止盈（ATR 动态 + 固定比例）
4. 获取机会列表（us-scanner / hk-scanner）
5. 五源共振评分（four_source_scorer.py）
6. 筛选高评分股票（交易时段≥75分下单 / 美股非交易时段≥85分推送）
7. 技术指标检查（technical_indicators_us/hk.py）
8. 执行交易（整手处理、仓位控制）
9. 发送飞书通知（feishu-pusher.py）
```

**运行方式**:
```bash
python3 auto-trader.py          # 单次运行（测试）
python3 auto-trader.py --daemon # 守护进程模式
```

### 2. 五源共振评分 (`four_source_scorer.py`)

**版本**: v1.4 — 五个维度独立采集数据，零硬拆

| 维度 | 美股权重 | 港股权重 | 数据源 |
|------|---------|---------|--------|
| 国际资讯 | 25 | 25 | Finnhub / AlphaVantage / yfinance / TinkClaw / 富途新闻 |
| 官方公告 | 20 | 20 | SEC EDGAR / 港交所公告 / 富途研报 |
| 社区情绪 | 25 | 25 | 富途讨论区 / 雪球 / 新浪 / Reddit |
| 机构观点 | 20 | 20 | 研报评级 / 分析师目标价 |
| 资金异动 | 10 | 10 | 大单资金流向 / 主力净流入 |

**缓存机制**: 慢变数据缓存在 `news.db` 的 `five_source_cache` 表，避免重复 API 调用。

### 3. 美股扫描器 (`us-scanner.py`)

**版本**: v2.5 — 扫描标普500 + NASDAQ上市非ETF（当前4639只）

**数据源优先级**: Finnhub (主) → AlphaVantage (备) → yfinance → TinkClaw → LongBridge → Futu

**核心规则**:
- 五源共振评分（资讯、公告、社区、机构、资金）
- LLM 分析：基础评分≥70触发，多模型 fallback
- 严格择时：MA20>MA50，技术信号≥2，成交量≥1.8x，RSI<65
- 仓位控制：单票 12%，总仓位≤40%
- 止损：ATR 1.8-2.0x / 浮亏≥6% 强制止损
- 止盈：ATR 4.0-4.5x / 最大持仓6天

### 4. 港股扫描器 (`hk-scanner.py`)

**版本**: v2.5 — 扫描恒生指数 + 恒生科技指数（当前104只）

**数据源**: Futu OpenD (主) / Tushare (备)

**核心规则**:
- 五源共振评分
- 开仓条件：评分≥70，MA20>MA50，成交量≥1.5x，RSI 40-65
- 仓位控制：单票 2-5%，最多10只
- 止损：ATR 1.5x / 浮亏≥6% 强制止损
- 止盈：ATR 3.0x / RSI>65 / 最大持仓10天

### 5. LLM 分析 (`llm_stock_analyzer.py`)

**功能**: 候选股票深度分析 + 日报/周报市场分析

**模型配置** (改文件顶部常量即可切换):
- 主模型: `xophunyuan7bmt`（讯飞星火平台）
- 备用链: `xop35qwen2b` → `xop3qwen1b7` → `qwen3.6-35b-a3b` → `qwen3.5-plus` → `glm-5.1` → `kimi-k2.6`
- 推理模型适配: 自动检测 `reasoning_content`，`max_tokens` 动态调整到 800
- 环境变量覆盖: `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`

### 6. 新闻管道 (`news_pipeline.py`)

**功能**: 全市场新闻采集 + SQLite 存储 + 情绪分析 + 股票关联

**数据源**:

| 来源 | 类型 | 覆盖市场 |
|------|------|----------|
| Finnhub | 美股资讯 | 美股 |
| Yahoo Finance | 财经新闻 | 全球 |
| 东方财富 | A股/港股 | 港股 |
| 新浪财经 | A股/港股 | 港股 |
| 富途新闻 API | 新闻/公告/研报 | 港股+美股 |
| SEC EDGAR | 持仓公告 | 美股 |

**数据库**: `data/news/news.db`，含 `news`、`stock_mentions`、`five_source_cache` 表

**运行方式**:
```bash
python3 news_pipeline.py          # 单次采集
python3 news_pipeline.py --cron   # cron 模式（静默）
```

### 7. 飞书推送 (`feishu-pusher.py`)

**功能**: 交易信号、机会推送、日报链接发送到飞书群聊

**推送内容**:
- 买入/卖出通知：五源分数 + 资金方向 + 社区多空比
- 机会推送：完整五源分解 + 技术指标
- 日报/周报/月报：飞书 Wiki 链接

### 8. 日报生成 (`daily-report-to-feishu.py`)

**功能**: 生成综合日报并上传飞书 Wiki

**日报内容**: 账户核心数据 → 持仓明细 → 策略收益 → 策略说明 → 交易记录 → 核心新闻分析 → 财报预测 → 风险提示

**运行方式**:
```bash
python3 daily-report-to-feishu.py          # 港股日报
python3 daily-report-to-feishu.py --us     # 美股日报
```

**飞书 Wiki**: https://www.feishu.cn/wiki/FkKBwRmOuimBJvkBFVkcSWBbnwc

### 9. 市场情绪监控

**美股** (`us_market_sentiment.py`):
- VIX 恐慌指数 (Yahoo Finance ^VIX)
- CNN 恐慌贪婪指数 (CNN API 真数据)
- 期权 Put/Call 比例 (SPX/QQQ/SPY 期权链)
- SPX/NDX/DJI 指数涨跌
- 综合评分: VIX 30% + FG 25% + PCR 25% + SPX 20%

**港股** (`hk_market_sentiment.py`):
- VHSI 恒指波幅指数 (Futu HK.800125)
- 港股通资金流向
- 牛熊证比例

### 10. 技术指标 (`technical_indicators_us.py` / `technical_indicators_hk.py`)

**美股**: yfinance K线数据，MA/RSI/MACD/ATR/成交量分析
**港股**: LongBridge (主) / Futu (备) K线数据，MA/RSI/ATR/布林带

### 11. 交易日历 (`trading_calendar.py`)

**版本**: v3.0 — 自动夏令时/冬令时

- 港股：按北京时间判断，含2026年港股节假日
- 美股：按美东时间判断，自动夏令时/冬令时切换

### 12. 策略优化 (`us-optimizer.py` / `hk-optimizer.py`)

**版本**: v2.0 — 每日收盘后分析策略表现

- 持仓分析：盈亏、持仓天数、信号质量
- 市场环境分析：VIX/ATR/趋势
- 生成调参建议（写入 `data/*-optimization-proposal.json`）

### 13. 心跳检查 (`heartbeat-check.py`)

**版本**: v1.0 — 每3分钟执行

- 检查待发日报、交易机会、交易状态
- 静默模式：正常不输出日志
- 高评分机会≥8个时输出提醒

### 14. 账户同步 (`sync-futu-account.py`)

**功能**: 从 Futu OpenD 获取真实账户和持仓数据，同步到 `trades.json`

**数据内容**: 账户总资产、现金、持仓市值、持仓明细（代码/数量/成本/盈亏）

### 15. 系统检查 (`system-preflight.py`)

**功能**: 只读环境验证，迁移/启动前检查

**检查项**: 目录结构 → 密钥配置 → 状态文件 → 新闻数据库 → 模块导入 → Futu 连接

```bash
python3 system-preflight.py --futu       # 含 Futu 连接检查
python3 system-preflight.py --manifest   # 打印迁移文件清单
```

### 16. 其他模块

| 模块 | 说明 |
|------|------|
| `vix_fetcher.py` | VIX 恐慌指数获取（yfinance + AlphaVantage 备用） |
| `fear_greed_index.py` | CNN 恐慌贪婪指数获取器 |
| `generate-weekly-report.py` | 周报生成器 v3.0，含 LLM 下周操作建议 |
| `generate-monthly-report.py` | 月报生成器 v2.0，收益归因分析 |
| `news_integration.py` | 新闻与交易策略整合，机会评分更新 |
| `earnings-forecast-module.py` | 财报预测模块 |
| `sentiment-3day-predictor.py` | 3日情绪预测 |
| `trading_calendar.py` | 交易日历（港股/美股，自动夏令时） |
| `get-constituents.py` | 获取港股成分股 |
| `get-us-constituents.py` | 获取美股成分股 |
| `update-heartbeat-status.py` | 更新心跳状态文件 |
| `add_file_locks.py` | 文件锁工具 |
| `recompute_sentiment.py` | 重新计算新闻情绪 |

---

## 配置说明

### 统一路径管理 (`runtime_config.py`)

所有路径通过 `runtime_config.py` 集中管理，支持环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `STOCK_HOME` | `strategy/` 的父目录 | 工作区根目录 |
| `STOCK_DATA_DIR` | `$STOCK_HOME/data` | 数据目录 |
| `STOCK_CONFIG_DIR` | `$STOCK_HOME/config` | 配置目录 |
| `STOCK_LOG_DIR` | `$STOCK_HOME/logs` | 日志目录 |
| `STOCK_REPORTS_DIR` | `$STOCK_HOME/daily-reports` | 报告输出 |
| `STOCK_API_KEYS_FILE` | `strategy/.api-keys.json` | API 密钥文件 |
| `STOCK_PYTHON` | 当前 Python | Python 解释器路径 |
| `FUTU_HOST` | `127.0.0.1` | Futu OpenD 地址 |
| `FUTU_PORT` | `11111` | Futu OpenD 端口 |
| `FUTU_OPEND_BIN` | `~/Futu_OpenD_.../FutuOpenD` | OpenD 二进制路径 |
| `LLM_BASE_URL` | 讯飞星火 API | LLM API 地址 |
| `LLM_API_KEY` | 从 `.api-keys.json` | LLM API 密钥 |
| `LLM_MODEL` | `xophunyuan7bmt` | LLM 模型名 |

### API 密钥 (`strategy/.api-keys.json`)

```json
{
  "tushare":   { "api_key": "xxx" },
  "finnhub":   { "api_key": "xxx" },
  "alphavantage": { "api_key": "xxx" },
  "feishu":    { "appId": "cli_xxx", "appSecret": "xxx", "chatId": "oc_xxx" },
  "llm":       { "api_key": "xxx", "base_url": "https://...", "model": "xxx" },
  "futu":      { "trade_password": "xxx" }
}
```

### 环境变量示例 (`.env.example`)

```bash
STOCK_HOME=/opt/workspace-stock
STOCK_API_KEYS_FILE=/opt/workspace-stock/strategy/.api-keys.json
STOCK_PYTHON=/opt/workspace-stock/futu-venv/bin/python3
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
FUTU_OPEND_BIN=/opt/FutuOpenD/FutuOpenD
OPENCLAW_HOME=/home/your-user/.openclaw
```

### 策略配置

**港股** (`config/hk-strategy.json`): v2.2（统一版本源：`strategy/runtime_config.py`）
- 入场: MA20上升趋势 + 价格>MA20 + RSI 40-65 + 成交量≥1.5x
- 出场: ATR 1.5x止损 / ATR 3.0x止盈 / RSI>65 / 最大持仓10天
- 仓位: 基础3%，按行业权重调整

**美股** (`config/us-strategy.json`): v1.7（统一版本源：`strategy/runtime_config.py`）
- 入场: MA20>MA50 + 技术信号≥2 + 成交量≥1.8x + RSI<65 + LLM评分≥65
- 出场: ATR 1.8-2.0x止损 / ATR 4.0-4.5x止盈 / RSI>70 / MACD死叉 / 最大持仓6天
- 仓位: 单票12%，总仓位≤40%
- 风控: 日亏≤2% / 周亏≤5% / 行业暴露≤30%

### 交易时间

**港股** (北京时间):
- 交易时段: 09:30-12:00, 13:00-16:00
- 预扫描: 08:50

**美股** (美东时间，自动夏令时):
- 盘中: 09:30-16:00 (北京时间 21:00-04:00 / 22:00-05:00)
- cron 按北京时间调度，节假日由 `trading_calendar.py` 内部过滤

---

## 运行方式

### 单次运行（测试）

```bash
cd /home/admin/.openclaw/workspace-stock
PYTHON=futu-venv/bin/python3

# 环境检查
$PYTHON strategy/system-preflight.py --futu

# 账户同步
$PYTHON strategy/sync-futu-account.py

# 自动交易（单次）
$PYTHON strategy/auto-trader.py

# 扫描器
$PYTHON strategy/hk-scanner.py
$PYTHON strategy/us-scanner.py

# 新闻采集
$PYTHON strategy/news_pipeline.py

# 日报
$PYTHON strategy/daily-report-to-feishu.py
$PYTHON strategy/daily-report-to-feishu.py --us

# 周报/月报
$PYTHON strategy/generate-weekly-report.py
$PYTHON strategy/generate-monthly-report.py

# 策略优化
$PYTHON strategy/hk-optimizer.py
$PYTHON strategy/us-optimizer.py
```

### 守护进程模式

```bash
nohup futu-venv/bin/python3 strategy/auto-trader.py --daemon \
  >> logs/auto-trader.log 2>&1 &

# 查看进程
ps aux | grep auto-trader

# 停止
pkill -f "auto-trader.py"
```

---

## 定时任务

实际 crontab 配置（关键任务）：

| 任务 | cron 表达式 | 说明 |
|------|------------|------|
| 港股扫描 | `50 8 * * 1-5` + `*/5 10-11,13-15 * * 1-5` 等 | 8:50预扫描，交易时段每5分钟 |
| 港股日报 | `10 16 * * 1-5` | 周一到周五 16:10 |
| 港股优化 | `0 17 * * 1-5` | 周一到周五 17:00 |
| 美股自动交易 | `*/5 0-7 * * 2-6` + `*/5 21-23 * * 1-5` 等 | 交易时段每5分钟 |
| 美股扫描 | `0 * * * 1-6` | 每小时 |
| 美股日报 | `30 4 * * 2-6` | 周二到周六 04:30 |
| 美股优化 | `0 5 * * 2-6` | 周二到周六 05:00 |
| 账户同步 | `*/10 * * * *` | 每10分钟 |
| 新闻采集 | `*/1 * * * *` | 每1分钟 |
| 心跳检查 | `*/3 * * * *` | 每3分钟 |
| 周报 | `0 15 * * 6` | 周六 15:00 |
| 月报 | `10 16 28-31 * *` (月末检查) | 月末 16:10 |

**所有任务均使用** `flock -n` 文件锁防止并发，`timeout` 限制运行时长。

### 管理定时任务

```bash
crontab -l | grep workspace-stock    # 查看当前任务
crontab -e                            # 编辑
```

---

## 数据文件

### 运行时数据 (`data/`)

| 文件 | 说明 |
|------|------|
| `trades.json` | 账户信息 + 持仓明细（由 sync-futu-account.py 同步） |
| `open-positions.json` | 当前持仓记录（含入场评分、原因、风控价位） |
| `closed-trades.json` | 已平仓交易历史 |
| `staged-reductions.json` | 分批减仓计划 |
| `us-opportunities.json` | 美股机会列表（扫描器输出） |
| `hk-opportunities.json` | 港股机会列表 |
| `alerts.json` | 预警数据 |
| `notify-cooldowns.json` | 通知冷却（防重复推送） |
| `weekly-history.json` | 周报历史数据 |
| `*-optimization-proposal.json` | 优化器调参建议 |
| `news/news.db` | 新闻数据库 (SQLite) |

### 新闻数据库结构

```sql
-- 新闻表
news (id, source, title, content, url, symbol, sentiment, timestamp)

-- 股票关联表
stock_mentions (id, news_id, symbol)

-- 五源缓存表
five_source_cache (cache_key, updated_at, payload)
```

---

## 常见问题

### 1. Futu OpenD 连接失败

**检查步骤**:
```bash
# 确认 OpenD 进程运行
ps aux | grep FutuOpenD

# 确认端口监听
ss -tlnp | grep 11111

# 运行系统检查
python3 strategy/system-preflight.py --futu
```

### 2. 新闻采集失败

**检查**:
```bash
tail -f logs/news-pipeline.log
sqlite3 data/news/news.db "SELECT COUNT(*) FROM news;"
```

### 3. 港股整手交易失败

港股需整手交易，系统已自动根据股票代码调整数量。如仍出错，检查 `auto-trader.py` 中整手计算逻辑。

### 4. 止损未执行

**可能原因**: 非交易时间 / Futu 未登录 / API 频率限制
```bash
tail -f logs/auto-trader.log | grep -E "止损|stop"
```

### 5. LLM 分析无响应

模型 fallback 链会自动切换。如全部失败，检查 `.api-keys.json` 中 `llm.api_key` 是否有效。

### 6. 迁移到新机器

```bash
# 1. 打包
tar -czf stock-backup.tar.gz strategy/ config/ data/ futu-venv/

# 2. 新机器解压后设置环境变量
cp strategy/.env.example strategy/.env  # 修改路径

# 3. 运行系统检查
python3 strategy/system-preflight.py --futu --manifest
```

---

## 维护命令

### 查看系统状态

```bash
# 进程
ps aux | grep -E "auto-trader|scanner|news_pipeline"

# 日志大小
du -sh logs/*.log

# 数据库大小
du -sh data/news/news.db

# 持仓概览
python3 -c "import json; d=json.load(open('data/open-positions.json')); print(f'{len(d)} positions')"

# 机会数量
python3 -c "import json; d=json.load(open('data/us-opportunities.json')); print(f'{len(d.get(\"opportunities\",[]))} US ops')"
```

### 清理

```bash
# 清理7天前日志
find logs/ -name "*.log" -mtime +7 -delete

# 清理新闻数据库（保留15天）
sqlite3 data/news/news.db "DELETE FROM news WHERE timestamp < datetime('now', '-15 days');"

# 清理备份文件
find data/ -name "*.bak.*" -mtime +30 -delete
```

### 备份

```bash
tar -czf backup_$(date +%Y%m%d).tar.gz data/ config/
tar -czf reports_$(date +%Y%m%d).tar.gz daily-reports/
```

---

## 依赖清单

核心依赖（`strategy/requirements.lock`）:

| 包 | 版本 | 用途 |
|----|------|------|
| futu_api | 10.8.6808 | 富途 OpenD API |
| yfinance | 1.2.0 | 美股行情/新闻 |
| tushare | 1.4.25 | A股/港股数据 |
| longbridge | 4.0.5 | LongBridge K线数据 |
| requests | 2.32.5 | HTTP 请求 |
| pandas | 3.0.1 | 数据处理 |
| numpy | 2.4.3 | 数值计算 |
| beautifulsoup4 | 4.14.3 | 网页解析 |
| sqlite3 | (内置) | 新闻数据库 |
| pytz | 2026.1.post1 | 时区处理 |
| matplotlib | 3.10.8 | 图表（可选） |

---

## 技术支持

- **代码位置**: `/home/admin/.openclaw/workspace-stock/strategy/`
- **配置位置**: `/home/admin/.openclaw/workspace-stock/config/`
- **数据位置**: `/home/admin/.openclaw/workspace-stock/data/`
- **日志位置**: `/home/admin/.openclaw/workspace-stock/logs/`
- **迁移指南**: `/home/admin/.openclaw/workspace-stock/strategy/MIGRATION.md`

---

**Stock 自动交易系统** — 让数据驱动交易决策 🚀
