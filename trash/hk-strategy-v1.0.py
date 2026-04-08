#!/usr/bin/env python3
"""
港股独立策略系统 v1.0
OpenClaw 港股专用交易模块
"""

import sys
import os
import json
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

# 导入恐惧贪婪指数
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi')
try:
    from fear_greed_index import FearGreedIndex
except ImportError:
    FearGreedIndex = None

class HKStrategy:
    """港股独立策略类"""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or '/home/admin/.openclaw/workspace-arashi/config/hk-strategy-v1.0.json'
        self.config = self._load_config()
        self.quote_ctx = None
        self.trade_ctx = None
        self.acc_id = None
        
    def _load_config(self) -> dict:
        """加载配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def connect(self) -> bool:
        """连接Futu OpenD"""
        try:
            self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            self.trade_ctx = OpenHKTradeContext(host='127.0.0.1', port=11111)
            
            # 获取模拟盘账户
            ret, acc_list = self.trade_ctx.get_acc_list()
            if ret != RET_OK:
                print(f"❌ 获取账户列表失败: {acc_list}")
                return False
            
            sim_acc = acc_list[acc_list['acc_type'] == 'CASH']
            if sim_acc.empty:
                print("❌ 未找到现金账户")
                return False
            
            self.acc_id = sim_acc.iloc[0]['acc_id']
            print(f"✅ 连接成功，账户ID: {self.acc_id}")
            return True
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
    
    # ==================== 情绪指数监控 ====================
    
    def get_vhsi(self) -> Optional[float]:
        """获取恒指波幅指数 VHSI"""
        try:
            ret, data = self.quote_ctx.get_market_snapshot(['HK.800125'])
            if ret == RET_OK and not data.empty:
                price = data.iloc[0]['last_price']
                if price and str(price) != 'N/A':
                    return float(price)
            return None
        except Exception as e:
            print(f"⚠️ 获取VHSI失败: {e}")
            return None
    
    def get_market_sentiment(self) -> Dict:
        """获取市场情绪状态"""
        vhsi = self.get_vhsi()
        thresholds = self.config['sentiment_monitor']['indicators']['VHSI']['thresholds']
        
        if vhsi is None:
            return {"status": "unknown", "vhsi": None, "description": "VHSI数据获取失败"}
        
        if vhsi >= thresholds['extreme_panic']:
            status = "extreme_panic"
        elif vhsi >= thresholds['panic']:
            status = "panic"
        elif vhsi >= thresholds['normal']:
            status = "normal"
        elif vhsi >= thresholds['calm']:
            status = "calm"
        else:
            status = "very_calm"
        
        return {
            "status": status,
            "vhsi": vhsi,
            "description": self._get_sentiment_description(status)
        }
    
    def get_capital_flow(self, stock_code: str) -> Optional[Dict]:
        """获取个股资金流向"""
        try:
            ret, data = self.quote_ctx.get_capital_distribution(stock_code)
            if ret == RET_OK and not data.empty:
                row = data.iloc[0]
                # 计算主力净流入
                super_in = float(row['capital_in_super']) if row['capital_in_super'] else 0
                big_in = float(row['capital_in_big']) if row['capital_in_big'] else 0
                super_out = float(row['capital_out_super']) if row['capital_out_super'] else 0
                big_out = float(row['capital_out_big']) if row['capital_out_big'] else 0
                
                main_net_in = (super_in + big_in) - (super_out + big_out)
                total_in = super_in + big_in + float(row.get('capital_in_mid', 0) or 0) + float(row.get('capital_in_small', 0) or 0)
                total_out = super_out + big_out + float(row.get('capital_out_mid', 0) or 0) + float(row.get('capital_out_small', 0) or 0)
                
                return {
                    "stock_code": stock_code,
                    "main_net_inflow": main_net_in,
                    "total_inflow": total_in,
                    "total_outflow": total_out,
                    "super_in": super_in,
                    "big_in": big_in,
                    "update_time": row.get('update_time', '')
                }
        except Exception as e:
            print(f"⚠️ 获取资金流向失败: {e}")
        return None
    
    def get_hkconnect_flow(self) -> Optional[Dict]:
        """获取港股通资金流向（恒生指数成分股合计）"""
        try:
            # 获取恒生指数成分股
            ret, data = self.quote_ctx.get_plate_stock('HK.HK800000')  # 恒生指数板块
            if ret == RET_OK and not data.empty:
                total_main_inflow = 0
                for _, stock in data.head(10).iterrows():  # 取前10只权重股
                    flow = self.get_capital_flow(stock['code'])
                    if flow:
                        total_main_inflow += flow['main_net_inflow']
                
                return {
                    "hkconnect_main_inflow": total_main_inflow,
                    "status": "inflow" if total_main_inflow > 0 else "outflow",
                    "magnitude": abs(total_main_inflow) / 1e8  # 亿元
                }
        except Exception as e:
            print(f"⚠️ 获取港股通流向失败: {e}")
        return None
    
    def get_bull_bear_ratio(self) -> Optional[Dict]:
        """获取牛熊证比例"""
        try:
            ret, (data, has_next, total) = self.quote_ctx.get_warrant()
            if ret == RET_OK and not data.empty:
                # 统计牛证和熊证数量
                bull_count = len(data[data['name'].str.contains('购', na=False)])
                bear_count = len(data[data['name'].str.contains('沽', na=False)])
                
                ratio = bull_count / bear_count if bear_count > 0 else 0
                
                # 判断情绪
                if ratio >= 1.5:
                    sentiment = "bullish"
                    desc = "市场看多"
                elif ratio >= 1.2:
                    sentiment = "slightly_bullish"
                    desc = "市场偏多"
                elif ratio >= 0.8:
                    sentiment = "neutral"
                    desc = "市场中性"
                elif ratio >= 0.7:
                    sentiment = "slightly_bearish"
                    desc = "市场偏空"
                else:
                    sentiment = "bearish"
                    desc = "市场看空"
                
                return {
                    "bull_count": bull_count,
                    "bear_count": bear_count,
                    "ratio": round(ratio, 2),
                    "sentiment": sentiment,
                    "description": desc,
                    "total_warrants": total
                }
        except Exception as e:
            print(f"⚠️ 获取牛熊证比例失败: {e}")
        return None
    
    def _get_sentiment_description(self, status: str) -> str:
        """获取情绪状态描述"""
        descriptions = {
            "extreme_panic": "极度恐慌，建议减半持仓或清仓",
            "panic": "市场恐慌，谨慎操作",
            "normal": "市场情绪正常",
            "calm": "市场情绪平稳",
            "very_calm": "市场非常平静，可能酝酿波动"
        }
        return descriptions.get(status, "未知状态")
    
    # ==================== 评分系统 ====================
    
    def calculate_score(self, stock_code: str, news_score: float = 0, 
                       technical_score: float = 0, sentiment_score: float = 0) -> Dict:
        """计算四源共振评分"""
        weights = self.config['scoring_weights']['weights']
        
        # 加权计算
        total_score = (
            news_score * weights['news'] +
            technical_score * weights['technical'] +
            sentiment_score * weights['sentiment']
        )
        
        # 入场阈值判断
        entry_threshold = 70  # 可从配置读取
        
        return {
            "stock_code": stock_code,
            "news_score": news_score,
            "technical_score": technical_score,
            "sentiment_score": sentiment_score,
            "total_score": round(total_score, 2),
            "weights": weights,
            "should_trade": total_score >= entry_threshold,
            "position_ratio": self._get_position_ratio(total_score)
        }
    
    def _get_position_ratio(self, score: float) -> float:
        """根据评分获取建议仓位比例"""
        if score >= 100:
            return 0.05
        elif score >= 90:
            return 0.04
        elif score >= 80:
            return 0.03
        elif score >= 70:
            return 0.02
        else:
            return 0
    
    # ==================== 技术指标验证 ====================
    
    def get_technical_indicators(self, stock_code: str) -> Dict:
        """获取技术指标"""
        try:
            # 获取K线数据
            ret, data, _ = self.quote_ctx.request_history_kline(
                code=stock_code,
                start=(date.today() - timedelta(days=60)).strftime('%Y-%m-%d'),
                end=date.today().strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != RET_OK or data.empty:
                return {"error": "获取K线数据失败"}
            
            close = data['close']
            volume = data['volume']
            
            # 计算均线
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma30 = close.rolling(30).mean().iloc[-1]
            
            # 计算RSI
            rsi = self._calculate_rsi(close, 14)
            
            # 成交量放大
            avg_volume_30 = volume.rolling(30).mean().iloc[-1]
            volume_ratio = volume.iloc[-1] / avg_volume_30 if avg_volume_30 > 0 else 1
            
            # 技术条件判断
            conditions = {
                "ma_golden_cross": ma5 > ma10,  # 5日线在10日线上方
                "volume_surge": volume_ratio >= 1.5,  # 成交量放大50%
                "rsi_normal": 40 <= rsi <= 60,  # RSI在合理区间
                "above_ma30": close.iloc[-1] > ma30  # 站上30日线
            }
            
            return {
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma30": round(ma30, 2),
                "rsi": round(rsi, 2),
                "volume_ratio": round(volume_ratio, 2),
                "conditions": conditions,
                "technical_score": self._calculate_technical_score(conditions)
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _calculate_rsi(self, prices, period: int = 14) -> float:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    def _calculate_technical_score(self, conditions: Dict) -> float:
        """根据技术条件计算分数"""
        score = 0
        if conditions.get('ma_golden_cross'):
            score += 25
        if conditions.get('volume_surge'):
            score += 25
        if conditions.get('rsi_normal'):
            score += 25
        if conditions.get('above_ma30'):
            score += 25
        return score
    
    # ==================== 风控模块 ====================
    
    def check_risk_control(self) -> Dict:
        """检查风控状态"""
        sentiment = self.get_market_sentiment()
        vhsi_adj = self.config['risk_control']['vhsi_adjustment']
        
        result = {
            "sentiment": sentiment,
            "risk_level": "normal",
            "action": None
        }
        
        if sentiment['vhsi'] and sentiment['vhsi'] >= 40:
            result['risk_level'] = "extreme"
            result['action'] = vhsi_adj['above_40']['action']
        elif sentiment['vhsi'] and sentiment['vhsi'] >= 30:
            result['risk_level'] = "high"
            result['action'] = vhsi_adj['above_30']['action']
        
        return result
    
    def is_trading_time(self) -> bool:
        """检查是否在交易时段"""
        now = datetime.now().time()
        start = dt_time(10, 0)
        end = dt_time(15, 30)
        return start <= now <= end
    
    # ==================== 账户操作 ====================
    
    def get_account_info(self) -> Optional[Dict]:
        """获取账户信息"""
        if not self.trade_ctx or not self.acc_id:
            return None
        
        try:
            ret, data = self.trade_ctx.accinfo_query(acc_id=self.acc_id, trd_env=TrdEnv.SIMULATE)
            if ret == RET_OK and not data.empty:
                return {
                    "total_asset": float(data['total_assets'].iloc[0]) if data['total_assets'].iloc[0] != 'N/A' else 0,
                    "cash": float(data['cash'].iloc[0]) if data['cash'].iloc[0] != 'N/A' else 0,
                    "market_val": float(data['market_val'].iloc[0]) if data['market_val'].iloc[0] != 'N/A' else 0,
                    "frozen_cash": float(data['frozen_cash'].iloc[0]) if data['frozen_cash'].iloc[0] != 'N/A' else 0
                }
        except Exception as e:
            print(f"❌ 获取账户信息失败: {e}")
        
        return None
    
    def get_positions(self) -> List[Dict]:
        """获取持仓列表"""
        if not self.trade_ctx:
            return []
        
        try:
            ret, data = self.trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            if ret == RET_OK and not data.empty:
                positions = []
                for _, row in data.iterrows():
                    positions.append({
                        "code": row['code'],
                        "name": row['stock_name'],
                        "qty": int(row['qty']),
                        "cost_price": float(row['cost_price']),
                        "market_price": float(row['market_price']),
                        "pl_ratio": float(row['pl_ratio']),
                        "pl_val": float(row['pl_val'])
                    })
                return positions
        except Exception as e:
            print(f"❌ 获取持仓失败: {e}")
        
        return []
    
    # ==================== 标的扫描 ====================
    
    def scan_watchlist(self) -> List[Dict]:
        """扫描核心标的池"""
        watchlist = self.config['core_watchlist']['stocks']
        results = []
        
        for stock in watchlist[:5]:  # 限制扫描数量避免API限制
            code = stock['code']
            name = stock['name']
            
            # 获取技术指标
            tech = self.get_technical_indicators(code)
            
            if 'error' not in tech:
                results.append({
                    "code": code,
                    "name": name,
                    "sector": stock['sector'],
                    "technical": tech
                })
        
        return results
    
    # ==================== 日报生成 ====================
    
    def generate_daily_report(self) -> str:
        """生成港股日报"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 收集数据
        sentiment = self.get_market_sentiment()
        risk = self.check_risk_control()
        account = self.get_account_info()
        positions = self.get_positions()
        
        # 生成报告
        vhsi_val = sentiment['vhsi'] if sentiment['vhsi'] else 'N/A'
        risk_action = risk['action'] if risk['action'] else '正常交易'
        total_asset = f"HK${account['total_asset']:,.2f}" if account else 'N/A'
        cash = f"HK${account['cash']:,.2f}" if account else 'N/A'
        market_val = f"HK${account['market_val']:,.2f}" if account else 'N/A'
        
        report = f"""# 港股日报 - {today}

## 一、市场情绪分析

| 指标 | 数值 | 状态 |
|------|------|------|
| VHSI | {vhsi_val} | {sentiment['status']} |
| 风险等级 | {risk['risk_level']} | {risk_action} |

**情绪描述**: {sentiment['description']}

## 二、账户概况

| 项目 | 数值 |
|------|------|
| 总资产 | {total_asset} |
| 可用资金 | {cash} |
| 持仓市值 | {market_val} |

## 三、持仓明细

"""
        
        if positions:
            report += "| 代码 | 名称 | 数量 | 成本价 | 现价 | 盈亏% |\n"
            report += "|------|------|------|--------|------|-------|\n"
            for p in positions:
                report += f"| {p['code']} | {p['name']} | {p['qty']} | {p['cost_price']:.2f} | {p['market_price']:.2f} | {p['pl_ratio']:.2f}% |\n"
        else:
            report += "暂无持仓\n"
        
        report += f"""
## 四、今日操作

无交易记录

## 五、明日关注

核心标的池已监控 {len(self.config['core_watchlist']['stocks'])} 只股票

---
*报告由 OpenClaw 港股策略系统 v1.0 自动生成*
"""
        
        return report


