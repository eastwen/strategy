# 策略最终版本总结

**更新日期：2026-07-12**
**当前版本：v2.4（五源共振 + LLM推理模型适配 + 飞书推送增强）**

---

## 🎯 项目全貌

**项目名称：** 模拟盘自动交易 + 每日汇报系统

**核心模块：**
1. 港股策略 v2.1（独立策略 + 动态调整）
2. 美股策略 v1.7（严格择时 + 自动交易 v2.1）
3. **五源共振评分模块 v2.0** ⭐ NEW（2026-07-04 ~ 07-12）
4. **LLM 智能分析（推理模型适配）** ⭐ NEW（2026-07-04）
5. **资金异动检测** ⭐ NEW（2026-07-04，接入 futu-capital-anomaly skill）
6. 情绪监控系统
7. 财报预测模块
8. 定时任务调度
9. 飞书推送集成（含五源分数 breakdown）

---

## 🔥 v2.4 核心变更（2026-07-04 ~ 07-12）

### 1. 五源共振评分系统（四源升级为五源）
- **新增资金异动维度** (10分)：接入 futu-capital-anomaly skill
- 五源总分：资讯(25) + 公告(20) + 社区(25) + 机构(20) + 资金(10) = 100
- score_all() 返回完整五源分数 + 证据 + 原始数据

### 2. LLM 推理模型适配
- 自动检测推理模型（deepseek-v4-pro 等），max_tokens 从 220 动态抬到 800
- content 空时从 reasoning_content 末尾抽答案

### 3. 飞书推送增强
- 买卖通知含五源分数 + 资金方向 + 社区多空比
- 机会提醒含完整五源 breakdown

### 4. 港股 Scanner 修复
- symbol 格式不再 lstrip，score_all() 传入原始代码
- 富途社区/新闻/研报接入（news_type=1/2/3）

### 5. 扫描器超时保护
- 第一层 Finnhub：20分钟时间预算
- 第二层四源+LLM：15分钟时间预算
- 超时 break 返回已扫到的部分结果

### 6. 基础设施
- runtime_config.py：统一配置管理
- system-preflight.py：启动前环境检查
- .gitignore 增强：排除 api-keys、IDE配置、缓存目录

**触发**：MU 财报超预期、股价 +12%，但非交易时段推送零命中，全市场最高分仅 68。

**三个系统级 Bug（全市场受影响）：**

1. **LLM 推理模型 token 截断** (`llm_stock_analyzer.py`)
   - 推理模型答案走 `reasoning_content`，220 tokens 被 reasoning 吃光 → `content` 空 → 误判调用失败
   - 修复：推理模型自动抬到 800 tokens；`content` 空时从 `reasoning_content` 末尾抽答案

2. **公告维度漏算财报/重大事件** (`four_source_scorer.py`)
   - 原 `score_official_announce` 只看 SEC insider trading，全市场财报 beat / 重大公告全不计分
   - 修复：新增 `_announce_news_event` 读 `data/alerts.json`
     - 重大利好 高档 +15 (cap=20) / 中档 +9 / 重大利空 -10
     - news.db 免底 ANNOUNCE 关键词正面情绪 +5

3. **社区维度只查中文源** (`four_source_scorer.py`)
   - 原仅查新浪/东方财富/36氪，美股个股永远 0/25
   - 修复：美股新增 `_us_public_attention`（Yahoo Finance / Google News Tech / Finnhub）

**验证结果（MU）**：
```
修复前：news 27 / ann  0 / com  0 / inst 24 = 51 → LLM"失败"+0 → 最终 51
修复后：news 27 / ann 15 / com 20 / inst 24 = 86 → LLM -3       → 最终 83
```

**门槛决策**：
- 交易时段 `us_config.min_score = 80`（自动下单）
- 非交易时段 `us_config.opp_alert_score = 90`（仅推送提醒，不下单）

---

## 🇭🇰 港股策略 v2.1 - 动态调整版

### 配置文件
```
/home/admin/.openclaw/workspace-stock/config/hk-strategy.json
/home/admin/.openclaw/workspace-stock/config/hk-strategy-dynamic-v2.1.json
```

