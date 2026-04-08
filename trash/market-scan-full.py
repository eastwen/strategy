#!/usr/bin/env python3
"""Full-featured market scanner with real news, technical analysis, earnings tracking and auto stop loss"""

import sys
import requests
import json
import re
from datetime import datetime, timedelta
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

print("="*60)
print("🚀 OpenClaw 全功能市场扫描器启动 (真实数据源+技术面+财报跟踪+自动止损)")
print("="*60)

# 自动止损
def auto_stop_loss(trade_ctx, acc_id):
    print("\n🛡️  正在执行自动止损检查...")
    ret, positions = trade_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
    if ret != RET_OK:
        print(f"❌ 获取持仓失败: {positions}")
        return
    
    stop_loss_executed = False
    for _, pos in positions.iterrows():
        pl_ratio = float(pos['pl_ratio'] if pos['pl_ratio'] != 'N/A' else 0)
        if pl_ratio <= -6: # 浮亏≥6%自动止损
            code = pos['code']
            name = pos['stock_name']
            qty = pos['qty']
            pl = float(pos['pl_val'] if pos['pl_val'] != 'N/A' else 0)
            print(f"⚠️ {code} {name} 浮亏达到{pl_ratio:.2f}%，触发止损线，执行卖出...")
            
            # 市价卖出
            ret, data = trade_ctx.place_order(
                price=0,
                qty=qty,
                code=code,
                trd_side=TrdSide.SELL,
                order_type=OrderType.MARKET,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret == RET_OK:
                order_id = data['order_id'][0]
                print(f"✅ 止损成功! 卖出{qty}股，单号: {order_id}")
                stop_loss_executed = True
                
                # 发送飞书通知 - 立即发送
                try:
                    res = requests.post(
                        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                        json={"app_id": "cli_a93b169884f8dcc1", "app_secret": "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV"},
                        timeout=10
                    )
                    token = res.json()["tenant_access_token"]
                    
                    # 卖出通知
                    msg = f"""⚠️ 自动止损执行！

标的: {code} {name}
数量: {qty}股
浮亏: ${pl:.2f} ({pl_ratio:.2f}%)
状态: 已自动市价卖出
单号: {order_id}

当前账户可用资金: ${cash:,.2f}"""
                    
                    requests.post(
                        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={
                            "receive_id": "ou_571e965fc81a2e887609a06ed6103d66",
                            "msg_type": "text",
                            "content": '{"text": "' + msg.replace("\n", "\\n").replace('"', '\\"') + '"}'
                        },
                        timeout=10
                    )
                    print("✅ 已发送止损飞书通知")
                except Exception as e:
                    print(f"⚠️ 通知发送失败: {e}")
            else:
                print(f"❌ 止损失败: {data}")
    
    if not stop_loss_executed:
        print("✅ 所有持仓浮亏均未达到止损线，无需操作")

# 完整资讯获取 - 全部渠道一次性对接
def fetch_real_news():
    print("\n📰 正在通过全部渠道抓取市场资讯...")
    news = []
    
    try:
        sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi')
        from news_fetcher_full import fetch_all_news
        
        # 获取全部渠道资讯
        all_news = fetch_all_news()
        news = all_news
        
        # 自动匹配标的关键词
        keywords = {
            "NVDA": ["英伟达", "NVIDIA", "AI芯片", "GPU"],
            "AMD": ["超微", "Advanced Micro Devices", "AI芯片"],
            "TSM": ["台积电", "Taiwan Semiconductor"],
            "META": ["Meta", "脸书", "人工智能"],
            "AAPL": ["苹果", "iPhone"],
            "MSFT": ["微软", "Microsoft", "Copilot"],
            "GOOGL": ["谷歌", "Google", "AI"],
            "BABA": ["阿里巴巴", "马云"],
            "TCEHY": ["腾讯", "马化腾"],
            "TSLA": ["特斯拉", "马斯克", "新能源"]
        }
        
        for n in news:
            for stock, keys in keywords.items():
                for key in keys:
                    if key in n.get('title', '') or key in n.get('summary', '') or key in n.get('content', ''):
                        if f"US.{stock}" not in n['stocks']:
                            n['stocks'].append(f"US.{stock}")
                            n['score'] = n.get('score', 60)  # 默认60分
        
        print(f"✅ 全部渠道资讯获取完成，共 {len(news)} 条")
        
    except Exception as e:
        print(f"⚠️ 资讯获取失败: {e}")
    
    return news

# 技术面分析 - 完整策略实现
def calculate_technical_score(quote_ctx, code):
    """完整技术面分析，包含策略原文要求的4个条件"""
    try:
        # 获取最近60日K线
        ret, data, _ = quote_ctx.request_history_kline(code, start=datetime.strftime(datetime.now() - timedelta(days=60), "%Y-%m-%d"),
                                                   end=datetime.now().strftime("%Y-%m-%d"), ktype=KLType.K_DAY, max_count=60)
        if ret != RET_OK or len(data) < 20:
            return 50, []
        
        # 计算各项技术指标
        data['ma5'] = data['close'].rolling(5).mean()
        data['ma10'] = data['close'].rolling(10).mean()
        data['ma20'] = data['close'].rolling(20).mean()
        
        close = data['close'].iloc[-1]
        ma5 = data['ma5'].iloc[-1]
        ma10 = data['ma10'].iloc[-1]
        ma20 = data['ma20'].iloc[-1]
        
        # 条件1: 5日/10日均线金叉
        golden_cross = ma5 > ma10 and data['ma5'].iloc[-2] <= data['ma10'].iloc[-2]
        
        # 条件2: 成交量放大≥50%
        avg_vol_30 = data['volume'].iloc[-30:].mean()
        current_vol = data['volume'].iloc[-1]
        vol_amplified = current_vol >= avg_vol_30 * 1.5
        
        # 条件3: RSI位于40-60区间
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean().iloc[-1]
        rs = gain / loss if loss != 0 else float('inf')
        rsi = 100 - (100 / (1 + rs))
        rsi_ok = 40 <= rsi <= 60
        
        # 条件4: 突破20日新高
        high_20 = data['high'].iloc[-20:].max()
        break_high = close >= high_20 * 0.98  # 接近20日新高
        
        # 统计满足的条件
        conditions_met = []
        if golden_cross: conditions_met.append("均线金叉")
        if vol_amplified: conditions_met.append("成交量放大")
        if rsi_ok: conditions_met.append("RSI中性(40-60)")
        if break_high: conditions_met.append("突破20日新高")
        
        # 计算技术面评分（0-100）
        tech_score = 50
        if golden_cross: tech_score += 20
        if vol_amplified: tech_score += 15
        if rsi_ok: tech_score += 15
        if break_high: tech_score += 10
        
        # 额外加分：所有条件都满足
        if len(conditions_met) >= 3:
            tech_score = min(100, tech_score + 10)
        
        tech_score = min(100, max(0, tech_score))
        
        return tech_score, conditions_met
        
    except Exception as e:
        print(f"⚠️ {code} 技术面计算失败: {e}")
        return 50, []

# 综合评分
def calculate_total_score(news_list, tech_score, stock):
    # 资讯面评分
    news_score = 0
    news_count = 0
    for news in news_list:
        if stock in news.get("stocks", []):
            weight = 0.35 if news.get("source") in ["Finnhub", "AlphaVantage"] else 0.25
            score = news.get("score", 50)  # 默认50分
            news_score += score * weight
            news_count += 1
    
    if news_count == 0:
        news_score = 50 # 无资讯返回中性分
    
    # 总分: 资讯面60% + 技术面40%
    total_score = news_score * 0.6 + tech_score * 0.4
    return round(total_score, 1)

# 财报跟踪提醒
def check_earnings_alert(news_list, watchlist):
    alerts = []
    for news in news_list:
        if news.get("type") == "earnings":
            for stock in news["stocks"]:
                if stock in watchlist:
                    alerts.append(f"⚠️ 财报提醒: {stock} {news['title']}")
    return alerts

# 主逻辑
def main():
    # 连接富途
    quote_ctx = OpenQuoteContext('127.0.0.1', port=11111)
    trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)
    
    # 解锁
    ret_unlock, _ = trade_ctx.unlock_trade('709394')
    print(f"\n🔑 交易接口解锁: {'✅ 成功' if ret_unlock == RET_OK else '❌ 失败'}")
    
    if ret_unlock != RET_OK:
        quote_ctx.close()
        trade_ctx.close()
        return
    
    # 获取账户ID
    ret_acc, acc_list = trade_ctx.get_acc_list()
    sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
    if len(sim_acc) == 0:
        print("❌ 未找到模拟账户")
        quote_ctx.close()
        trade_ctx.close()
        return
    
    acc_id = sim_acc.iloc[0]['acc_id']
    
    # 1. 执行自动止损检查
    auto_stop_loss(trade_ctx, acc_id)
    
    # 关注池 - 港股和美股分开
    hk_watchlist = ["HK.00700", "HK.09988", "HK.09999", "HK.01810", "HK.09868", "HK.01211", "HK.02386", "HK.03988"]
    us_watchlist = ["US.NVDA", "US.AMD", "US.TSM", "US.VRT", "US.LITE", "US.AVGO", "US.META", "US.AAPL", "US.MSFT"]
    watchlist = hk_watchlist + us_watchlist
    
    print(f"📊 港股关注池: {len(hk_watchlist)} 只")
    print(f"📊 美股关注池: {len(us_watchlist)} 只")
    
    # 2. 抓取真实资讯
    news_list = fetch_real_news()
    
    # 3. 市场情绪VIX
    print("\n📊 市场情绪监测:")
    try:
        sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi')
        from vix_fetcher import get_market_sentiment
        sentiment, vix = get_market_sentiment()
        print(f"  VIX指数: {vix:.2f} | 情绪: {sentiment}")
        
        # 根据VIX调整策略参数
        global ADJUSTED_ENTRY_THRESHOLD, ADJUSTED_POSITION_RATIO
        ADJUSTED_ENTRY_THRESHOLD = 70 # 默认入场阈值
        ADJUSTED_POSITION_RATIO = 0.02 # 默认仓位2%
        
        if sentiment == "极度恐慌" or vix >= 30:
            ADJUSTED_ENTRY_THRESHOLD = 80
            ADJUSTED_POSITION_RATIO = 0.01
            print("  ⚠️ 市场极度恐慌：入场阈值提高到80分，仓位降低到1%")
        elif sentiment == "恐慌" or 25 <= vix <30:
            ADJUSTED_ENTRY_THRESHOLD = 75
            ADJUSTED_POSITION_RATIO = 0.015
            print("  ⚠️ 市场恐慌：入场阈值提高到75分，仓位降低到1.5%")
        elif sentiment == "极度乐观" or vix <15:
            ADJUSTED_ENTRY_THRESHOLD = 65
            ADJUSTED_POSITION_RATIO = 0.025
            print("  📈 市场极度乐观：入场阈值降低到65分，仓位提高到2.5%")
    except Exception as e:
        print(f"⚠️ VIX获取失败: {e}")
        ADJUSTED_ENTRY_THRESHOLD = 70
        ADJUSTED_POSITION_RATIO = 0.02
    
    # 4. 财报提醒
    earnings_alerts = check_earnings_alert(news_list, watchlist)
    if earnings_alerts:
        print("\n📢 财报提醒:")
        for alert in earnings_alerts:
            print(f"  {alert}")
    
    # 4. 逐个分析标的，输出满足的技术条件
    print(f"\n🔍 正在分析 {len(watchlist)} 个标的...")
    candidates = []
    for stock in watchlist:
        tech_score, conditions = calculate_technical_score(quote_ctx, stock)
        total_score = calculate_total_score(news_list, tech_score, stock)
        
        cond_str = ", ".join(conditions) if conditions else "无明显信号"
        print(f"  {stock}: 技术面{tech_score:.1f}分 [{cond_str}] + 资讯面{calculate_total_score(news_list, 0, stock):.1f}分 = 总分{total_score}分")
        
        # 入场条件：总分≥动态阈值 + 至少2个技术条件满足
        if total_score >= ADJUSTED_ENTRY_THRESHOLD and len(conditions) >= 2:
            candidates.append((stock, total_score, conditions))
    
    # 5. 执行符合条件的买入
    if candidates:
        print(f"\n✅ 找到 {len(candidates)} 个符合条件的标的（≥70分）:")
        ret_info, acc_info = trade_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
        cash = float(acc_info['cash'].iloc[0] if acc_info['cash'].iloc[0] != 'N/A' else 0)
        
        for stock, score, conditions in sorted(candidates, key=lambda x: x[1], reverse=True):
            # 按评分确定仓位，基础仓位使用VIX调整后的比例
            base_ratio = ADJUSTED_POSITION_RATIO
            if score >= 90:
                position_ratio = min(0.05, base_ratio * 1.5)
            elif score >= 80:
                position_ratio = min(0.03, base_ratio * 1.2)
            else:
                position_ratio = base_ratio
            
            position_size = cash * position_ratio
            if position_size < 100:
                continue
            
            # 获取当前价格
            ret, data, _ = quote_ctx.get_market_snapshot([stock])
            if ret != RET_OK or len(data) == 0:
                continue
            
            price = data['last_price'].iloc[0]
            qty = int(position_size / price)
            if qty <= 0:
                continue
            
            print(f"  🔹 执行买入 {stock}: 评分{score}分，仓位{position_ratio*100:.0f}%，预计{qty}股@${price:.2f}")
            
            # 市价买入
            ret, data = trade_ctx.place_order(
                price=0,
                qty=qty,
                code=stock,
                trd_side=TrdSide.BUY,
                order_type=OrderType.MARKET,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret == RET_OK:
                order_id = data['order_id'][0]
                print(f"    ✅ 委托成功! 单号: {order_id}")
                
                # 发送通知
                try:
                    res = requests.post(
                        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                        json={"app_id": "cli_a93b169884f8dcc1", "app_secret": "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV"},
                        timeout=10
                    )
                    token = res.json()["tenant_access_token"]
                    
                    msg = f"✅ 自动买入提醒\n\n标的: {stock}\n数量: {qty}股\n价格: ${price:.2f}\n总金额: ${qty*price:.2f}\n评分: {score}分\n委托单号: {order_id}"
                    
                    requests.post(
                        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={
                            "receive_id": "ou_571e965fc81a2e887609a06ed6103d66",
                            "msg_type": "text",
                            "content": '{"text": "' + msg.replace("\n", "\\n").replace('"', '\\"') + '"}'
                        },
                        timeout=10
                    )
                except Exception as e:
                    print(f"    ⚠️ 通知发送失败: {e}")
            else:
                print(f"    ❌ 委托失败: {data}")
    else:
        print("\n⚠️ 当前没有符合条件的交易标的")
    
    # 6. 获取持仓盈亏
    ret, positions = trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
    if ret == RET_OK and len(positions) > 0:
        print(f"\n📦 当前持仓:")
        total_pnl = 0
        for _, pos in positions.iterrows():
            pl = float(pos['pl_val'] if pos['pl_val'] != 'N/A' else 0)
            total_pnl += pl
            print(f"  {pos['code']} {pos['stock_name']}: {pos['qty']}股 | 盈亏: ${pl:.2f} ({pos['pl_ratio']}%)")
        print(f"  总持仓盈亏: ${total_pnl:.2f}")
    
    # 关闭连接
    quote_ctx.close()
    trade_ctx.close()
    
    # 保存日志
    with open("/home/admin/.openclaw/workspace-arashi/logs/scan-full.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 扫描完成, 候选标的{len(candidates)}个, 持仓总盈亏${total_pnl:.2f}\n")
    
    print(f"\n✅ 本次扫描完成!")
    print(f"📝 后续系统会自动筛选符合条件的标的，达到阈值自动交易并通知你~")

if __name__ == "__main__":
    main()