# ==================== 主程序 ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='港股独立策略系统 v1.0')
    parser.add_argument('--action', choices=['sentiment', 'scan', 'account', 'positions', 'report', 'all'], 
                       default='all', help='执行的操作')
    args = parser.parse_args()
    
    strategy = HKStrategy()
    
    if not strategy.connect():
        print("❌ 连接失败，请检查Futu OpenD是否运行")
        sys.exit(1)
    
    try:
        if args.action in ['sentiment', 'all']:
            print("\n" + "="*50)
            print("📊 港股市场情绪")
            print("="*50)
            sentiment = strategy.get_market_sentiment()
            print(f"VHSI: {sentiment['vhsi']}")
            print(f"状态: {sentiment['status']}")
            print(f"描述: {sentiment['description']}")
        
        if args.action in ['account', 'all']:
            print("\n" + "="*50)
            print("💰 账户信息")
            print("="*50)
            account = strategy.get_account_info()
            if account:
                print(f"总资产: HK${account['total_asset']:,.2f}")
                print(f"可用资金: HK${account['cash']:,.2f}")
                print(f"持仓市值: HK${account['market_val']:,.2f}")
        
        if args.action in ['positions', 'all']:
            print("\n" + "="*50)
            print("📋 持仓明细")
            print("="*50)
            positions = strategy.get_positions()
            if positions:
                for p in positions:
                    print(f"{p['code']} {p['name']}: {p['qty']}股, 盈亏 {p['pl_ratio']:.2f}%")
            else:
                print("暂无持仓")
        
        if args.action in ['scan', 'all']:
            print("\n" + "="*50)
            print("🔍 标的扫描")
            print("="*50)
            results = strategy.scan_watchlist()
            for r in results:
                tech = r['technical']
                score = tech.get('technical_score', 0)
                print(f"{r['code']} {r['name']}: 技术分{score}, RSI {tech.get('rsi', 'N/A')}")
        
        if args.action == 'report':
            print("\n" + "="*50)
            print("📄 生成日报")
            print("="*50)
            report = strategy.generate_daily_report()
            print(report)
    
    finally:
        strategy.close()
        print("\n✅ 完成")