### 核心特点
- **动态行业权重**：根据近期表现自动调整（0.2-2.0）
- **四源共振**：资讯+公告+社区+社交
- **情绪监控**：VHSI、资金流向、牛熊证比例
- **财报预测**：预期EPS、营收增速、超预期概率

### 回测表现
| 行业 | 平均收益 | 胜率 | 权重 |
|------|----------|------|------|
| 新能源汽车 | +2.58% | 100% | 2.00 |
| 消费 | +2.31% | 100% | 1.85 |
| 医药 | +0.43% | 50% | 0.81 |

### 推荐交易股票（8只）
**新能源汽车（权重2.00）：**
1. 小鹏汽车-W (HK.09868)
2. 蔚来-SW (HK.09866)
3. 比亚迪股份 (HK.02333)

**消费（权重1.85）：**
4. 李宁 (HK.02331)
5. 蒙牛乳业 (HK.02319)
6. 安踏体育 (HK.02020)

**医药（权重0.81）：**
7. 药明生物 (HK.02269)
8. 石药集团 (HK.01093)

---

## 🇺🇸 美股策略 v1.7 - 严格择时版（搭配四源共振 v1.0）

### 配置文件
```
/home/admin/.openclaw/workspace-stock/config/us-strategy.json
/home/admin/.openclaw/workspace-stock/config/us-strategy-v1.7.json
```

### 核心特点
- **严格择时**：MA20 > MA50，价格 > MA20
- **多信号共振**：MACD+均线+成交量+布林带
- **情绪监控**：VIX、恐慌贪婪指数、期权比例
- **财报预测**：预期EPS、营收增速、超预期概率

### 回测表现
| 标的 | 收益率 | 最大回撤 | 交易次数 | 胜率 |
|------|--------|----------|----------|------|
| Vertiv | +2.88% | 0.28% | 1 | 100% |
| Meta | +0.93% | 0.20% | 1 | 100% |
| 其他4只 | 0.00% | 0.00% | 0 | - |
| **平均** | **+1.91%** | - | **2次** | **100%** |

### 推荐交易股票（4只）
1. Vertiv (VRT)
2. Meta (META)
3. AMD (AMD)
4. 苹果 (AAPL)

---

## 📊 四源共振系统

### 港股四源
```
国际资讯 (30%) → 宏观新闻、政策变化
港股公告 (20%) → 财报、回购、配股
国内社区 (25%) → 雪球、富途讨论
海外社交 (25%) → 机构观点、大V热议
```

### 美股四源
```
国际资讯 (35%) → Bloomberg, Reuters, Finnhub
监管公告 (20%) → SEC EDGAR
国内社区 (25%) → 财联社、雪球、富途
海外社交 (20%) → X/Twitter, Reddit
```

---

## 📈 情绪监控系统

### 港股指标
| 指标 | 代码 | 权重 | 数据源 |
|------|------|------|--------|
| VHSI恒指波幅 | HK.800125 | 35% | Futu |
| 港股通资金流向 | get_capital_distribution | 35% | Futu |
| 牛熊证比例 | get_warrant | 30% | Futu |

### 美股指标
| 指标 | 代码/来源 | 权重 | 数据源 |
|------|----------|------|--------|
| VIX恐慌指数 | US.VIX | 30% | Futu |
| CNN恐慌贪婪指数 | CNN API | 25% | CNN |
| 看涨看跌期权比例 | get_option_chain | 25% | Futu |

### 主要指数监控
**港股：** 恒生指数(HK.800000)、国企指数(HK.800100)、恒生科技指数(HK.800700)

**美股：** 标普500(^GSPC)、纳斯达克100(^NDX)、道琼斯(^DJI)、纳斯达克综合(^IXIC)

---

## 📉 财报预测模块

### 数据字段
- 财报披露时间
- 预期EPS
- 预期营收增速
- 超预期概率
- 对股价影响预期

### 数据源
- SEC EDGAR（官方）
- Finnhub API
- Yahoo Finance

---

## ⚙️ 定时任务

