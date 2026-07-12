#!/usr/bin/env python3
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

from runtime_config import FUTU_HOST, FUTU_PORT, PYTHON_BIN, SKILLS_DIR, WORKSPACE_DIR

# 使用LongBridge获取K线数据（本地已有）
sys.path.insert(0, str(WORKSPACE_DIR / 'skills/longbridge/longbridge_cli'))
try:
    from commands.quote import get_config, QuoteContext
    from longbridge.openapi import PERIOD_MAP, AdjustType
    LONGBRIDGE_AVAILABLE = True
except ImportError:
    LONGBRIDGE_AVAILABLE = False

# 备用: Futu API

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
        self.futu_host = FUTU_HOST
        self.futu_port = FUTU_PORT
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
        quote_ctx = getattr(self, 'quote_ctx', None)
        if quote_ctx:
            try:
                quote_ctx.close()
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

    def calc_atr(self, high, low, close, period=14):
        """计算 ATR (Average True Range)。
        2026-06-29 east 补上：原本 HK 版本缺此方法，导致 get_stop_loss/get_take_profit
        抓 'HKTechIndicators object has no attribute calc_atr'。实现与 US 版本一致。
        """
        try:
            if len(high) < period + 1:
                return None
            tr1 = high - low
            tr2 = (high - close.shift()).abs()
            tr3 = (low - close.shift()).abs()
            import pandas as pd
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean()
            value = atr.iloc[-1]
            if value != value:  # NaN 检查
                return None
            return float(value)
        except Exception:
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
    
    def get_llm_snapshot(self, symbol):
        '''Return a compact, real K-line summary for LLM verification.'''
        df = self.get_kline(symbol, 180)
        if df is None or len(df) < 50:
            return {}

        close = self._get_column(df, 'close', 'Close')
        high = self._get_column(df, 'high', 'High')
        low = self._get_column(df, 'low', 'Low')
        volume = self._get_column(df, 'volume', 'Volume')
        if close is None or high is None or low is None:
            return {}

        close = close.astype(float)
        high = high.astype(float)
        low = low.astype(float)
        ma20_series = close.rolling(20).mean()
        ma50_series = close.rolling(50).mean()
        ma20 = float(ma20_series.iloc[-1])
        ma50 = float(ma50_series.iloc[-1])
        last = float(close.iloc[-1])

        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        macd_series = ema_fast - ema_slow
        signal_series = macd_series.ewm(span=9, adjust=False).mean()
        macd = float(macd_series.iloc[-1])
        signal = float(signal_series.iloc[-1])
        prev_macd = float(macd_series.iloc[-2])
        prev_signal = float(signal_series.iloc[-2])
        if prev_macd <= prev_signal and macd > signal:
            macd_state = '金叉'
        elif prev_macd >= prev_signal and macd < signal:
            macd_state = '死叉'
        else:
            macd_state = '多头' if macd >= signal else '空头'

        ma20_prev = float(ma20_series.iloc[-6]) if len(ma20_series.dropna()) >= 6 else ma20
        ma20_slope = ((ma20 / ma20_prev) - 1) * 100 if ma20_prev else 0
        high_20d = float(high.tail(20).max())
        day_high = float(high.iloc[-1])
        atr = self.calc_atr(high, low, close)
        kline_volume_ratio = None
        if volume is not None and len(volume) >= 21:
            volume = volume.astype(float)
            avg_volume = float(volume.iloc[-21:-1].mean())
            if avg_volume > 0:
                kline_volume_ratio = float(volume.iloc[-1]) / avg_volume

        rsi = self.calc_rsi(close)
        rsi_value = round(float(rsi), 2) if rsi is not None and not pd.isna(rsi) else None

        return {
            'ma20': round(ma20, 4),
            'ma50': round(ma50, 4),
            'ma20_slope_pct': round(ma20_slope, 3),
            'rsi': rsi_value,
            'macd': round(macd, 4),
            'macd_signal': round(signal, 4),
            'macd_state': macd_state,
            'kline_volume_ratio': round(kline_volume_ratio, 3) if kline_volume_ratio is not None else None,
            'atr': round(float(atr), 4) if atr is not None else None,
            'return_5d_pct': round(((last / float(close.iloc[-6])) - 1) * 100, 2),
            'return_20d_pct': round(((last / float(close.iloc[-21])) - 1) * 100, 2),
            'distance_20d_high_pct': round(((last / high_20d) - 1) * 100, 2) if high_20d else None,
            'intraday_drawdown_pct': round(((last / day_high) - 1) * 100, 2) if day_high else None,
            'price_above_ma20': last > ma20,
            'price_above_ma50': last > ma50,
        }

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
        _data_ok = 0  # 有几个检查成功拿到了数据
        trend_ok = rsi_ok = volume_ok = enhance_ok = False
        
        # 1. MA趋势检查 (2分)
        ma_trend = self.check_ma_trend(symbol)
        if ma_trend:
            _data_ok += 1
            signals['details']['ma_trend'] = ma_trend
            if ma_trend.get('can_entry', False):
                trend_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ MA20上升趋势，价格>MA20")
        
        # 2. RSI检查 (2分) - 区间35-70
        rsi_result = self.check_rsi_entry(symbol)
        if rsi_result:
            _data_ok += 1
            signals['details']['rsi'] = rsi_result
            if rsi_result.get('can_entry', False):
                rsi_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ RSI={rsi_result['rsi']:.1f}在35-70区间")
            else:
                signals['reasons'].append(f"⚠️ RSI={rsi_result['rsi']:.1f}不在35-70区间")
        
        # 3. 成交量检查 (2分) - >=1.5x
        volume_result = self.check_volume(symbol)
        if volume_result:
            _data_ok += 1
            signals['details']['volume'] = volume_result
            if volume_result.get('meets_condition', False):
                volume_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ 成交量放大{volume_result['ratio']:.1f}倍")
            else:
                signals['reasons'].append(f"⚠️ 成交量仅{volume_result['ratio']:.1f}倍，不足1.5倍")
        
        # 4. 增强信号检查 (2分) - >=1个
        enhance = self.check_enhance_signals(symbol)
        if enhance:
            _data_ok += 1
            signals['details']['enhance_signals'] = enhance
            if enhance.get('meets_condition', False):
                enhance_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ 增强信号: {', '.join(enhance['signals'])}")
            else:
                signals['reasons'].append("⚠️ 无增强信号")
        
        # 入场硬门槛：趋势、RSI、成交量、增强信号均须合格。
        signals['can_enter'] = trend_ok and rsi_ok and volume_ok and enhance_ok
        if _data_ok > 0 and not signals['can_enter']:
            signals['reasons'].append('⛔ 港股入场硬门槛未全部满足')

        # 只有数据全部获取失败（K线不足/断连）时才用备用源，不是技术面差的时候
        if _data_ok == 0:
            fallback = self._technical_anomaly_fallback(symbol)
            if fallback:
                signals['score'] = fallback['score']
                signals['can_enter'] = fallback['score'] >= 4
                signals['reasons'].extend(fallback['reasons'])
                signals['details']['tech_anomaly_fallback'] = fallback['detail']

        return signals

    def _technical_anomaly_fallback(self, symbol):
        """技术异动备用源（futu-technical-anomaly skill）。

        自己算的 MA/RSI/MACD 全失败时，调 futu 技术异动接口拿文本，
        按关键词判定看多/看空，返回分数和理由。
        """
        import subprocess, json as _json
        FUTU_TECH_SCRIPT = str(SKILLS_DIR / 'futu-technical-anomaly/scripts/handle_technical_anomaly.py')
        FUTU_PY = str(PYTHON_BIN)
        _POS = ['金叉', '看涨', '多头占优', '上涨', '突破', '超卖区反弹', '上涨概率']
        _NEG = ['死叉', '超买', '回调风险', '下行趋势']
        try:
            clean = str(symbol).replace('US.', '').replace('HK.', '').split('.')[0]
            futu_sym = f'HK.{clean}'
            proc = subprocess.run(
                [FUTU_PY, FUTU_TECH_SCRIPT, futu_sym, '--time-range', '7',
                 '--indicator-filters', 'MACD', 'RSI6', 'RSI12', 'MA', '--json'],
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode != 0:
                return None
            stdout = proc.stdout.strip()
            json_start = stdout.find('{')
            if json_start < 0:
                return None
            payload, _end = _json.JSONDecoder().raw_decode(stdout[json_start:])
            data = payload.get('data') or {}
            if str(data.get('err_code', -1)) != '0':
                return None
            content = data.get('content') or ''
            if not content:
                return None
            low = content.lower()
            pos_hits = sum(1 for w in _POS if w in low)
            neg_hits = sum(1 for w in _NEG if w in low)
            evidence = content.replace('\n', ' ')[:120]
            if pos_hits > neg_hits:
                print(f"   📈 技术异动备用: 看多 (正{pos_hits}/负{neg_hits})")
                return {
                    'score': 3,
                    'reasons': [f"✅ [Futu技术异动] 看多信号(正{pos_hits}/负{neg_hits}): {evidence}"],
                    'detail': {'direction': '看多', 'pos_hits': pos_hits, 'neg_hits': neg_hits, 'content': evidence},
                }
            elif neg_hits > pos_hits:
                print(f"   📉 技术异动备用: 看空 (正{pos_hits}/负{neg_hits})")
                return {
                    'score': 0,
                    'reasons': [f"⚠️ [Futu技术异动] 看空信号(正{pos_hits}/负{neg_hits}): {evidence}"],
                    'detail': {'direction': '看空', 'pos_hits': pos_hits, 'neg_hits': neg_hits, 'content': evidence},
                }
            else:
                return {
                    'score': 1,
                    'reasons': [f"⚪ [Futu技术异动] 中性(正{pos_hits}/负{neg_hits}): {evidence}"],
                    'detail': {'direction': '中性', 'pos_hits': pos_hits, 'neg_hits': neg_hits, 'content': evidence},
                }
        except Exception as e:
            print(f"   ⚠️ 技术异动备用源失败: {e}")
            return None
    
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