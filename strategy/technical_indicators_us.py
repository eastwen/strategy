#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
美股技术指标计算模块
美股策略v1.6专用

数据来源: LongBridge (本地已有，无需额外配置)
- K线数据获取

入场条件:
- MA20 > MA50, 价格 > MA20
- 技术信号 >= 2
- 成交量 >= 1.8x
- RSI < 65

出场条件:
- ATR止损 (1.8-2.0x)
- ATR止盈 (4.0-4.5x)
- RSI > 70
- MACD死叉
- 最大持仓6天
"""

import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

# yfinance (主数据源)
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

class USTechIndicators:
    """美股技术指标计算类
    
    策略v1.6要求:
    - 趋势: MA20 > MA50, 价格 > MA20
    - 技术信号: >= 2
    - 成交量: >= 1.8x
    - RSI: < 65
    
    出场:
    - 止损: ATR 1.8-2.0x
    - 止盈: ATR 4.0-4.5x
    - RSI > 70
    - MACD死叉
    - 最大持仓6天
    """
    
    def __init__(self):
        pass
    
    def close(self):
        pass
    
    def get_kline(self, symbol, days=90):
        """获取K线数据 - 使用yfinance（免费）优先"""
        
        # 方法1: 使用yfinance (主，免费)
        try:
            import yfinance as yf
            
            # yfinance用 AAPL 格式，不需要 US. 前缀
            yf_symbol = symbol
            if yf_symbol.startswith('US.'):
                yf_symbol = yf_symbol[3:]  # 去掉US.前缀
            
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=f'{days}d', auto_adjust=True)
            
            if not df.empty:
                # yfinance返回的列名是大写，需要转换为小写
                df = df.reset_index()
                df.columns = [c.lower() for c in df.columns]
                # 去掉多余的列
                cols_to_keep = ['date', 'open', 'high', 'low', 'close', 'volume']
                df = df[[c for c in cols_to_keep if c in df.columns]]
                df = df.sort_values('date')
                return df
                return df
        except Exception as e:
            print(f"  ⚠️ yfinance获取失败: {e}")
        return None
    
    def calc_ma(self, close, period):
        """计算MA"""
        if len(close) < period:
            return None
        return close.rolling(period).mean().iloc[-1]
    
    def calc_rsi(self, close, period=14):
        """计算RSI"""
        if len(close) < period + 1:
            return None
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    def calc_atr(self, high, low, close, period=14):
        """计算ATR"""
        if len(high) < period + 1:
            return None
        
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr.iloc[-1]
    
    def calc_macd(self, close, fast=12, slow=26, signal=9):
        """计算MACD"""
        if len(close) < slow + signal:
            return None
        
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        
        return {
            'macd': macd.iloc[-1],
            'signal': signal_line.iloc[-1],
            'prev_macd': macd.iloc[-2],
            'prev_signal': signal_line.iloc[-2]
        }
    
    def check_trend(self, symbol):
        """检查MA趋势：MA20 > MA50"""
        df = self.get_kline(symbol, 180)
        if df is None or len(df) < 50:
            return None
        
        close = df['close']
        ma20 = self.calc_ma(close, 20)
        ma50 = self.calc_ma(close, 50)
        price = close.iloc[-1]
        
        if ma20 is None or ma50 is None:
            return None
        
        return {
            'trend': 'up' if ma20 > ma50 else 'down',
            'ma20': ma20,
            'ma50': ma50,
            'price': price,
            'above_ma20': price > ma20
        }
    
    def check_rsi(self, symbol):
        """检查RSI"""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 15:
            return None
        
        rsi = self.calc_rsi(df['close'])
        return rsi
    
    def check_volume(self, symbol):
        """检查成交量是否放大1.8倍"""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 21:
            return None
        
        current_vol = df['volume'].iloc[-1]
        avg_vol = df['volume'].rolling(20).mean().iloc[-1]
        
        if avg_vol == 0:
            return None
        
        return current_vol / avg_vol
    
    def check_macd_death_cross(self, symbol):
        """检查MACD死叉"""
        df = self.get_kline(symbol, 90)
        if df is None or len(df) < 35:
            return None
        
        macd_data = self.calc_macd(df['close'])
        if macd_data is None:
            return None
        
        # 死叉：MACD从上方穿过到下方
        macd_above_prev = macd_data['prev_macd'] > macd_data['prev_signal']
        macd_below_now = macd_data['macd'] < macd_data['signal']
        
        return macd_above_prev and macd_below_now
    
    def get_entry_signals(self, symbol):
        """获取入场技术信号"""
        signals = {
            'score': 0,
            'details': {},
            'can_enter': False,
            'reasons': []
        }
        
        # 1. MA趋势检查 (2分)
        ma_trend = self.check_trend(symbol)
        if ma_trend:
            signals['details']['ma_trend'] = ma_trend
            if ma_trend['trend'] == 'up' and ma_trend['above_ma20']:
                signals['score'] += 2
                signals['reasons'].append(f"✅ MA20>MA50上升趋势 (MA20={ma_trend['ma20']:.2f}, MA50={ma_trend['ma50']:.2f})")
        
        # 2. RSI检查 (2分)
        rsi = self.check_rsi(symbol)
        if rsi:
            signals['details']['rsi'] = rsi
            if rsi < 65:
                signals['score'] += 2
                signals['reasons'].append(f"✅ RSI={rsi:.1f}<65，可入场")
            else:
                signals['reasons'].append(f"⚠️ RSI={rsi:.1f}≥65，不建议入场")
        
        # 3. 成交量检查 (2分)
        vol_ratio = self.check_volume(symbol)
        if vol_ratio:
            signals['details']['volume'] = vol_ratio
            if vol_ratio >= 1.8:
                signals['score'] += 2
                signals['reasons'].append(f"✅ 成交量放大{vol_ratio:.1f}倍")
            else:
                signals['reasons'].append(f"⚠️ 成交量仅{vol_ratio:.1f}倍，不足1.8倍")
        
        # 4. MACD检查 (2分) - 无死叉
        try:
            death_cross = self.check_macd_death_cross(symbol)
            if death_cross is not None:
                signals['details']['macd_death_cross'] = death_cross
                if not death_cross:
                    signals['score'] += 2
                    signals['reasons'].append("✅ MACD无死叉")
                else:
                    signals['reasons'].append("⚠️ MACD出现死叉")
        except:
            pass
        
        # 入场条件：技术信号≥2分
        signals['can_enter'] = signals['score'] >= 2
        
        return signals
    
    def get_stop_loss(self, symbol, multiplier=1.8):
        """计算ATR止损价格"""
        df = self.get_kline(symbol, 60)
        if df is None:
            return None
        
        atr = self.calc_atr(df['high'], df['low'], df['close'])
        if atr is None:
            return None
        
        current_price = df['close'].iloc[-1]
        return current_price - (atr * multiplier)
    
    def get_take_profit(self, symbol, multiplier=4.0):
        """计算ATR止盈价格"""
        df = self.get_kline(symbol, 60)
        if df is None:
            return None
        
        atr = self.calc_atr(df['high'], df['low'], df['close'])
        if atr is None:
            return None
        
        current_price = df['close'].iloc[-1]
        return current_price + (atr * multiplier)
    
    def calc_position_size(self, total_assets, price, position_pct=0.12):
        """计算仓位：单票12%"""
        position_value = total_assets * position_pct
        shares = int(position_value / price)
        return shares
    
    def check_total_position_limit(self, current_position_value, total_assets, max_pct=0.40):
        """检查总仓位是否超过40%"""
        if total_assets <= 0:
            return True, "总资产为0"
        
        current_pct = current_position_value / total_assets
        return current_pct >= max_pct, f"当前{current_pct*100:.1f}%"
    
    def calc_profit_pct(self, entry_price, current_price):
        """计算盈利百分比"""
        if entry_price <= 0:
            return 0
        return (current_price - entry_price) / entry_price
    
    def should_take_profit(self, entry_price, current_price, threshold=0.15):
        """检查是否应分批止盈（15%收益）"""
        profit_pct = self.calc_profit_pct(entry_price, current_price)
        return profit_pct >= threshold, profit_pct
    
    def check_holding_days(self, buy_date_str, max_days=6):
        """检查持仓天数"""
        if not buy_date_str:
            return False, 0
        
        try:
            if 'T' in buy_date_str:
                buy_date = datetime.fromisoformat(buy_date_str.replace('Z', '+00:00'))
            else:
                buy_date = datetime.fromisoformat(buy_date_str)
            
            holding_days = (datetime.now() - buy_date).days
            return holding_days >= max_days, holding_days
        except:
            return False, 0


# 测试
if __name__ == '__main__':
    ti = TechIndicators()
    
    if ti.connect():
        print("✅ 连接成功，测试技术指标...")
        
        # 测试获取信号
        signals = ti.get_entry_signals('AAPL')
        
        print(f"\n📈 AAPL 入场信号:")
        print(f"   技术评分: {signals['score']}/8")
        print(f"   可入场: {'✅ 是' if signals['can_enter'] else '❌ 否'}")
        
        for reason in signals['reasons']:
            print(f"   {reason}")
        
        # 测试止损止盈
        sl = ti.get_stop_loss('AAPL')
        tp = ti.get_take_profit('AAPL')
        
        print(f"\n🛡️ 止损止盈 (AAPL):")
        if sl:
            print(f"   止损: ${sl:.2f}")
        if tp:
            print(f"   止盈: ${tp:.2f}")
        
        ti.close()
    else:
        print("❌ 连接失败")