| 任务 | 时间 | 频率 | 说明 |
|------|------|------|------|
| 港股日报 | 16:10 | 周一到周五 | 周末不发 |
| 美股日报 | 05:10 | 周六 | 美股周五收盘后 |
| 周报 | 15:00 | 周六 | 本周总结 |
| 月报 | 16:10 | 月末 | 本月总结 |
| 市场扫描 | 每小时 | 24小时 | 实时监控 |
| 行业权重更新 | - | 每月 | 动态调整 |

---

## 🔌 API配置

| API | 用途 | 状态 |
|-----|------|------|
| Futu OpenD | 港股数据/交易 | ✅ 127.0.0.1:11111 |
| Tushare | A股/港股数据 | ✅ 已配置 |
| Finnhub | 美股资讯/财报 | ✅ 已配置 |
| AlphaVantage | 美股技术数据 | ✅ 已配置 |
| CNN API | 恐慌贪婪指数 | ✅ 已配置 |
| 长桥 | 美股行情数据 | ✅ 已配置 |

---

## 📱 飞书集成

```
AppId: cli_a93b169884f8dcc1
权限: wiki:wiki, drive:drive:readonly, docx:document
用户: ou_571e965fc81a2e887609a06ed6103d66
维基空间: 7618145540269820891
```

---

## 📁 文件结构（当前）

```
/home/admin/.openclaw/workspace-stock/
├── 📊 报告生成
│   ├── comprehensive-report-v12.py    # 日报 ⭐
│   ├── generate-weekly-report.py      # 周报 ⭐
│   └── generate-monthly-report.py     # 月报 ⭐
│
├── 🔍 扫描器
│   ├── smart-scanner-v2.py            # 核心扫描器 ⭐
│   └── auto-scanner-daemon.py         # 扫描守护进程
│
├── 💰 交易执行
│   └── futu-trader.py                 # 富途交易
│
├── 📡 数据获取
│   ├── sync-futu-account.py           # 账户同步 ⭐
│   ├── vix_fetcher.py                 # VIX数据
│   ├── fear_greed_index.py            # 恐慌贪婪指数
│   ├── news_fetcher.py                # 新闻获取
│   └── news_fetcher_full.py           # 完整新闻
│
├── 🔮 预测模块
│   ├── sentiment-3day-predictor.py    # 3日情绪预测
│   └── earnings-forecast-module.py    # 财报预测
│
├── 📤 推送模块
│   └── feishu-pusher.py               # 飞书推送
│
├── ⚙️ 其他
│   ├── trading_calendar.py            # 交易日历
│   ├── get_sim_account_info.py        # 账户信息
│   ├── hf-monitor.py                  # 高频监控
│   └── auto-trading-system.py         # 自动交易系统
│
├── ⚙️ 配置文件
│   ├── .api-keys.json                 # API密钥
│   └── config/
│       ├── hk-strategy-dynamic-v2.0.json  # 港股策略配置 ⭐
│       └── us-strategy-v1.0.json          # 美股策略配置 ⭐
│
├── 📁 数据目录
│   └── data/
│       ├── trades.json                # 交易数据
│       ├── us-opportunities.json      # 美股机会
│       ├── hk-opportunities.json      # 港股机会
│       └── alerts.json                # 警报数据
│
└── 📝 文档
    ├── STRATEGY-FINAL.md              # 策略总结（本文件）⭐
    └── MEMORY.md                      # 长期记忆
```

⭐ = 核心文件
**Python文件总数：18个**

---

## ✅ 系统状态

### 港股
- ✅ 专注新能源汽车+消费（权重≥1.85）
- ✅ 8只推荐股票
- ✅ 动态调整行业权重

### 美股
- ✅ 专注科技龙头
- ✅ 4只推荐股票
- ✅ 严格择时策略

### 系统
- ✅ 四源共振系统
- ✅ 情绪监控系统
- ✅ 财报预测模块
- ✅ 定时任务调度
- ✅ 飞书推送集成

---

**最终更新：2026-06-26**
**当前版本：v2.2（四源共振真实评分 + LLM 推理模型修复）**
**下次评估：跳过一轮交易日后复盘数据**
