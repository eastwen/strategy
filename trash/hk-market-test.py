#!/usr/bin/env python3
"""
港股全市场测试 - 扩大标的池
测试不同行业和市值股票
"""

import sys
import json
from datetime import datetime, date, timedelta

# 导入数据分析库
try:
    import pandas as pd
    import numpy as np
except ImportError as e:
    print(f"❌ 缺少依赖库: {e}")
    print("请安装: pip install pandas numpy")
    sys.exit(1)

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

class HKMarketTester:
    """港股全市场测试器"""
    
    def __init__(self):
        self.quote_ctx = None
        
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
    
    def get_stock_categories(self) -> Dict[str, List[tuple]]:
        """定义港股不同类别股票"""
        return {
            "科技龙头": [
                ("HK.00700", "腾讯控股"),
                ("HK.09988", "阿里巴巴-SW"),
                ("HK.03690", "美团-W"),
                ("HK.09888", "百度集团-SW"),
                ("HK.09999", "网易-S"),
                ("HK.09618", "京东集团-SW"),
            ],
            "金融股": [
                ("HK.00005", "汇丰控股"),
                ("HK.01299", "友邦保险"),
                ("HK.00388", "香港交易所"),
                ("HK.00939", "建设银行"),
                ("HK.01398", "工商银行"),
                ("HK.03988", "中国银行"),
            ],
            "消费股": [
                ("HK.02319", "蒙牛乳业"),
                ("HK.02020", "安踏体育"),
                ("HK.02331", "李宁"),
                ("HK.00357", "美兰空港"),
                ("HK.01579", "颐海国际"),
                ("HK.01068", "中国飞鹤"),
            ],
            "地产股": [
                ("HK.00016", "新鸿基地产"),
                ("HK.01113", "长实集团"),
                ("HK.00960", "龙湖集团"),
                ("HK.03333", "中国恒大"),
                ("HK.02007", "碧桂园"),
                ("HK.00688", "中国海外发展"),
            ],
            "医药股": [
                ("HK.02269", "药明生物"),
                ("HK.01093", "石药集团"),
                ("HK.03692", "翰森制药"),
                ("HK.01548", "金斯瑞生物科技"),
                ("HK.01877", "君实生物"),
                ("HK.06969", "思摩尔国际"),
            ],
            "工业股": [
                ("HK.00669", "创科实业"),
                ("HK.00868", "信义玻璃"),
                ("HK.02382", "舜宇光学科技"),
                ("HK.02313", "申洲国际"),
                ("HK.00968", "信义光能"),
                ("HK.02018", "瑞声科技"),
            ]
        }
    
    def test_single_stock(self, stock_code: str, stock_name: str) -> Dict:
        """测试单只股票"""
        try:
            # 获取90天数据
            ret, data, _ = self.quote_ctx.request_history_kline(
                code=stock_code,
                start=(date.today() - timedelta(days=120)).strftime('%Y-%m-%d'),
                end=date.today().strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != RET_OK or data.empty or len(data) < 30:
                return {"stock": stock_code, "name": stock_name, "error": "数据不足"}
            
            close = data['close']
            volume = data['volume']
            
            # 计算技术指标
            # 1. 价格表现
            start_price = close.iloc[0]
            end_price = close.iloc[-1]
            price_change = (end_price - start_price) / start_price * 100
            
            # 2. 波动率（最近20天）
            recent_close = close.iloc[-20:] if len(close) >= 20 else close
            volatility = recent_close.pct_change().std() * np.sqrt(252) * 100
            
            # 3. 成交量放大信号数
            vol_ma10 = volume.rolling(10).mean()
            vol_surge_signals = (volume > vol_ma10 * 1.3).sum()
            vol_days = len(volume)
            surge_ratio = vol_surge_signals / vol_days * 100
            
            # 4. 均线金叉信号数
            ma5 = close.rolling(5).mean()
            ma10 = close.rolling(10).mean()
            ma_cross_signals = ((ma5 > ma10) & (ma5.shift(1) <= ma10.shift(1))).sum()
            
            # 5. RSI超卖超买信号
            rsi = self._calculate_rsi_series(close, 14)
            oversold_signals = (rsi < 30).sum()
            overbought_signals = (rsi > 70).sum()
            
            # 6. 市值信息
            ret2, snapshot = self.quote_ctx.get_market_snapshot([stock_code])
            market_cap = None
            turnover = None
            if ret2 == RET_OK and not snapshot.empty:
                market_cap = snapshot.iloc[0].get('market_val', 0) / 1e9  # 十亿港元
                turnover = snapshot.iloc[0].get('turnover_rate', 0)  # 换手率
            
            return {
                "stock": stock_code,
                "name": stock_name,
                "price_change_90d": round(price_change, 2),
                "volatility": round(volatility, 2),
                "total_days": vol_days,
                "vol_surge_signals": int(vol_surge_signals),
                "vol_surge_ratio": round(surge_ratio, 1),
                "ma_cross_signals": int(ma_cross_signals),
                "rsi_oversold": int(oversold_signals),
                "rsi_overbought": int(overbought_signals),
                "market_cap_bn": round(market_cap, 1) if market_cap else None,
                "turnover_rate": round(turnover, 2) if turnover else None,
                "avg_price": round(close.mean(), 2),
                "strategy_suitability": self._assess_strategy_suitability(
                    vol_surge_signals, ma_cross_signals, volatility
                )
            }
            
        except Exception as e:
            return {"stock": stock_code, "name": stock_name, "error": str(e)}
    
    def _calculate_rsi_series(self, prices, period: int = 14):
        """计算RSI序列"""
        if len(prices) < period:
            return pd.Series([50] * len(prices))
        
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)
    
    def _assess_strategy_suitability(self, vol_signals, ma_signals, volatility):
        """评估策略适应性"""
        # 适合策略的条件：
        # 1. 成交量放大信号多
        # 2. 均线金叉信号适中
        # 3. 波动率适中
        
        if vol_signals < 5:
            return "不适合 (量能信号少)"
        elif volatility > 50:
            return "高风险 (波动率>50%)"
        elif volatility < 15:
            return "低波动 (信号少)"
        elif ma_signals >= 3:
            return "适合 (量能+趋势)"
        else:
            return "一般 (量能为主)"
    
    def run_full_test(self):
        """运行全市场测试"""
        if not self.connect():
            return
        
        categories = self.get_stock_categories()
        
        print(f"\n{'='*70}")
        print("🇭🇰 港股全市场策略适应性测试")
        print(f"{'='*70}")
        print("测试维度：成交量放大、均线金叉、RSI信号、波动率")
        print(f"{'='*70}")
        
        all_results = {}
        
        for category, stocks in categories.items():
            print(f"\n📊 测试类别: {category} ({len(stocks)}只)")
            print(f"{'-'*70}")
            
            category_results = []
            for code, name in stocks:
                result = self.test_single_stock(code, name)
                category_results.append(result)
                
                if "error" in result:
                    print(f"  {name:<15} ❌ {result['error']}")
                else:
                    suitability = result['strategy_suitability']
                    marker = "✅" if "适合" in suitability else "⚠️" if "一般" in suitability else "❌"
                    print(f"  {name:<15} {marker} 价格:{result['price_change_90d']:>+6.1f}% 波动:{result['volatility']:>5.1f}% 量能信号:{result['vol_surge_signals']:>2d} 适应性:{suitability}")
            
            # 分析类别适合度
            suitable = [r for r in category_results if "适合" in r.get('strategy_suitability', '')]
            total = len([r for r in category_results if 'error' not in r])
            if total > 0:
                suitability_rate = len(suitable) / total * 100
                print(f"  📈 类别适合度: {suitability_rate:.0f}% ({len(suitable)}/{total})")
            
            all_results[category] = category_results
        
        # 汇总分析
        print(f"\n{'='*70}")
        print("📊 策略适应性汇总")
        print(f"{'='*70}")
        
        total_stocks = 0
        total_suitable = 0
        
        for category, results in all_results.items():
            valid_results = [r for r in results if 'error' not in r]
            if valid_results:
                suitable = [r for r in valid_results if "适合" in r.get('strategy_suitability', '')]
                rate = len(suitable) / len(valid_results) * 100
                total_stocks += len(valid_results)
                total_suitable += len(suitable)
                
                print(f"{category:<12}: {len(suitable):>2d}/{len(valid_results):>2d} ({rate:>5.1f}%) 适合")
        
        if total_stocks > 0:
            overall_rate = total_suitable / total_stocks * 100
            print(f"{'='*70}")
            print(f"🏆 总体适合度: {total_suitable}/{total_stocks} ({overall_rate:.1f}%)")
            
            # 推荐标的
            print(f"\n{'='*70}")
            print("🚀 推荐标的 (策略适应性高)")
            print(f"{'='*70}")
            print(f"{'股票':<15} {'类别':<10} {'价格变动':<8} {'波动率':<8} {'量能信号':<8} {'换手率':<8}")
            print(f"{'-'*70}")
            
            recommendations = []
            for category, results in all_results.items():
                for r in results:
                    if 'error' not in r and "适合" in r.get('strategy_suitability', ''):
                        recommendations.append(r)
            
            # 按量能信号排序
            recommendations.sort(key=lambda x: x.get('vol_surge_signals', 0), reverse=True)
            
            for r in recommendations[:10]:  # 显示前10个
                print(f"{r['name']:<15} {r.get('category', 'N/A'):<10} {r['price_change_90d']:>+7.1f}% {r['volatility']:>7.1f}% {r['vol_surge_signals']:>9d} {r.get('turnover_rate', 0):>8.1f}%")
        
        self.close()


def main():
    """主函数"""
    # 导入所需库
    try:
        import pandas as pd
        import numpy as np
    except ImportError as e:
        print(f"❌ 缺少依赖库: {e}")
        print("请安装: pip install pandas numpy")
        return
    
    print("\n" + "="*70)
    print("🎯 港股策略全市场适应性测试")
    print("="*70)
    print("目标：找出最适合当前策略的股票类别和标的")
    print("测试股票数: 36只 (6个行业 × 6只代表股)")
    print("="*70)
    
    tester = HKMarketTester()
    tester.run_full_test()


if __name__ == '__main__':
    main()