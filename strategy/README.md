# Strategy 目录 - v2.4

> 最后更新: 2026-07-14

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
├── get-constituents.py          # 港股成分股获取
├── get-us-constituents.py       # 美股成分股获取
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

## 🎯 v2.4 当前系统说明 (截至 2026-07-14)

### 五源共振评分系统
- **新增资金异动维度** (10分)：接入 futu-capital-anomaly skill，检测大单/异常资金流向
- 五源总分：资讯(25) + 公告(20) + 社区(25) + 机构(20) + 资金(10) = 100
- `score_all()` 返回完整五源分数 + 证据 + 原始数据

### LLM 推理模型适配
- 自动检测推理模型（deepseek-v4-pro 等），`max_tokens` 从 220 动态抬到 800
- `content` 空时从 `reasoning_content` 末尾抽答案，避免误判为调用失败

### 飞书推送增强
- 买卖通知含五源分数 + 资金方向 + 社区多空比
- 机会提醒含完整五源 breakdown

### 港股 Scanner 修复
- symbol 格式不再 lstrip，`score_all()` 传入原始代码
- 富途社区/新闻/研报接入（news_type=1/2/3）

### 扫描器时间预算与成交一致性
- 美股扫描总预算为59分钟，外层 cron 以60分钟作为最终兜底
- 第二层在总预算内完成五源预取、Top 20 LLM 与结果保存；到期后立即收尾，不阻塞下一轮锁
- 卖单只有在富途确认 `FILLED_ALL` 且取得真实成交均价后，才写入平仓记录并发送飞书通知
- 延迟成交卖单会在下一轮自动交易中回查，按订单 ID 去重

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
         ├─ 资讯 (25分)：Finnhub 新闻 + 情绪分析
         ├─ 公告 (20分)：SEC + 财报 beat + 重大公告
         ├─ 社区 (25分)：富途社区 + Yahoo/Google/Finnhub
         ├─ 机构 (20分)：SEC insider + 分析师一致预期
         └─ 资金 (10分)：futu-capital-anomaly skill
         │
         └─→ LLM 智能调整 (±10分)
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
| 美股扫描 | 每小时 | 交易时段密集扫描 |
| 港股扫描 | 每小时 | 交易时段密集扫描 |
| 自动交易 | 每5分钟 | 交易时段检查持仓风控与合格机会 |
| 日报生成 | 收盘后 | 上传飞书Wiki |
| 心跳检查 | 每30分钟 | 系统健康监控 |

---

**版本：v2.4**
**更新日期：2026-07-14**
**状态：✅ 运行中**
