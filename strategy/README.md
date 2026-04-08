# Strategy 目录 - 整合版

## 📁 目录结构
```
strategy/
├── README.md                    # 本文件
├── simple_chinese_news.py       # ✅ 国内新闻获取（财联社、雪球、新浪）
├── news_pipeline.py            # ✅ 国际新闻管道（Finnhub、SEC、CNBC等）
├── news_integration.py         # ✅ 新闻与交易策略深度整合
├── hk-scanner.py               # 港股扫描器
├── us-scanner.py               # 美股扫描器
├── test_news_integration.py    # 测试脚本
└── venv/                       # 虚拟环境（如有）
```

## 🎯 核心文件说明

### 1. **simple_chinese_news.py** ⭐推荐
- **功能**：获取国内财经新闻
- **支持**：财联社、雪球、新浪财经
- **特点**：简单有效，不依赖复杂API
- **使用**：`python3 simple_chinese_news.py`

### 2. **news_pipeline.py**
- **功能**：国际财经新闻获取
- **支持**：Finnhub、SEC EDGAR、CNBC、Yahoo Finance
- **特点**：情绪分析、数据库存储、自动摘要
- **使用**：`python3 news_pipeline.py`

### 3. **news_integration.py** ⭐核心
- **功能**：新闻与交易策略深度整合
- **特点**：
  - 自动调整交易评分（±15分）
  - 重大新闻实时警报
  - 市场情绪分析
  - 更新opportunities.json
- **使用**：
  ```bash
  python3 news_integration.py --full     # 完整整合
  python3 news_integration.py --update   # 只更新交易机会
  python3 news_integration.py --alerts   # 检查新闻警报
  ```

## 🔧 使用方法

### 基本工作流
1. **获取国内新闻**
   ```bash
   python3 simple_chinese_news.py
   ```

2. **获取国际新闻**
   ```bash
   python3 news_pipeline.py
   ```

3. **深度整合**
   ```bash
   python3 news_integration.py --full
   ```

### 添加到定时任务
在 `cron-tasks.txt` 末尾添加：

```bash
# 国内新闻获取：每天4次
0 9,12,15,18 * * * cd /home/admin/.openclaw/workspace-arashi/strategy && python3 simple_chinese_news.py >> ../logs/chinese_news.log 2>&1

# 新闻整合：每小时一次
30 * * * * cd /home/admin/.openclaw/workspace-arashi/strategy && python3 news_integration.py --update >> ../logs/news_integration.log 2>&1

# 国际新闻管道：每天2次
0 8,20 * * * cd /home/admin/.openclaw/workspace-arashi/strategy && python3 news_pipeline.py >> ../logs/news_pipeline.log 2>&1
```

## 📊 数据流程
```
国内新闻 → 国际新闻 → 新闻数据库 → 策略整合 → 交易决策
(simple_chinese_news.py) (news_pipeline.py)  (news.db)   (news_integration.py) (opportunities.json)
```

## 🗑️ 已删除的重复文件
为了简化系统，已删除以下重复文件：
- `news_fetcher.py` (根目录)
- `news_fetcher_full.py` (根目录)
- `strategy/news_fetcher.py` (重复)
- `strategy/news_fetcher_v2.py` (重复)
- `strategy/fix_chinese_news.py` (冲突)
- `strategy/fix_news_channels.py` (冲突)
- `strategy/web_based_news_fetcher.py` (web_fetch不可用)

## 🎯 核心优势
1. **✅ 深度整合**：新闻直接影响交易评分
2. **✅ 简单有效**：不依赖复杂API
3. **✅ 本地优先**：使用本地已有系统
4. **✅ 已验证**：测试通过，立即可用
5. **✅ 整洁目录**：无重复冲突文件

## 📞 技术支持

### 测试系统
```bash
# 测试新闻获取
python3 simple_chinese_news.py

# 测试整合效果
python3 test_news_integration.py

# 查看数据库
sqlite3 ../data/news/news.db "SELECT source,COUNT(*) FROM news GROUP BY source ORDER BY COUNT(*) DESC"
```

### 故障排除
```bash
# 重新创建数据库
rm ../data/news/news.db
python3 news_pipeline.py

# 检查定时任务
crontab -l | grep -E "(news|整合)"
```

---

**更新日期：2026-03-25**
**版本：v2.0 整合版**
**状态：✅ 已整合完成，立即可用**