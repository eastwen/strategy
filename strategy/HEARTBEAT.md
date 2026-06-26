# Strategy Heartbeat - 策略心跳检查

## 📊 检查内容

### 1. 项目数据完整性检查
- 检查 data/pending-reports/ 目录
- 有新的日报 → 主动汇报给用户
- 汇报后移动到 data/sent-reports/

### 2. 交易机会扫描
- 检查 data/us-opportunities.json
- 有评分≥70的机会 → 主动汇报
- 检查 data/hk-opportunities.json

### 3. 交易执行状态
- 检查 data/trades.json
- 有新交易 → 主动汇报
- 监控持仓变化

### 4. 系统警报检查
- 检查 data/alerts.json
- 有重大变化 → 主动汇报
- 数据过期时提醒刷新

### 5. 数据同步健康度
- 检查 data/trades.json 的 sync_time
- 如果超过1小时未同步 → 执行同步
- 确保日报数据与富途账户一致

## 📍 路径说明
所有路径相对于策略项目根目录 (~/.openclaw/workspace/strategy/)
