# Strategy 目录 - v2.9

> 最后更新: 2026-09-22

## 📁 目录结构
```
strategy/
├── README.md                    # 本文件
├── auto-trader.py               # ⭐ 自动交易守护进程（港股+美股）
├── us-scanner.py                # ⭐ 美股扫描器（两层架构：Finnhub快筛 → 五源评分）
├── hk-scanner.py                # ⭐ 港股扫描器（两层架构：成分股快筛 → 五源评分）
├── four_source_scorer.py        # ⭐ 五源共振评分模块（资讯/公告/社区/机构/资金）
├── llm_stock_analyzer.py        # ⭐ LLM 智能分析（适配推理模型）
├── feishu-pusher.py             # ⭐ 飞书消息推送（买卖通知/机会提醒）
├── daily-report-to-feishu.py    # 日报生成 + 飞书Wiki上传
├── generate-weekly-report.py    # 周报生成
├── generate-monthly-report.py   # 月报生成
├── heartbeat-check.py           # 心跳健康检查
├── sync-futu-account.py         # 富途账户数据同步
├── hk_market_sentiment.py       # 港股情绪监控（VHSI/资金流向/牛熊证）
├── us_market_sentiment.py       # 美股情绪监控（VIX/恐慌贪婪/期权比）
├── technical_indicators_hk.py   # 港股技术指标（MA/RSI/ATR/MACD）
├── technical_indicators_us.py   # 美股技术指标
├── hk-optimizer.py              # 港股策略优化器
├── us-optimizer.py              # 美股策略优化器
├── news_pipeline.py             # 国际新闻管道（Finnhub/SEC/CNBC）
├── news_integration.py          # 新闻与交易策略整合
├── runtime_config.py            # ⭐ 统一配置管理（API密钥从.api-keys.json加载）
├── system-preflight.py          # ⭐ 启动前环境检查
├── vix_fetcher.py               # VIX数据获取
├── fear_greed_index.py          # CNN恐慌贪婪指数
├── earnings-forecast-module.py  # 财报预测模块
├── sentiment-3day-predictor.py  # 未来3日情绪预测
├── trading_calendar.py          # 交易日历工具
├── get-constituents.py          # 港股股票池周更（恒指+恒科）
├── get-us-constituents.py       # 美股股票池周更（标普500+NASDAQ）
├── recompute_sentiment.py       # 情绪重算工具
├── update-heartbeat-status.py   # 心跳状态更新
├── add_file_locks.py            # 文件锁工具
├── test_*.py                    # 测试脚本
├── .api-keys.json               # API密钥（git忽略，不入库）
├── .env.example                 # 环境变量示例
├── requirements.lock            # Python依赖锁定
├── cron-tasks.txt               # 定时任务配置参考
├── HEARTBEAT.md                 # 心跳任务说明
├── MEMORY.md                    # 策略记忆文件
├── MIGRATION.md                 # 迁移说明
├── CLEANUP-CANDIDATES.md        # 清理候选
├── hk-index-constituents.json   # 港股指数成分股
├── us-index-constituents.json   # 美股指数成分股
├── nasdaq-stocks.json           # NASDAQ股票列表
└── venv.bak/                    # 备份虚拟环境（git忽略）
```

## 🎯 v2.9 当前系统说明 (截至 2026-09-22)

### 五源共振评分系统
- 五源总分：资讯(25) + 公告(20) + 社区(25) + 机构(20) + 资金(10) = 100，中性基线合计50分
- 各数据源只提供原始证据；所有可用数据先合并，资讯/公告/研报按事件去重，再按分项统一计分一次
- 单个来源失败不扣分、不补零、不进入平均分母；所有来源都无真实数据时，该分项才标记“未覆盖”
- 资讯和公告数量不直接加分；社区数量只体现讨论热度；机构按去重意见方向；资金围绕5分对称增减
- 资讯和公告按事件类型固定强度计分（100%/75%/45%/25%），标题中同类词出现次数不会抬高分数；传闻按40%可信度折算
- `score_all()` 返回分数、中性线、相对中性增减、覆盖状态、证据和原始数据

### LLM 推理模型适配
- 自动检测推理模型（deepseek-v4-pro 等），`max_tokens` 从 220 动态抬到 800
- `content` 空时从 `reasoning_content` 末尾抽答案，避免误判为调用失败
- 美股五源评分 Top 50 会读取富途个股新闻，合并重复标题后交给现有同一次 LLM 判断事件方向、确定性和是否已被价格消化，不增加第二次 LLM 分析

### 飞书推送增强
- 买卖通知含五源分数 + 资金方向 + 社区多空比
- 买入与机会通知同时显示各分项“较中性±分数”
- 买入成交通知区分扫描信号参考价、盘中买点、保护限价与富途真实成交价
- 美股非交易时段机会通知显示信号参考价、参考价时间和规则追高上限

### 港股 Scanner 修复
- symbol 格式不再 lstrip，`score_all()` 传入原始代码
- 富途社区/新闻/研报接入（news_type=1/2/3）

