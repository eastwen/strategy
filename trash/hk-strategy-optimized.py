#!/usr/bin/env python3
"""
港股策略 v1.8 - 优化版（基于原v1.0优化）
优化目标：提高信号数量，保持盈利质量
"""

import sys
import os
import json
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

class HKStrategyOptimized:
    """港股策略优化版 v1.8"""
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or '/home/admin/.openclaw/workspace-arashi/config/hk-strategy-optimized.json'
        self.config = self._load_config()
        self.quote_ctx = None
        self.trade_ctx = None
        self.acc_id = None
        
    def _load_config(self) -> dict:
        """加载配置文件"""
        default_config = {
            "version": "1.8",
            "updated": "2026-03-23",
            "name": "港股策略优化版",
            
            "scoring_weights": {
                "description": "优化评分权重 - 情绪优先",
                "weights": {
                    "news": 0.25,      # 降低新闻权重
                    "technical": 0.30,  # 保持技术权重
                    "sentiment": 0.45   # 提高情绪权重（港股情绪驱动）
                }
            },
            
            "entry_threshold": 65,  # 从70降低到65
            
            "technical_conditions": {
                "description": "技术条件 - 更灵活",
                "min_conditions": 1,  # 从2降到1
                "strong_conditions": {
                    "volume_surge": {
                        "name": "成交量放大",
                        "rule": "成交量 ≥ 10日均值 × 1.3",
                        "score": 30
                    },
                    "price_breakout": {
                        "name": "价格突破",
                        "rule": "价格突破5日高点",
                        "score": 25
                    }
                },
                "weak_conditions": {
                    "ma_golden_cross": {
                        "name": "均线金叉",
                        "rule": "5日线 > 10日线",
                        "score": 15
                    },
                    "rsi_ok": {
                        "name": "RSI适中",
                        "rule": "RSI(14) 30-70",
                        "score": 10
                    }
                }
            },
            
            "sentiment_rules": {
                "VHSI": {
                    "extreme_panic": 30,
                    "panic": 25,
                    "normal": 20,
                    "calm": 15
                },
                "vhsi_trading_rule": {
                    "vhsi_lt_20": "正常交易",
                    "vhsi_20_25": "减仓50%",
                    "vhsi_gt_25": "不交易"
                }
            },
            
            "position_sizing": {
                "description": "仓位管理优化",
                "score_range": {
                    "65_75": 0.02,
                    "76_85": 0.03,
                    "86_95": 0.04,
                    "96_100": 0.05
                }
            }
        }
        
        # 如果配置文件不存在，创建默认
        if not os.path.exists(self.config_path):
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            return default_config
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def connect(self) -> bool:
        """连接Futu OpenD"""
        try:
            self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            print("✅ 连接Futu Quote成功")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
    
    # ==================== 情绪监控 ====================
    
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
        thresholds = self.config['sentiment_rules']['VHSI']
        
        if vhsi is None:
            return {"status": "unknown", "vhsi": None, "description": "VHSI数据获取失败"}
        
        if vhsi >= thresholds['extreme_panic']:
            status = "extreme_panic"
        elif vhsi >= thresholds['panic']:
            status = "panic"
        elif vhsi >= thresholds['normal']:
            status = "normal"
        else:
            status = "calm"
        
        return {
            "status": status,
            "vhsi": vhsi,
            "description": self._get_sentiment_description(status),
            "can_trade": vhsi < 25  # VHSI<25才交易
        }
    
    def _get_sentiment_description(self, status: str) -> str:
        """获取情绪状态描述"""
        descriptions = {
            "extreme_panic": "VHSI≥30，极度恐慌，不交易",
            "panic": "VHSI≥25，市场恐慌，谨慎交易",
            "normal": "VHSI 15-20，市场情绪正常",
            "calm": "VHSI<15，市场平静，正常交易"
        }
        return descriptions.get(status, "未知状态")
    
    # ==================== 技术指标 ====================
    
    def get_technical_indicators(self, stock_code: str) -> Dict:
        """获取技术指标（优化版）"""
        try:
            # 获取K线数据（30天足够）
            ret, data, _ = self.quote_ctx.request_history_kline(
                code=stock_code,
                start=(date.today() - timedelta(days=30)).strftime('%Y-%m-%d'),
                end=date.today().strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != RET_OK or data.empty or len(data) < 10:
                return {"error": "获取K线数据失败"}
            
            close = data['close']
            volume = data['volume']
            
            # 计算均线
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            
            # 计算RSI
            rsi = self._calculate_rsi(close, 14)
            
            # 成交量放大（10日均线）
            avg_volume_10 = volume.rolling(10).mean().iloc[-1]
            volume_ratio = volume.iloc[-1] / avg_volume_10 if avg_volume_10 > 0 else 1
            
            # 价格突破5日高点
            high_5 = close.rolling(5).max().iloc[-2]  # 前一日5日高点
            price_breakout = close.iloc[-1] >= high_5
            
            # 均线金叉
            ma_cross = ma5 > ma10
            
            # 计算技术评分（简化版）
            tech_conditions = {
                "volume_surge": volume_ratio >= 1.3,
                "price_breakout": price_breakout,
                "ma_golden_cross": ma_cross,
                "rsi_ok": 30 <= rsi <= 70
            }
            
            technical_score = self._calculate_technical_score_optimized(tech_conditions)
            
            return {
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "rsi": round(rsi, 2),
                "volume_ratio": round(volume_ratio, 2),
                "price_breakout": price_breakout,
                "conditions": tech_conditions,
                "technical_score": technical_score,
                "volume_surge_strength": "强" if volume_ratio >= 1.5 else "中" if volume_ratio >= 1.3 else "弱"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _calculate_rsi(self, prices, period: int = 14) -> float:
        """计算RSI"""
        if len(prices) < period:
            return 50
        
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_technical_score_optimized(self, conditions: Dict) -> float:
        """计算优化版技术评分"""
        score = 50  # 基础分
        
        # 强条件加分多
        if conditions.get('volume_surge'):
            score += 20
        if conditions.get('price_breakout'):
            score += 15
        
        # 弱条件加分少
        if conditions.get('ma_golden_cross'):
            score += 10
        if conditions.get('rsi_ok'):
            score += 5
        
        return min(100, score)  # 不超过100
    
    # ==================== 综合评分 ====================
    
    def calculate_score(self, stock_code: str, technical_score: float = 0) -> Dict:
        """计算综合评分（优化版）"""
        sentiment = self.get_market_sentiment()
        
        # 情绪评分（基于VHSI）
        vhsi = sentiment.get('vhsi')
        if vhsi is None:
            sentiment_score = 50
        elif vhsi < 15:
            sentiment_score = 80  # 市场平静，积极
        elif vhsi < 20:
            sentiment_score = 70  # 正常
        elif vhsi < 25:
            sentiment_score = 60  # 谨慎
        else:
            sentiment_score = 30  # 不交易
        
        # 新闻评分（简化，假设中性）
        news_score = 60
        
        # 权重计算
        weights = self.config['scoring_weights']['weights']
        total_score = (
            news_score * weights['news'] +
            technical_score * weights['technical'] +
            sentiment_score * weights['sentiment']
        )
        
        # 检查是否能交易
        can_trade = sentiment.get('can_trade', False)
        entry_threshold = self.config.get('entry_threshold', 65)
        
        return {
            "stock_code": stock_code,
            "news_score": news_score,
            "technical_score": technical_score,
            "sentiment_score": sentiment_score,
            "total_score": round(total_score, 2),
            "weights": weights,
            "can_trade": can_trade,
            "should_trade": can_trade and total_score >= entry_threshold,
            "position_ratio": self._get_position_ratio(total_score)
        }
    
    def _get_position_ratio(self, score: float) -> float:
        """根据评分获取仓位比例"""
        if score >= 96:
            return 0.05
        elif score >= 86:
            return 0.04
        elif score >= 76:
            return 0.03
        elif score >= 65:
            return 0.02
        else:
            return 0
    
    # ==================== 回测辅助 ====================
    
    def backtest_signal(self, stock_code: str, days_back: int = 90) -> Dict:
        """回测信号生成（简化版）"""
        try:
            # 获取历史数据
            ret, data, _ = self.quote_ctx.request_history_kline(
                code=stock_code,
                start=(date.today() - timedelta(days=days_back)).strftime('%Y-%m-%d'),
                end=date.today().strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != RET_OK or data.empty:
                return {"error": "获取数据失败"}
            
            signals = []
            for i in range(10, len(data)):
                # 模拟每天计算
                close_slice = data['close'].iloc[:i+1]
                volume_slice = data['volume'].iloc[:i+1]
                date_str = data['time_key'].iloc[i]
                
                # 简单信号判断
                if len(close_slice) >= 10:
                    ma5 = close_slice.rolling(5).mean().iloc[-1]
                    ma10 = close_slice.rolling(10).mean().iloc[-1]
                    avg_vol_10 = volume_slice.rolling(10).mean().iloc[-1]
                    vol_ratio = volume_slice.iloc[-1] / avg_vol_10 if avg_vol_10 > 0 else 1
                    
                    # 信号条件（简化）
                    signal = vol_ratio >= 1.3 and ma5 > ma10
                    if signal:
                        signals.append({
                            "date": date_str,
                            "price": close_slice.iloc[-1],
                            "ma5": ma5,
                            "ma10": ma10,
                            "volume_ratio": vol_ratio
                        })
            
            return {
                "stock_code": stock_code,
                "period_days": days_back,
                "total_signals": len(signals),
                "signals": signals[:5]  # 只显示前5个
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    # ==================== 主运行 ====================
    
    def analyze_stock(self, stock_code: str, stock_name: str = "") -> Dict:
        """分析单个股票"""
        if not self.quote_ctx:
            if not self.connect():
                return {"error": "连接失败"}
        
        # 获取情绪
        sentiment = self.get_market_sentiment()
        print(f"\n📊 {stock_name or stock_code} 分析")
        print(f"  VHSI: {sentiment.get('vhsi', 'N/A')} ({sentiment.get('description')})")
        print(f"  可交易: {sentiment.get('can_trade', False)}")
        
        if not sentiment.get('can_trade'):
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "result": "市场情绪不适合交易",
                "sentiment": sentiment,
                "should_trade": False
            }
        
        # 获取技术指标
        technical = self.get_technical_indicators(stock_code)
        if "error" in technical:
            return {"error": technical["error"]}
        
        print(f"  技术评分: {technical['technical_score']}")
        print(f"  成交量放大: {technical['volume_ratio']:.1f}x ({technical['volume_surge_strength']})")
        print(f"  价格突破5日高点: {technical['price_breakout']}")
        print(f"  5日>10日线: {technical['conditions']['ma_golden_cross']}")
        print(f"  RSI: {technical['rsi']}")
        
        # 综合评分
        score_result = self.calculate_score(stock_code, technical['technical_score'])
        
        print(f"  综合评分: {score_result['total_score']}")
        print(f"  建议仓位: {score_result['position_ratio']*100:.1f}%")
        print(f"  是否交易: {score_result['should_trade']}")
        
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "sentiment": sentiment,
            "technical": technical,
            "score": score_result,
            "should_trade": score_result['should_trade'],
            "position_ratio": score_result['position_ratio']
        }


def main():
    """主函数"""
    print("\n" + "="*60)
    print("🇭🇰 港股策略优化版 v1.8")
    print("="*60)
    print("优化点：")
    print("1. 评分阈值从70降至65")
    print("2. 技术条件从至少2个降到至少1个强条件")
    print("3. 情绪权重提高到45%")
    print("4. VHSI≥25时不交易")
    print("5. 成交量要求从1.5x降至1.3x")
    print("="*60)
    
    strategy = HKStrategyOptimized()
    
    if not strategy.connect():
        print("❌ 连接失败")
        return
    
    hk_stocks = [
        ('HK.00700', '腾讯'),
        ('HK.09988', '阿里巴巴'),
        ('HK.03690', '美团'),
        ('HK.09618', '京东健康'),
        ('HK.01810', '小米'),
        ('HK.09999', '网易'),
    ]
    
    results = []
    for code, name in hk_stocks:
        try:
            result = strategy.analyze_stock(code, name)
            results.append(result)
        except Exception as e:
            print(f"❌ {name} 分析失败: {e}")
    
    strategy.close()
    
    # 汇总结果
    print(f"\n{'='*60}")
    print("📊 分析汇总")
    print(f"{'='*60}")
    print(f"\n{'标的':<10} {'可交易':<8} {'技术评分':<8} {'综合评分':<8} {'仓位':<8} {'建议':<10}")
    print('-'*55)
    
    tradable_count = 0
    for r in results:
        if 'error' in r:
            print(f"{r.get('stock_name', '?'):<10} {'❌':<8} {'-':<8} {'-':<8} {'-':<8} {'错误'}")
        else:
            tech_score = r.get('technical', {}).get('technical_score', 0)
            total_score = r.get('score', {}).get('total_score', 0)
            position = r.get('score', {}).get('position_ratio', 0)
            should_trade = r.get('should_trade', False)
            
            if should_trade:
                tradable_count += 1
                advice = '🚀 买入'
                emoji = '✅'
            else:
                advice = '⏸️ 观望'
                emoji = '❌'
            
            print(f"{r.get('stock_name', '?'):<10} {emoji:<8} {tech_score:<8.0f} {total_score:<8.1f} {position*100:<7.1f}% {advice:<10}")
    
    print(f"\n📈 可交易标的: {tradable_count}/{len(hk_stocks)}")
    
    # 回测信号分析
    print(f"\n{'='*60}")
    print("📈 回测信号分析（最近90天）")
    print(f"{'='*60}")
    
    strategy2 = HKStrategyOptimized()
    strategy2.connect()
    
    for code, name in hk_stocks:
        backtest = strategy2.backtest_signal(code)
        if 'error' in backtest:
            print(f"{name}: 回测失败")
        else:
            print(f"{name}: {backtest['total_signals']}个信号")
    
    strategy2.close()


if __name__ == '__main__':
    main()