#!/usr/bin/env python3
"""
美股技术指标计算模块
美股策略v1.6专用

数据来源: LongBridge (本地已有，无需额外配置)
- K线数据获取

入场条件:
- MA20 > MA50, 价格 > MA20
- 技术信号 >= 2
- 成交量 >= 1.2x（>=1.8x为强放量）
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
from zoneinfo import ZoneInfo

from runtime_config import PYTHON_BIN, SKILLS_DIR

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
    - 成交量: >= 1.2x（>=1.8x为强放量）
    - RSI: < 65
    
    出场:
    - 止损: ATR 1.8-2.0x
    - 止盈: ATR 4.0-4.5x
    - RSI > 70
    - MACD死叉
    - 最大持仓6天
    """
    
    def __init__(self):
        self._kline_cache = {}
    
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
            
            cached = self._kline_cache.get(yf_symbol)
            if cached is not None and cached['days'] >= days:
                return cached['data'].copy()

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
                self._kline_cache[yf_symbol] = {'days': days, 'data': df.copy()}
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
        """Project current US daily volume by session progress, then compare with 20 complete sessions."""
        df = self.get_kline(symbol, 60)
        if df is None or len(df) < 21:
            return None

        current_vol = float(df['volume'].iloc[-1] or 0)
        avg_vol = float(df['volume'].iloc[-21:-1].mean() or 0)
        if avg_vol == 0:
            return None

        projected_vol = current_vol
        try:
            last_date = pd.to_datetime(df['date'].iloc[-1]).date()
            now_et = datetime.now(ZoneInfo('America/New_York'))
            if last_date == now_et.date():
                session_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
                session_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
                if session_open <= now_et < session_close:
                    progress = (now_et - session_open).total_seconds() / (session_close - session_open).total_seconds()
                    projected_vol = current_vol / max(0.10, min(1.0, progress))
        except Exception:
            pass
        return projected_vol / avg_vol

    def get_llm_snapshot(self, symbol):
        '''Return a compact, real K-line summary for LLM verification.'''
        df = self.get_kline(symbol, 180)
        if df is None or len(df) < 50:
            return {}

        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        ma20_series = close.rolling(20).mean()
        ma50_series = close.rolling(50).mean()
        ma20 = float(ma20_series.iloc[-1])
        ma50 = float(ma50_series.iloc[-1])
        last = float(close.iloc[-1])

        macd_data = self.calc_macd(close) or {}
        macd = float(macd_data.get('macd', 0))
        signal = float(macd_data.get('signal', 0))
        prev_macd = float(macd_data.get('prev_macd', macd))
        prev_signal = float(macd_data.get('prev_signal', signal))
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
        volume_ratio = self.check_volume(symbol)

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
            'volume_ratio': round(float(volume_ratio), 3) if volume_ratio is not None else None,
            'atr': round(float(atr), 4) if atr is not None else None,
            'return_5d_pct': round(((last / float(close.iloc[-6])) - 1) * 100, 2),
            'return_20d_pct': round(((last / float(close.iloc[-21])) - 1) * 100, 2),
            'distance_20d_high_pct': round(((last / high_20d) - 1) * 100, 2) if high_20d else None,
            'intraday_drawdown_pct': round(((last / day_high) - 1) * 100, 2) if day_high else None,
            'price_above_ma20': last > ma20,
            'price_above_ma50': last > ma50,
        }

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
        _data_ok = 0  # 有几个检查成功拿到了数据
        trend_ok = rsi_ok = volume_ok = False
        
        # 1. MA趋势检查 (2分)
        ma_trend = self.check_trend(symbol)
        if ma_trend:
            _data_ok += 1
            signals['details']['ma_trend'] = ma_trend
            if ma_trend['trend'] == 'up' and ma_trend['above_ma20']:
                trend_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ MA20>MA50上升趋势 (MA20={ma_trend['ma20']:.2f}, MA50={ma_trend['ma50']:.2f})")
            else:
                signals['reasons'].append(
                    f"⚠️ MA趋势未通过 (MA20={ma_trend['ma20']:.2f}, MA50={ma_trend['ma50']:.2f}, "
                    f"价格={ma_trend['price']:.2f})"
                )
        
        # 2. RSI检查 (2分)
        rsi = self.check_rsi(symbol)
        if rsi:
            _data_ok += 1
            signals['details']['rsi'] = rsi
            if rsi < 65:
                rsi_ok = True
                signals['score'] += 2
                signals['reasons'].append(f"✅ RSI={rsi:.1f}<65，可入场")
            else:
                signals['reasons'].append(f"⚠️ RSI={rsi:.1f}≥65，不建议入场")
        
        # 3. 成交量检查 (2分)
        vol_ratio = self.check_volume(symbol)
        if vol_ratio:
            _data_ok += 1
            signals['details']['volume'] = vol_ratio
            if vol_ratio >= 1.2:
                volume_ok = True
                if vol_ratio >= 1.8:
                    signals['score'] += 2
                    signals['reasons'].append(f"✅ 强放量{vol_ratio:.1f}倍")
                else:
                    signals['score'] += 1
                    signals['reasons'].append(f"✅ 成交量{vol_ratio:.1f}倍，达到1.2倍入场门槛")
            else:
                signals['reasons'].append(f"⚠️ 成交量仅{vol_ratio:.1f}倍，不足1.2倍")
        
        # 4. MACD检查 (2分) - 无死叉
        try:
            death_cross = self.check_macd_death_cross(symbol)
            if death_cross is not None:
                _data_ok += 1
                signals['details']['macd_death_cross'] = death_cross
                if not death_cross:
                    signals['score'] += 2
                    signals['reasons'].append("✅ MACD无死叉")
                else:
                    signals['reasons'].append("⚠️ MACD出现死叉")
        except:
            pass
        
        # 入场硬门槛：趋势、RSI、成交量均须合格；MACD仅作加分确认。
        signals['can_enter'] = trend_ok and rsi_ok and volume_ok and signals['score'] >= 2
        if _data_ok > 0 and not signals['can_enter']:
            signals['reasons'].append('⛔ 美股入场硬门槛未全部满足')

        # 只有数据全部获取失败（K线不足/断连）时才用备用源，不是技术面差的时候
        if _data_ok == 0:
            fallback = self._technical_anomaly_fallback(symbol)
            if fallback:
                signals['score'] = fallback['score']
                signals['can_enter'] = fallback['score'] >= 2
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
            clean = symbol.replace('US.', '').replace('HK.', '').split('.')[0]
            futu_sym = f'US.{clean}'
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