### 扫描器时间预算与成交一致性
- 美股扫描总预算为59分钟，外层 cron 以60分钟作为最终兜底
- 美股第一层行情扫描与第二层五源评分均使用4并发
- 第二层在总预算内完成五源预取、Top 50 LLM 与结果保存；到期后立即收尾，不阻塞下一轮锁
- 美股75-79分使用6%-8%动态仓位，港股75-79分使用2%仓位，与75分交易线一致
- 卖单只有在富途确认 `FILLED_ALL` 且取得真实成交均价后，才写入平仓记录并发送飞书通知
- 延迟成交卖单会在下一轮自动交易中回查，按订单 ID 去重，并按富途剩余持仓清理或更新本地开仓状态
- 新闻入库统计只累计真实新增记录，重复新闻会复用原记录补充股票关联

### 港美股盘中买点与订单保护
- 美股在评分、五源、LLM和日线技术条件通过后采用双路径：现价站稳VWAP/EMA9且未超过信号价1.5%时以保护限价单直接入场；否则挂DAY被动限价等待回踩
- 美股不再等待30分钟K线确认，也不主动撤销未成交订单；订单未成交时由富途在当日收盘自动失效
- 港股仍保留最多30分钟观察，要求“回踩VWAP/EMA9后重新站稳”或“连续两根已完成1分钟K线放量突破”
- 港股数量继续按每手股数向下取整；港美股各自使用独立状态文件、市场时区和跨进程订单锁
- 活动订单会阻止同标的重复下单；只有富途确认真实成交后才记录持仓并发送飞书买入通知

### 股票池周更
- 股票池只覆盖既定范围：港股为恒生指数、恒生科技指数及2只明确配置的韩国半导体杠杆ETF；美股为标普500与NASDAQ上市非ETF股票，不扩展到其他美国交易所
- 港股每周日08:00通过Futu OpenD读取`HK.800000`和`HK.800700`，再合并固定自定义标的`HK.07709`、`HK.07747`并按代码去重
- 港股和美股JSON均使用独立`custom`字段保存手工标的；周更只替换官方来源字段并原样保留`custom`，不再使用无法区分来源的`legacy_extra`
- 美股每周日08:15更新：标普500同时请求Wikipedia和GitHub CSV进行差异核对；NASDAQ以Nasdaq Trader为主，并使用Finnhub `XNAS`名录补漏
- 标普双源差异超过安全阈值时拒绝覆盖；单个NASDAQ补充源失败时跳过该源，不估算、不生成虚假成员
- 更新文件采用临时文件原子替换；扫描器每次启动都会重新读取`hk-index-constituents.json`或`us-index-constituents.json`
- 当前股票池：港股106只；美股4660只；两边均按代码去重

### 基础设施
- `runtime_config.py`：路径、密钥位置、系统版本与 `STRATEGY_POLICY` 的统一来源
- `system-preflight.py`：启动前环境检查
- `.gitignore` 增强：排除 api-keys、IDE配置、缓存目录

## 🔧 快速开始

### 前置要求
1. **Futu OpenD** 运行在 `127.0.0.1:11111`
2. **Python 3.x** + futu-venv 虚拟环境
3. **API密钥** 配置在 `strategy/.api-keys.json`

### 启动自动交易
```bash
# 启动守护进程
python3 auto-trader.py --daemon

# 单次运行
python3 auto-trader.py
```

### 启动扫描器
```bash
# 美股扫描
python3 us-scanner.py

# 港股扫描
python3 hk-scanner.py
```

## 📊 评分架构
```
第一层：市场快筛（Finnhub/成分股）→ 候选列表
第二层：五源共振评分 → LLM 调整 → 最终分数
         │
         ├─ 资讯 (25分)：多源新闻合并去重，按最强利好/利空事件计分
         ├─ 公告 (20分)：公告、EPS、内部人交易和重大事件合并去重
         ├─ 社区 (25分)：多平台讨论合并，热度 + 多空方向
         ├─ 机构 (20分)：分析师票数与研报事件合并，重复共识不重复投票
         └─ 资金 (10分)：特大单、连续主力流向和卖空变化对称计分
         │
         └─→ Top 50 单次 LLM 智能调整 (±10分，含富途新闻语义分析)
              │
              ├─ 交易候选线 ≥75；仍须通过 LLM、技术指标、仓位和富途订单校验
              └─ 美股非交易时段 ≥85 → 推送提醒
```

## 📱 飞书集成
- 交易信号实时推送（买入/卖出/机会提醒）
- 日报/周报/月报自动生成上传 Wiki
- 消息卡片含五源分数 breakdown

## 📋 定时任务
| 任务 | 时间 | 说明 |
|------|------|------|
| 美股扫描 | 周一至周六每小时 | 每轮最长60分钟 |
| 港股扫描 | 交易时段每5分钟 | 每轮最长20分钟 |
| 自动交易 | 每5分钟 | 交易时段检查持仓风控与合格机会 |
| 日报生成 | 收盘后 | 上传飞书Wiki |
| 股票池周更 | 周日08:00/08:15 | 港股/美股依次更新 |
| 心跳检查 | 每3分钟 | 系统健康监控 |

---

**版本：v2.9**
**更新日期：2026-09-22**
**状态：✅ 运行中**
