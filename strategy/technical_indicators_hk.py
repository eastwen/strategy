#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
港股技术指标计算模块
港股策略v2.0专用

数据来源: LongBridge (本地已有) 或 Futu
- K线数据获取

入场条件:
- MA20上升趋势, 价格 > MA20
- RSI区间: 35-70
- 成交量 >= 1.5x
- 增强信号: >=1个 (突破高点 或 布林收缩)

出场条件:
- 止损: ATR 1.5x
- 止盈: ATR 3.0x
- RSI超买: > 70
- 最大持仓10天
"""

import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

# 使用LongBridge获取K线数据（本地已有）
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/skills/longbridge/longbridge_cli')
try:
    from commands.quote import get_config, QuoteContext
    from longbridge.openapi import PERIOD_MAP, AdjustType
    LONGBRIDGE_AVAILABLE = True
except ImportError:
    LONGBRIDGE_AVAILABLE = False

# 备用: Futu API
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext


class HKTechIndicators:
    """港股技术指标计算类
    
    策略v2.0要求:
    入场:
    - 趋势: MA20上升, 价格 > MA20
    - RSI: 35-70
    - 成交量: >= 1.5x
    - 增强信号: >=1个
    
    出场:
    - 止损: ATR 1.5x
    - 止盈: ATR 3.0x
    - RSI > 70
    - 最大持仓10天
    """
    
    def __init__(self):
        """初始化Futu连接"""
        self.futu_host = '127.0.0.1'
        self.futu_port = 11111
        self.quote_ctx = None
        self._connect_futu()
    
    def _connect_futu(self):
        """连接Futu OpenD"""
        try:
            self.quote_ctx = OpenQuoteContext(self.futu_host, self.futu_port)
        except Exception as e:
            print(f"⚠️ Futu连接失败: {e}")
            self.quote_ctx = None
    
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            try:
                self.quote_ctx.close()
            except:
                pass
    
    def __del__(self):
        """关闭连接"""
        self.close()
    
    def _get_column(self, df, *names):
        """安全获取列（尝试多种可能的列名）"""
        for name in names:
            if name in df.columns:
                return df[name]
        return None
    
    def calc_rsi(self, close, period=14):
        """计算RSI指标"""
        try:
            deltas = close.diff()
            gains = deltas.clip(lower=0).rolling(period).mean()
            losses = (-deltas.clip(upper=0)).rolling(period).mean()
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None
        except:
            return None
    
    def calc_volume_ratio(self, volume, period=5):
        """计算成交量比率（当前/平均）"""
        try:
            avg_volume = volume.iloc[-period:].mean()
            if avg_volume == 0:
                return None
            return volume.iloc[-1] / avg_volume
        except:
            return None
    
    def calc_bollinger(self, close, period=20, std_dev=2):
        """计算布林带"""
        try:
            middle = close.rolling(period).mean()
            std = close.rolling(period).std()
            upper = middle + std_dev * std
            lower = middle - std_dev * std
            return {
                'upper': upper.iloc[-1],
                'middle': middle.iloc[-1],
                'lower': lower.iloc[-1]
            }
        except:
            return None
    
    def get_kline(self, symbol, days=90):
        """获取港股K线数据 - 使用LongBridge优先，备选Futu"""
        
        # 方法1: 使用LongBridge (本地已有)
        if LONGBRIDGE_AVAILABLE:
            try:
                # 标准化symbol格式 (港股)
                lb_symbol = symbol
                if not lb_symbol.endswith('.HK'):
                    if '.' not in lb_symbol and lb_symbol.isdigit():
                        lb_symbol = f"{lb_symbol}.HK"
                
                ctx = QuoteContext(get_config())
                resp = ctx.candlesticks(lb_symbol, PERIOD_MAP["day"], days, AdjustType.NoAdjust)
                
                if resp and len(resp) > 0:
                    data = []
                    for c in resp:
                        data.append({
                            'time': c.timestamp,
                            'open': float(c.open),
                            'high': float(c.high),
                            'low': float(c.low),
                            'close': float(c.close),
                            'volume': float(c.volume)
                        })
                    
                    df = pd.DataFrame(data)
                    df = df.sort_values('time')
                    return df
            except Exception as e:
                print(f"  ⚠️ LongBridge获取失败: {e}, 尝试备选方案...")
        
        # 方法2: 使用Futu API (备选)
        if self.quote_ctx:
            try:
                futu_symbol = symbol
                if not futu_symbol.startswith('HK.'):
                    if futu_symbol.isdigit():
                        futu_symbol = f'HK.{futu_symbol}'
                
                ret, df, extra = self.quote_ctx.request_history_kline(
                    futu_symbol,
                    start='',
                    end='',
                    max_count=days,
                    autype='qfq'
                )
                
                if ret == 0 and df is not None and not df.empty:
                    # 统一列名：Futu用time_key，LongBridge用timestamp
                    if 'time_key' in df.columns:
                        df = df.rename(columns={'time_key': 'time'})
                    elif 'timestamp' in df.columns:
                        df = df.rename(columns={'timestamp': 'time'})
                    # 统一列名为小写
                    df.columns = df.columns.str.lower()
                    return df.sort_values('time')
            except Exception as e:
                print(f"  ⚠️ Futu获取也失败: {e}")
        
        return None
    
    def check_ma_trend(self, symbol):
        """检查MA20趋势: 上升且价格 > MA20"""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 25:
            return None
        
        close = self._get_column(df, 'close', 'Close')
        if close is None:
            return None
        
        ma20 = close.rolling(20).mean()
        
        # MA20趋势: 最近3天持续上升
        ma20_now = ma20.iloc[-1]
        ma20_prev = ma20.iloc[-2]
        ma20_prev2 = ma20.iloc[-3]
        
        trend_up = ma20_now > ma20_prev > ma20_prev2
        price_above_ma20 = close.iloc[-1] > ma20_now
        
        return {
            'trend': 'up' if trend_up else 'down',
            'ma20': ma20_now,
            'price': close.iloc[-1],
            'above_ma20': price_above_ma20,
            'can_entry': trend_up and price_above_ma20
        }
    
    def check_rsi_entry(self, symbol):
        """检查RSI入场条件: 35-70"""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 20:
            return None
        
        close = self._get_column(df, 'close', 'Close')
        if close is None:
            return None
        
        rsi = self.calc_rsi(close)
        
        if rsi is None:
            return None
        
        # 港股RSI区间: 35-70
        in_range = 35 <= rsi <= 70
        
        return {
            'rsi': rsi,
            'in_range': in_range,
            'can_entry': in_range,
            'status': 'oversold' if rsi < 35 else ('overbought' if rsi > 70 else 'neutral')
        }
    
    def check_volume(self, symbol, min_ratio=1.5):
        """检查成交量: >=1.5倍"""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 21:
            return None
        
        volume = self._get_column(df, 'volume', 'Volume')
        if volume is None:
            return None
        
        volume_ratio = self.calc_volume_ratio(volume)
        
        if volume_ratio is None:
            return None
        
        return {
            'ratio': volume_ratio,
            'meets_condition': volume_ratio >= min_ratio,
            'min_required': min_ratio
        }
    
    def check_enhance_signals(self, symbol):
        """检查增强信号: 突破高点 或 布林收缩
        
        返回增强信号数量 (需要 >=1)
        """
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 25:
            return {'count': 0, 'signals': []}
        
        close = self._get_column(df, 'close', 'Close')
        high = self._get_column(df, 'high', 'High')
        
        if close is None or high is None:
            return {'count': 0, 'signals': []}
        
        signals = []
        
        # 信号1: 突破10日高点
        highest_10d = high.iloc[-10:].max()
        if close.iloc[-1] > highest_10d:
            signals.append('突破10日高点')
        
        # 信号2: 布林带收缩 (queeze)
        bb = self.calc_bollinger(close, period=20)
        if bb:
            # 当前带宽
            bandwidth = (bb['upper'] - bb['lower']) / bb['middle']
            # 历史平均带宽（取最后20天的平均值）
            bb_std = close.iloc[-20:].std()
            bb_ma = close.iloc[-20:].mean()
            hist_bandwidth = (4 * bb_std) / bb_ma  # 简化计算
            
            if bandwidth < hist_bandwidth * 0.8:
                signals.append('布林收缩')
        
        return {
            'count': len(signals),
            'signals': signals,
            'meets_condition': len(signals) >= 1
        }
    
    def get_entry_signals(self, symbol):
        """获取完整的入场技术信号"""
        signals = {
            'market': 'HK',
            'score': 0,
            'max_score': 6,  # MA + RSI + 成交量 + 增强信号 + 2备用
            'details': {},
            'can_enter': False,
            'reasons': []
        }
        
        # 1. MA趋势检查 (2分)
        ma_trend = self.check_ma_trend(symbol)
        if ma_trend:
            signals['details']['ma_trend'] = ma_trend
            if ma_trend.get('can_entry', False):
                signals['score'] += 2
                signals['reasons'].append(f"✅ MA20上升趋势，价格>MA20")
        
        # 2. RSI检查 (2分) - 区间35-70
        rsi_result = self.check_rsi_entry(symbol)
        if rsi_result:
            signals['details']['rsi'] = rsi_result
            if rsi_result.get('can_entry', False):
                signals['score'] += 2
                signals['reasons'].append(f"✅ RSI={rsi_result['rsi']:.1f}在35-70区间")
            else:
                signals['reasons'].append(f"⚠️ RSI={rsi_result['rsi']:.1f}不在35-70区间")
        
        # 3. 成交量检查 (2分) - >=1.5x
        volume_result = self.check_volume(symbol)
        if volume_result:
            signals['details']['volume'] = volume_result
            if volume_result.get('meets_condition', False):
                signals['score'] += 2
                signals['reasons'].append(f"✅ 成交量放大{volume_result['ratio']:.1f}倍")
            else:
                signals['reasons'].append(f"⚠️ 成交量仅{volume_result['ratio']:.1f}倍，不足1.5倍")
        
        # 4. 增强信号检查 (2分) - >=1个
        enhance = self.check_enhance_signals(symbol)
        if enhance:
            signals['details']['enhance_signals'] = enhance
            if enhance.get('meets_condition', False):
                signals['score'] += 2
                signals['reasons'].append(f"✅ 增强信号: {', '.join(enhance['signals'])}")
            else:
                signals['reasons'].append("⚠️ 无增强信号")
        
        # 入场条件: 至少4分 (至少2个条件满足)
        signals['can_enter'] = signals['score'] >= 4
        
        return signals
    
    def get_stop_loss(self, symbol, multiplier=1.5):
        """计算ATR止损价格 (1.5x)"""
        df = self.get_kline(symbol, 60)
        if df is None:
            return None
        
        close = self._get_column(df, 'close', 'Close')
        high = self._get_column(df, 'high', 'High')
        low = self._get_column(df, 'low', 'Low')
        
        if close is None or high is None or low is None:
            return None
        
        atr = self.calc_atr(high, low, close)
        if atr is None:
            return None
        
        current_price = close.iloc[-1]
        return current_price - (atr * multiplier)
    
    def get_take_profit(self, symbol, multiplier=3.0):
        """计算ATR止盈价格 (3.0x)"""
        df = self.get_kline(symbol, 60)
        if df is None:
            return None
        
        close = self._get_column(df, 'close', 'Close')
        high = self._get_column(df, 'high', 'High')
        low = self._get_column(df, 'low', 'Low')
        
        if close is None or high is None or low is None:
            return None
        
        atr = self.calc_atr(high, low, close)
        if atr is None:
            return None
        
        current_price = close.iloc[-1]
        return current_price + (atr * multiplier)


# 测试
if __name__ == '__main__':
    ti = HKTechIndicators()
    
    if ti.connect():
        print("✅ 连接成功，测试港股技术指标...")
        
        # 测试港股股票 (腾讯控股)
        signals = ti.get_entry_signals('HK.00700')
        
        print(f"\n📈 港股 (00700) 入场信号:")
        print(f"   技术评分: {signals['score']}/{signals['max_score']}")
        print(f"   可入场: {'✅ 是' if signals['can_enter'] else '❌ 否'}")
        
        for reason in signals['reasons']:
            print(f"   {reason}")
        
        # 测试止损止盈
        sl = ti.get_stop_loss('HK.00700')
        tp = ti.get_take_profit('HK.00700')
        
        print(f"\n🛡️ 止损止盈:")
        if sl:
            print(f"   止损: ${sl:.2f}")
        if tp:
            print(f"   止盈: ${tp:.2f}")
        
        ti.close()
    else:
        print("❌ 连接失败")