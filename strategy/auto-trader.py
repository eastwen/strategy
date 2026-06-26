#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3
"""
自动交易执行器 v2.1
集成技术指标检查
- MA趋势判断
- RSI检查
- 成交量检查
- MACD死叉检查
- ATR动态止损/止盈
- 仓位控制
"""

import sys
import os
import json
import time
import requests
from datetime import datetime, time as dt_time, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext, OpenSecTradeContext, RET_OK, OrderType, TrdSide, TrdEnv, Market, SecurityType, TrdMarket, SecurityFirm

# 导入技术指标模块（区分美股/港股）
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
try:
    from technical_indicators_us import USTechIndicators
    from technical_indicators_hk import HKTechIndicators
    TECH_INDICATORS_AVAILABLE = True
except Exception as e:
    TECH_INDICATORS_AVAILABLE = False
    print(f"⚠️ 技术指标模块不可用: {e}")

class AutoTrader:
    """自动交易执行器"""
    
    def __init__(self):
        self.load_config()
        self.quote_ctx = None
        self.trade_ctx = None
        self.hk_trade_ctx = None
        self.closed_trades_file = '/home/admin/.openclaw/workspace-stock/data/closed-trades.json'
        self.open_positions_file = '/home/admin/.openclaw/workspace-stock/data/open-positions.json'
        self.staged_reductions_file = '/home/admin/.openclaw/workspace-stock/data/staged-reductions.json'
        self._vix_cache = {'value': None, 'timestamp': 0}
    
    def save_open_position(self, symbol, shares, entry_price, market='us', score=0, reasons=None):
        """保存入场记录
        
        Args:
            symbol: 标的代码
            shares: 持仓数量
            entry_price: 开仓价格
            market: 市场（us/hk）
            score: 开仓评分
            reasons: 开仓原因列表（技术信号、新闻等）
        """
        try:
            positions = []
            try:
                with open(self.open_positions_file, 'r') as f:
                    positions = json.load(f)
            except:
                positions = []
            
            # 检查是否已存在
            positions = [p for p in positions if p.get('symbol') != symbol]
            
            positions.append({
                'symbol': symbol,
                'shares': shares,
                'entry_price': entry_price,
                'entry_time': datetime.now().isoformat(),
                'market': market,
                'entry_score': score,
                'entry_reasons': reasons or [],
                'peak_pnl_pct': 0.0,  # 峰值浮盈
                'peak_time': datetime.now().isoformat()
            })
            
            with open(self.open_positions_file, 'w') as f:
                json.dump(positions, f, ensure_ascii=False, indent=2)
            print(f"   💾 已记录入场: {symbol} @ ${entry_price} (评分{score})")
        except Exception as e:
            print(f"   ⚠️ 记录入场失败: {e}")
    
    def update_peak_profit(self, symbol, current_pnl_pct):
        """更新持仓峰值浮盈"""
        try:
            try:
                with open(self.open_positions_file, 'r') as f:
                    positions = json.load(f)
            except:
                return
            
            updated = False
            for p in positions:
                if p.get('symbol') == symbol:
                    if current_pnl_pct > p.get('peak_pnl_pct', 0):
                        p['peak_pnl_pct'] = current_pnl_pct
                        p['peak_time'] = datetime.now().isoformat()
                        updated = True
            
            if updated:
                with open(self.open_positions_file, 'w') as f:
                    json.dump(positions, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def remove_open_position(self, symbol):
        """移除入场记录"""
        try:
            try:
                with open(self.open_positions_file, 'r') as f:
                    positions = json.load(f)
            except:
                return None
            
            # 找到并移除
            result = None
            positions = [p for p in positions if p.get('symbol') != symbol]
            
            with open(self.open_positions_file, 'w') as f:
                json.dump(positions, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def get_open_position(self, symbol):
        """获取入场记录"""
        try:
            with open(self.open_positions_file, 'r') as f:
                positions = json.load(f)
            for p in positions:
                if p.get('symbol') == symbol:
                    return p
            return None
        except:
            return None
    
    def _lookup_entry_context(self, symbol):
        """从 open-positions.json 查询入场上下文（score/reasons）。
        2026-06-24 east 补：止损/止盈记录落盘时需要带上这些信息。
        """
        try:
            with open(self.open_positions_file, 'r') as f:
                positions = json.load(f)
            target = self.normalize_symbol(symbol)
            for pos in positions:
                if self.normalize_symbol(pos.get('symbol', '')) == target:
                    return {
                        'entry_score': int(pos.get('entry_score', 0) or 0),
                        'entry_reasons': pos.get('entry_reasons', []) or [],
                    }
        except Exception:
            pass
        return {'entry_score': 0, 'entry_reasons': []}

    def save_closed_trade(self, symbol, side, shares, entry_price, exit_price, pnl_pct, reason, market='us', stop_type=None, entry_score=0, llm_review=None, entry_reasons=None):
        """保存平仓记录
        
        Args:
            symbol: 标的代码
            side: 买卖方向
            shares: 数量
            entry_price: 开仓价（从Futu持仓获取）
            exit_price: 平仓价
            pnl_pct: 盈亏比例
            reason: 平仓原因
            market: 市场
            stop_type: 止损类型
            entry_score: 开仓评分
            entry_reasons: 开仓理由列表（2026-06-24 east 补：随平仓一起落盘）
        """
        try:
            # 计算盈亏
            pnl = (exit_price - entry_price) * shares if entry_price > 0 else 0
            
            # 读取现有记录
            closed_trades = []
            try:
                with open(self.closed_trades_file, 'r') as f:
                    closed_trades = json.load(f)
            except:
                closed_trades = []
            
            # 添加新记录
            trade = {
                'symbol': symbol,
                'side': side,
                'shares': shares,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'reason': reason,
                'stop_type': stop_type,
                'market': market,
                'entry_score': entry_score,
                'close_time': datetime.now().isoformat()
            }
            # 2026-06-18 east 修复: 让飞书与日报使用同一份 LLM 复盘
            if llm_review:
                trade['llm_review'] = llm_review
            # 2026-06-24 east 修复: 入场理由一并落盘，避免后续复盘信息缺失
            if entry_reasons:
                trade['entry_reasons'] = list(entry_reasons)
            closed_trades.append(trade)
            
            # 保存
            with open(self.closed_trades_file, 'w') as f:
                json.dump(closed_trades, f, ensure_ascii=False, indent=2)
            
            print(f"   💾 已保存平仓记录: {symbol} {reason} {pnl_pct:+.2f}%")
        except Exception as e:
            print(f"   ⚠️ 保存平仓记录失败: {e}")
        
    def load_config(self):
        """加载配置"""
        # 直接使用默认配置（不需要配置文件）
        self.us_config = {'min_score': 80, 'opp_alert_score': 90, 'position_size': 0.12, 'max_positions': 999}
        self.hk_config = {'min_score': 70, 'position_size': 0.03, 'max_positions': 999}
        self.risk_config = {
            'us_single_position_limit': 0.12,
            'us_total_position_limit': 1.0,   # 总仓位无上限（VIX高位会单向收紧到 50% / 0%）
            'hk_single_position_limit': 0.03,
            'hk_total_position_limit': 1.0,
        }
        self.cooldown_seconds = 86400  # 24小时冷却：同一标的一天内不重复交易
        self.recently_closed = {}  # {symbol: timestamp} 记录最近平仓的标的，防止重复平仓
        # 持久化通知冷却（auto-trader 每 5 分钟被 cron 重启，内存字典会丢，必须落盘）
        self._load_notify_cooldowns()
        
        # 兼容旧代码
        self.config = {
            'min_score': self.us_config.get('min_score', 80),
            'max_positions': self.us_config.get('max_positions', 999),
            'position_size': self.us_config.get('position_size', 0.12),
        }
        
        try:
            with open('/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json', 'r') as f:
                keys = json.load(f)
            self.feishu_chat_id = keys.get('feishu', {}).get('chatId', '') or keys.get('feishu', {}).get('openId', '')
        except:
            pass
    
    def _load_notify_cooldowns(self):
        """加载持久化的通知冷却记录（跨进程）。只读未过期的条目。"""
        path = '/home/admin/.openclaw/workspace-stock/data/notify-cooldowns.json'
        self.notify_cooldown_file = path
        try:
            with open(path, 'r') as f:
                data = json.load(f) or {}
            now = time.time()
            # 只保留未过期的（90天）
            cleaned = {k: float(v) for k, v in data.items() if isinstance(v, (int, float)) and now - float(v) < 90 * 86400}
            # 合并进 recently_closed，让所有冷却逻辑复用同一个字典
            self.recently_closed.update(cleaned)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ 加载通知冷却失败: {e}")

    def _save_notify_cooldowns(self):
        """落盘通知冷却记录。只保存 opp_/notify_ 前缀的跨进程冷却项，
        避免把仅当进程生命周期内使用的 recently_closed[symbol] 也写进去。"""
        path = getattr(self, 'notify_cooldown_file', '/home/admin/.openclaw/workspace-stock/data/notify-cooldowns.json')
        try:
            now = time.time()
            persistent = {
                k: float(v) for k, v in self.recently_closed.items()
                if isinstance(k, str) and (k.startswith('opp_') or k.startswith('notify_'))
                and isinstance(v, (int, float)) and now - float(v) < 90 * 86400
            }
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(persistent, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            print(f"⚠️ 保存通知冷却失败: {e}")
    
    def connect_futu(self):
        """连接Futu OpenD（每次都创建新连接确保数据最新）"""
        # 关闭旧连接
        if self.trade_ctx:
            try:
                self.trade_ctx.close()
            except:
                pass
        if self.hk_trade_ctx:
            try:
                self.hk_trade_ctx.close()
            except:
                pass
        if self.quote_ctx:
            try:
                self.quote_ctx.close()
            except:
                pass
        try:
            self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            
            # 模拟盘不需要解锁，直接创建交易上下文
            # 美股交易上下文 (2026-06-26 east: futu-api 10.8 废弃 OpenUSTradeContext、OpenHKTradeContext，统一用 OpenSecTradeContext)
            self.trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111,
                                                  security_firm=SecurityFirm.FUTUSECURITIES)
            
            # 港股交易上下文
            self.hk_trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host='127.0.0.1', port=11111,
                                                     security_firm=SecurityFirm.FUTUSECURITIES)
            
            print("✅ 连接Futu OpenD成功")
            return True
        except Exception as e:
            print(f"❌ 连接Futu失败: {e}")
            return False
    
    def place_order(self, symbol, side, quantity, market='us'):
        """下单"""
        # 选择正确的交易上下文
        ctx = self.hk_trade_ctx if market == 'hk' else self.trade_ctx
        try:
            ret, data = ctx.place_order(
                price=0,  # 市价单
                qty=quantity,
                code=symbol,
                order_type=OrderType.MARKET,
                trd_side=TrdSide.BUY if side == 'BUY' else TrdSide.SELL,
                trd_env=TrdEnv.SIMULATE
            )
            
            if ret == RET_OK:
                order_id = data['order_id'].iloc[0]
                market_tag = '🇭🇰' if market == 'hk' else '🇺🇸'
                print(f"{market_tag} 下单成功: 订单ID {order_id}")
                return True, order_id
            else:
                print(f"❌ 下单失败: {data}")
                return False, str(data)
        except Exception as e:
            print(f"❌ 下单异常: {e}")
            return False, str(e)
    
    def _wait_filled_price(self, order_id, market='us', timeout=10, poll_interval=0.5):
        """等订单状态 FILLED_ALL 并回查真实成交均价 dealt_avg_price。

        防止用 "触发那一刻的报价" 当成交价（尤其港股 09:30 集合竞价跳价）。

        Returns:
            (filled_price: float, dealt_qty: int, status: str) 或 (None, 0, status)。
            failure 时 filled_price = None。
        """
        import time as _time
        ctx = self.hk_trade_ctx if market == 'hk' else self.trade_ctx
        if ctx is None or not order_id:
            return None, 0, 'NO_CTX'
        oid = str(order_id)
        deadline = _time.time() + timeout
        last_status = ''
        last_avg = 0.0
        last_qty = 0
        while _time.time() < deadline:
            try:
                ret, df = ctx.order_list_query(order_id=oid, trd_env=TrdEnv.SIMULATE)
                if ret == RET_OK and df is not None and len(df) > 0:
                    row = df.iloc[0]
                    last_status = str(row.get('order_status', ''))
                    try:
                        last_avg = float(row.get('dealt_avg_price', 0) or 0)
                    except Exception:
                        last_avg = 0.0
                    try:
                        last_qty = int(row.get('dealt_qty', 0) or 0)
                    except Exception:
                        last_qty = 0
                    if last_status == 'FILLED_ALL' and last_avg > 0:
                        return last_avg, last_qty, last_status
                    if last_status in ('CANCELLED_ALL', 'CANCELLED_PART', 'FAILED', 'DISABLED', 'DELETED'):
                        # 终态但非全部成交，返回当下已成交均价（可能为0）
                        return (last_avg if last_avg > 0 else None), last_qty, last_status
            except Exception as e:
                print(f"  ⚠️ _wait_filled_price 查询异常: {e}")
            _time.sleep(poll_interval)
        # 超时：能拿到部分成交均价就返回部分
        return (last_avg if last_avg > 0 else None), last_qty, last_status or 'TIMEOUT'

    def _get_hk_lot_size(self, symbol):
        """获取港股每手股数：优先从 Futu 实时基础信息查询，失败时使用本地兜底。"""
        try:
            ctx = self.quote_ctx
            close_after = False
            if ctx is None:
                ctx = OpenQuoteContext('127.0.0.1', 11111)
                close_after = True
            try:
                ret, data = ctx.get_stock_basicinfo(Market.HK, SecurityType.STOCK, [symbol])
                if ret == RET_OK and data is not None and len(data) > 0 and 'lot_size' in data.columns:
                    lot_size = int(data.iloc[0].get('lot_size') or 0)
                    if lot_size > 0:
                        return lot_size
            finally:
                if close_after:
                    ctx.close()
        except Exception as e:
            print(f"⚠️ 获取港股每手股数失败 {symbol}: {e}，使用本地兜底")

        # 常见港股每手股数映射（兜底）
        lot_sizes = {
            'HK.00001': 500,   # 长和
            'HK.00005': 400,   # 汇丰控股
            'HK.00012': 1000,  # 恒基地产
            'HK.00016': 1000,  # 新鸿基地产
            'HK.00027': 1000,  # 银河娱乐
            'HK.00700': 100,   # 腾讯
            'HK.09988': 100,   # 阿里巴巴
            'HK.00939': 1000,  # 建设银行
            'HK.00981': 500,   # 中银香港
            'HK.02318': 500,   # 中国平安
            'HK.02331': 500,   # 李宁
            'HK.09868': 100,   # 小鹏汽车
            'HK.09866': 100,   # 蔚来
            'HK.02333': 500,   # 比亚迪股份
            'HK.02269': 500,   # 药明生物
            'HK.01093': 1000,  # 石药集团
            'HK.02319': 1000,  # 蒙牛乳业
            'HK.02020': 500,   # 安踏体育
        }
        return lot_sizes.get(symbol, 100)
    
    _trading_day_cache = {}  # {(market, 'YYYY-MM-DD'): bool}

    def is_trading_day(self, market='us', date=None):
        """检查指定日期是否为交易日（节假日/周末过滤），结果按天缓存。
        优先使用 futu request_trading_days，异常时回退到周末判断。"""
        if date is None:
            date = datetime.now().date()
        key = (market, date.isoformat())
        if key in self._trading_day_cache:
            return self._trading_day_cache[key]

        # 周末直接 False
        if date.weekday() >= 5:
            self._trading_day_cache[key] = False
            return False

        result = None
        try:
            mkt = Market.HK if market == 'hk' else Market.US
            quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            try:
                ret, data = quote_ctx.request_trading_days(
                    market=mkt, start=date.isoformat(), end=date.isoformat()
                )
                if ret == RET_OK:
                    result = bool(data) and any(
                        d.get('time') == date.isoformat() for d in data
                    )
            finally:
                quote_ctx.close()
        except Exception as e:
            print(f"⚠️  交易日历查询失败({market} {date}): {e}，回退周末判断")
            result = None

        if result is None:
            result = date.weekday() < 5  # 兜底

        self._trading_day_cache[key] = result
        if not result:
            print(f"📅 {market.upper()} {date} 非交易日（节假日/周末），跳过交易")
        return result

    def check_trading_hours(self, market='us'):
        """检查是否在交易时间（包含盘前+盘中+盘后）"""
        now_dt = datetime.now()
        now = now_dt.time()

        # 节假日 / 非交易日过滤
        # 美股跨午夜，按当前时段所属的交易日判断
        if market == 'us':
            # 21:00 之后属于今天开盘的美股交易日；00:00-08:00 属于昨天开盘
            check_date = now_dt.date()
            if now < dt_time(21, 0):
                check_date = (now_dt - timedelta(days=1)).date()
            if not self.is_trading_day('us', check_date):
                return False
        elif market == 'hk':
            if not self.is_trading_day('hk', now_dt.date()):
                return False

        if market == 'us':
            # 美股交易时段：盘中(21:00-04:00) + 盘后(04:00-08:00)
            # 盘中: 21:00 - 次日04:00
            market_start = dt_time(21, 0)
            market_end = dt_time(4, 0)
            # 盘后: 04:00 - 04:30
            after_hours_start = dt_time(4, 0)
            after_hours_end = dt_time(4, 30)
            
            # 判断是否在交易时段
            if now >= market_start or now <= market_end:
                return True  # 盘中（跨午夜）
            if now >= after_hours_start and now <= after_hours_end:
                return True  # 盘后
            
            return False
        elif market == 'hk':
            start = dt_time(9, 30)
            end = dt_time(16, 0)
            return start <= now <= end
        
        return False
    
    def get_account_and_positions(self, market='us'):
        """获取账户和持仓信息（从API实时获取）
        
        Args:
            market: 'us' 或 'hk'，决定使用哪个交易上下文
        """
        try:
            # 根据市场选择交易上下文
            if market == 'hk' and self.hk_trade_ctx:
                ctx = self.hk_trade_ctx
                print(f"  📊 使用港股交易上下文")
            else:
                ctx = self.trade_ctx
                print(f"  📊 使用美股交易上下文")
            
            # 查询账户
            ret, acc_data = ctx.accinfo_query(trd_env=TrdEnv.SIMULATE)
            if ret != RET_OK or acc_data is None or len(acc_data) == 0:
                print(f"⚠️ {market.upper()}账户查询失败: {ret}")
                return None
            
            total_assets = acc_data.iloc[0]['total_assets']
            total_cash = acc_data.iloc[0]['cash']
            account_market_val = acc_data.iloc[0].get('market_val', 0)
            
            print(f"  💰 {market.upper()}账户: 总资产=${total_assets:,.2f}, 现金=${total_cash:,.2f}, 持仓市值=${account_market_val:,.2f}")
            
            # 查询持仓
            ret, positions_data = ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
            
            positions = []
            if ret == RET_OK and positions_data is not None and len(positions_data) > 0:
                for p in positions_data.itertuples():
                    positions.append({
                        'symbol': p.code,
                        'shares': p.qty,
                        'cost_price': getattr(p, 'cost_price', 0),
                        'market_val': getattr(p, 'market_val', 0),
                        'pl_ratio': float(getattr(p, 'pl_ratio', 0))
                    })
                print(f"  📈 {market.upper()}持仓: {len(positions)}只")
            else:
                print(f"  📈 {market.upper()}持仓: 0只")
            
            # 获取未完成订单
            ret, orders = ctx.order_list_query(trd_env=TrdEnv.SIMULATE)
            pending_orders = []
            if ret == RET_OK and orders is not None:
                pending = orders[orders['order_status'] != 'FILLED_ALL']
                for o in pending.itertuples():
                    pending_orders.append(o.code.replace('US.', '').replace('HK.', ''))
                if pending_orders:
                    print(f"  ⏳ {market.upper()}未完成订单: {len(pending_orders)}个")
            
            return {
                'total_assets': total_assets,
                'cash': total_cash,
                'market_val': account_market_val,
                'positions': positions,
                'pending_orders': pending_orders
            }
        except Exception as e:
            print(f"❌ 获取{market.upper()}账户信息失败: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def get_opportunities(self):
        """获取交易机会（拒绝使用过期机会文件，避免旧信号触发通知/交易）"""
        opportunities = {'us': [], 'hk': []}
        max_age_hours = 72

        def load_fresh(path, market_name):
            try:
                if not os.path.exists(path):
                    print(f"⚠️ {market_name}机会文件不存在: {path}")
                    return []

                with open(path, 'r') as f:
                    data = json.load(f)

                # 优先检查文件内的 last_scan；没有则退回文件 mtime
                last_scan = data.get('last_scan')
                if last_scan:
                    try:
                        scan_dt = datetime.fromisoformat(last_scan.replace('Z', '+00:00')).replace(tzinfo=None)
                    except Exception:
                        scan_dt = None
                else:
                    scan_dt = None

                if scan_dt is None:
                    scan_dt = datetime.fromtimestamp(os.path.getmtime(path))

                age_hours = (datetime.now() - scan_dt).total_seconds() / 3600
                if age_hours > max_age_hours:
                    print(f"⚠️ {market_name}机会数据过期: {age_hours:.1f}小时前，已忽略 {path}")
                    return []

                return data.get('opportunities', [])
            except Exception as e:
                print(f"⚠️ 读取{market_name}机会失败: {e}")
                return []

        opportunities['us'] = load_fresh('/home/admin/.openclaw/workspace-stock/data/us-opportunities.json', '美股')
        opportunities['hk'] = load_fresh('/home/admin/.openclaw/workspace-stock/data/hk-opportunities.json', '港股')
        return opportunities

    def find_opportunity(self, symbol, market='us'):
        """按标的从机会文件中读取最新动态分析结果。"""
        target = self.normalize_symbol(symbol)
        try:
            opportunities = self.get_opportunities().get(market, [])
            for opp in opportunities:
                if self.normalize_symbol(opp.get('symbol', '')) == target:
                    return opp
        except Exception as e:
            print(f"⚠️ 查找机会数据失败 {symbol}: {e}")
        return {}

    def _build_exit_payload(self, symbol, market, raw_reason, entry_price, exit_price, pnl_pct,
                            entry_time='', entry_score=0, entry_reasons=None):
        """为 LLM 卖出复盘组装全套数据：技术指标 + 市场环境 + 机会文件上下文。采集失败不阻主流程。

        2026-06-24 east 修复：
          - 显式标记 entry_context_available，防止 LLM 在缺失上下文时臆测入场原因。
          - 卖出时点指标改用 exit_* 命名，避免被误读为入场指标。
        """
        entry_reasons_list = [r for r in (entry_reasons or []) if r]
        entry_score_int = int(entry_score or 0)
        entry_context_available = bool(entry_reasons_list) or entry_score_int > 0
        payload = {
            'market': market,
            'side': 'SELL',
            'raw_reason': raw_reason,
            'stop_type': self._guess_stop_type(raw_reason),
            'entry_price': float(entry_price or 0),
            'exit_price': float(exit_price or 0),
            'pnl_pct': float(pnl_pct or 0),
            'entry_time': entry_time,
            'entry_score': entry_score_int,
            'entry_reasons': entry_reasons_list,
            'entry_context_available': entry_context_available,
        }

        # 持有天数
        try:
            if entry_time:
                et = datetime.fromisoformat(str(entry_time).replace('Z', '+00:00')).replace(tzinfo=None)
                payload['holding_days'] = max(0, (datetime.now() - et).days)
        except Exception:
            payload['holding_days'] = 0

        # 卖出时点的技术指标快照（注意：这是卖出时的指标，不是入场时的）
        try:
            if TECH_INDICATORS_AVAILABLE:
                ti = USTechIndicators() if market.lower() == 'us' else HKTechIndicators()
                try:
                    rsi = ti.check_rsi(symbol)
                    if rsi is not None:
                        payload['exit_rsi'] = round(float(rsi), 2)
                except Exception:
                    pass
                try:
                    trend = ti.check_trend(symbol)
                    if trend:
                        payload['exit_ma20'] = round(float(trend.get('ma20', 0)), 2)
                        payload['exit_ma50'] = round(float(trend.get('ma50', 0)), 2)
                except Exception:
                    pass
                try:
                    vol = ti.check_volume(symbol)
                    if vol is not None:
                        payload['exit_volume_ratio'] = round(float(vol), 2)
                except Exception:
                    pass
                try:
                    payload['exit_macd_death_cross'] = bool(ti.check_macd_death_cross(symbol))
                except Exception:
                    pass
                try:
                    mult = 2.0 if market.lower() == 'us' else 1.5
                    sl = ti.get_stop_loss(symbol, mult)
                    if sl is not None and payload['exit_price'] > 0:
                        payload['exit_atr'] = round(abs(payload['exit_price'] - float(sl)) / mult, 2)
                except Exception:
                    pass
                try:
                    ti.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ 采集技术指标失败 {symbol}: {e}")

        # 机会文件上下文（新闻情绪等）
        try:
            opp = self.find_opportunity(symbol, market)
            if opp:
                payload.setdefault('sentiment', opp.get('sentiment', '中性'))
                payload.setdefault('change_pct', opp.get('change_pct', 0))
        except Exception:
            pass

        # VIX
        try:
            import requests
            r = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX',
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            if r.status_code == 200:
                payload['vix'] = round(float(r.json()['chart']['result'][0]['meta']['regularMarketPrice']), 2)
        except Exception:
            pass

        # 市场当日涨跌
        try:
            import requests
            idx_sym = '%5EGSPC' if market.lower() == 'us' else '%5EHSI'
            r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{idx_sym}',
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            if r.status_code == 200:
                meta = r.json()['chart']['result'][0]['meta']
                cur = float(meta['regularMarketPrice'])
                prev = float(meta.get('previousClose') or meta.get('chartPreviousClose') or cur)
                if prev:
                    payload['market_change_pct'] = round((cur - prev) / prev * 100, 2)
        except Exception:
            pass

        return payload

    def _guess_stop_type(self, raw_reason):
        s = str(raw_reason or '')
        if '重大利空' in s:
            return 'major_negative'
        if '收紧' in s:
            return 'tightened_atr_stop'
        if '分级' in s:
            return 'staged_reduction'
        if '止盈' in s:
            return 'take_profit'
        if '止损' in s:
            return 'max_loss_stop'
        return 'auto_close'

    def _calc_risk_targets(self, symbol, price, market='us'):
        """计算买入通知中的真实风控价位。
        2026-06-24 east 修复: 不再用死板 -6%/+8%。使用 ATR 动态规则。

        Returns:
            dict: {
                'atr': float | None,
                'atr_stop': 初始 ATR 止损价 (美2.0x/港1.5x),
                'staged_first': 分级减仓第一档 (-6% 价),
                'hard_stop': 复核期硬止损 (-10% 价),
                'tp_first': ATR 2x 获利参考,
                'tp_trend': ATR 4x 趋势止盈参考,
                'rule_note': 人能看懂的规则说明
            }
        """
        market = (market or 'us').lower()
        atr_mult_stop = 2.0 if market == 'us' else 1.5
        atr_mult_tp = 4.0 if market == 'us' else 3.0
        targets = {
            'atr': None,
            'atr_stop': None,
            'staged_first': round(price * 0.94, 2),  # 分级减仓触发点 -6%
            'hard_stop': round(price * 0.90, 2),     # 复核期硬止损 -10%
            'tp_first': None,
            'tp_trend': None,
            'rule_note': '',
        }
        try:
            if TECH_INDICATORS_AVAILABLE:
                ti = USTechIndicators() if market == 'us' else HKTechIndicators()
                try:
                    sl = ti.get_stop_loss(symbol, atr_mult_stop)
                    tp = ti.get_take_profit(symbol, atr_mult_tp)
                    if sl is not None and price > 0:
                        atr_value = round(abs(price - float(sl)) / atr_mult_stop, 4)
                        targets['atr'] = atr_value
                        targets['atr_stop'] = round(float(sl), 2)
                        targets['tp_first'] = round(price + atr_value * 2.0, 2)
                    if tp is not None:
                        targets['tp_trend'] = round(float(tp), 2)
                except Exception as e:
                    print(f"⚠️ 计算 ATR 风控失败 {symbol}: {e}")
                try:
                    ti.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ 风控指标模块不可用 {symbol}: {e}")

        def _pct(v):
            return f"{(v/price - 1)*100:+.1f}%" if v and price else ''
        rule_lines = []
        if targets['atr_stop']:
            rule_lines.append(f"初始 ATR 止损: ${targets['atr_stop']} ({_pct(targets['atr_stop'])}, {atr_mult_stop}x ATR)")
        else:
            rule_lines.append('初始 ATR 止损: 未取到 ATR，按系统默认执行')
        rule_lines.append(f"分级减仓: ${targets['staged_first']} ({_pct(targets['staged_first'])}, 先减 50%)")
        rule_lines.append(f"复核期硬止损: ${targets['hard_stop']} ({_pct(targets['hard_stop'])}, 全平)")
        if targets['tp_first']:
            rule_lines.append(f"ATR 止盈一档: ${targets['tp_first']} ({_pct(targets['tp_first'])}, 2x ATR)")
        if targets['tp_trend']:
            rule_lines.append(f"趋势止盈: ${targets['tp_trend']} ({_pct(targets['tp_trend'])}, {atr_mult_tp}x ATR)")
        rule_lines.append('另: 重大利空 / MACD 死叉 / RSI>70 超买也会触发减仓')
        targets['rule_note'] = '\n'.join(rule_lines)
        return targets

    def build_dynamic_signal_details(self, symbol, market='us', score=0, llm_analysis=None, reasons=None):
        """构造飞书通知的真实四源评分、信号类型和LLM结论。

        2026-06-24 east 重构：
          - 删除全部“按比例硬拆”逻辑
          - 优先读 opportunities.json 中 four_source_scorer 写入的真实分项
          - 没有真实分项时当场调 four_source_scorer.score_all
          - 所有分项携带 available_* 和 evidence_*
        """
        opp = self.find_opportunity(symbol, market)

        def num(value, default=0):
            try:
                return float(value)
            except Exception:
                return default

        # 1) 优先读 opportunities.json 中真实四源分项与证据
        score_news = opp.get('score_news')
        score_announce = opp.get('score_announce')
        score_community = opp.get('score_community')
        score_institution = opp.get('score_institution')
        available_news = opp.get('available_news')
        available_announce = opp.get('available_announce')
        available_community = opp.get('available_community')
        available_institution = opp.get('available_institution')
        evidence_news = opp.get('evidence_news', '')
        evidence_announce = opp.get('evidence_announce', '')
        evidence_community = opp.get('evidence_community', '')
        evidence_institution = opp.get('evidence_institution', '')

        # 2) 没有真实分项时当场跑一次
        if score_news is None or available_news is None:
            try:
                sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
                from four_source_scorer import score_all as _fs_score_all
                fs = _fs_score_all(symbol, market)
                score_news = fs['score_news']
                score_announce = fs['score_announce']
                score_community = fs['score_community']
                score_institution = fs['score_institution']
                available_news = fs['available_news']
                available_announce = fs['available_announce']
                available_community = fs['available_community']
                available_institution = fs['available_institution']
                evidence_news = fs['evidence_news']
                evidence_announce = fs['evidence_announce']
                evidence_community = fs['evidence_community']
                evidence_institution = fs['evidence_institution']
                print(f"ℹ️ {symbol} 通知前现算四源: 资讯{score_news}/公告{score_announce}/社区{score_community}/机构{score_institution}")
            except Exception as e:
                print(f"⚠️ {symbol} 四源评分不可用，全部记为未覆盖: {e}")
                score_news = score_announce = score_community = score_institution = 0
                available_news = available_announce = available_community = available_institution = False
                evidence_news = evidence_announce = evidence_community = evidence_institution = f'评分器异常: {e}'

        # 3) 计算总分：优先用扫描器商定的 final_score
        score_total = opp.get('final_score') or opp.get('score') or opp.get('base_score')
        if score_total is None:
            score_total = (score_news or 0) + (score_announce or 0) + (score_community or 0) + (score_institution or 0)

        # 5) LLM 验真结论
        llm_conclusion = ''
        if llm_analysis:
            llm_conclusion = llm_analysis.get('llm_reason', '')
        if not llm_conclusion:
            llm_conclusion = opp.get('llm_reason', '')

        invalid_llm_markers = ['无API Key', 'API错误', '调用失败', 'LLM分析失败', '解析失败']
        llm_invalid = (not llm_conclusion) or any(marker in str(llm_conclusion) for marker in invalid_llm_markers)
        if llm_invalid:
            try:
                from llm_stock_analyzer import analyze_stock
                market_data = {
                    'symbol': self.normalize_symbol(symbol),
                    'market': market,
                    'base_score': int(num(score_total, score or 70)),
                    'price': num(opp.get('price', 0), 0),
                    'change_pct': num(opp.get('change_pct', 0), 0),
                    'rsi': num(opp.get('rsi', 50), 50),
                    'ma20': num(opp.get('ma20', 0), 0),
                    'ma50': num(opp.get('ma50', 0), 0),
                    'volume_ratio': num(opp.get('volume_ratio', 1.0), 1.0),
                    'atr': num(opp.get('atr', 0), 0),
                    'sentiment': opp.get('sentiment', '中性'),
                }
                fresh_llm = analyze_stock(symbol, market_data)
                fresh_reason = fresh_llm.get('llm_reason', '')
                if fresh_reason and not any(marker in fresh_reason for marker in invalid_llm_markers):
                    llm_conclusion = fresh_reason
                    score_total = fresh_llm.get('final_score', score_total)
                    print(f"✅ {symbol} 通知前已重新LLM验真: {llm_conclusion}")
            except Exception as e:
                print(f"⚠️ {symbol} 通知前重新LLM验真失败: {e}")

        if (not llm_conclusion or any(marker in str(llm_conclusion) for marker in invalid_llm_markers)) and reasons:
            llm_conclusion = '；'.join(reasons[:3])
        if not llm_conclusion or any(marker in str(llm_conclusion) for marker in invalid_llm_markers):
            # 2026-06-24 east 修复：LLM 不可用时不再说“请复核”套话，明确告知失败
            llm_conclusion = f"⚠️ LLM 验真不可用（限流/超时），仅依据扫描器原始评分 {score_total} 分"

        # 4) 信号类型按评分分档（放在 LLM 之后，使用最终的 score_total）
        signal_type = opp.get('signal_type') or opp.get('signal')
        if not signal_type:
            st = float(num(score_total, 0))
            if st >= 85:
                signal_type = f'强势共振 ({int(st)}分)'
            elif st >= 75:
                signal_type = f'中等共振 ({int(st)}分)'
            elif st >= 65:
                signal_type = f'边缘共振 ({int(st)}分)'
            else:
                signal_type = f'评分不足 ({int(st)}分)'
        # 未覆盖维度清单（44 east）
        uncovered_keys = []
        if not available_news: uncovered_keys.append('news')
        if not available_announce: uncovered_keys.append('announce')
        if not available_community: uncovered_keys.append('community')
        if not available_institution: uncovered_keys.append('institution')

        return {
            'score_total': int(num(score_total, 0)),
            'score_news': int(num(score_news, 0)),
            'score_announce': int(num(score_announce, 0)),
            'score_community': int(num(score_community, 0)),
            'score_institution': int(num(score_institution, 0)),
            'available_news': bool(available_news),
            'available_announce': bool(available_announce),
            'available_community': bool(available_community),
            'available_institution': bool(available_institution),
            'evidence_news': evidence_news,
            'evidence_announce': evidence_announce,
            'evidence_community': evidence_community,
            'evidence_institution': evidence_institution,
            'uncovered_keys': uncovered_keys,
            'estimated_keys': uncovered_keys,  # 向后兼容
            'signal_type': signal_type,
            'llm_conclusion': llm_conclusion,
        }
    
    def should_trade(self, symbol, positions, pending_orders=None):
        """判断是否应该交易"""
        # 标准化股票代码（精确匹配基础代码）
        def normalize(sym):
            sym = sym.upper()
            if sym.startswith('US.'):
                sym = sym[3:]
            elif sym.startswith('HK.'):
                sym = sym[3:]
            parts = sym.split('.')
            return parts[0]  # 返回基础代码
        
        sym = normalize(symbol)
        
        # 检查是否已持仓
        for pos in positions:
            pos_sym = normalize(pos.get('symbol', ''))
            if sym == pos_sym:
                return False, f"已持仓({pos.get('symbol')})"
        
        # 检查未完成订单
        if pending_orders:
            pending_normalized = [normalize(s) for s in pending_orders]
            if sym in pending_normalized:
                return False, f"有未完成订单"
        
        return True, "可以交易"
    
    def execute_trade(self, symbol, side, quantity, price, market='us', force=False, skip_llm=False, score=0, reasons=None, entry_price_override=None):
        """执行交易
        
        Args:
            symbol: 标的代码
            side: 买入/卖出
            quantity: 数量
            price: 价格
            market: 市场（us/hk）
            force: 是否强制执行（止损/止盈时为True）
            skip_llm: 是否跳过LLM分析
            score: 开仓评分（用于记录开仓原因）
            reasons: 开仓原因列表（技术信号、新闻等）
        """
        print(f"\n{'='*60}")
        print(f"📈 准备下单")
        print(f"{'='*60}")
        print(f"标的: {symbol}")
        print(f"方向: {side}")
        print(f"数量: {quantity}股")
        print(f"价格: ${price:.2f}")
        print(f"金额: ${quantity * price:,.2f}")
        
        # ===== LLM分析（下单前分析，基础评分≥70时触发）=====
        # 止损交易跳过LLM分析
        llm_analysis = None
        if not skip_llm:
            llm_analysis = self.llm_analysis_before_trade(symbol, price, market)
            
            # LLM分析失败或被阻止
            if not llm_analysis:
                print(f"❌ LLM分析不可用，禁止下单")
                return False
            
            if not llm_analysis.get('passed', True):
                print(f"❌ LLM分析失败，禁止下单: {llm_analysis.get('llm_reason', '未知错误')}")
                return False
            
            final_score = llm_analysis.get('final_score', 0)
            llm_reason = llm_analysis.get('llm_reason', '')
            
            print(f"\n🧠 LLM分析结果:")
            print(f"   评分调整: {llm_analysis.get('score_adjust', 0):+d}")
            print(f"   最终评分: {final_score}")
            print(f"   LLM理由: {llm_reason}")
            
            # 如果LLM建议不买入，则取消
            if final_score < 65:
                print(f"❌ LLM分析不建议买入（评分: {final_score}），取消下单")
                return False
        
        # 连接Futu
        if not self.trade_ctx:
            if not self.connect_futu():
                self.send_notification(f"❌ 无法连接Futu，下单失败\n\n标的: {symbol}")
                return False
        
        # 下单前检查持仓和订单（避免重复购买/下单）
        check_ctx = self.hk_trade_ctx if market == 'hk' else self.trade_ctx
        check_ret, check_data = check_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
        if check_ret == RET_OK and check_data is not None:
            # 检查持仓（使用相同的标准化方法）
            def normalize(sym):
                sym = sym.upper()
                if sym.startswith('US.'):
                    sym = sym[3:]
                elif sym.startswith('HK.'):
                    sym = sym[3:]
                parts = sym.split('.')
                return parts[0]
            
            current_symbols = [normalize(p.code) for p in check_data.itertuples()]
            trade_sym = normalize(symbol)
            if trade_sym in current_symbols and not force:
                print(f"⚠️ 检查发现已持仓 {symbol}（标准化后: {trade_sym}），取消下单")
                return False
            
            # 检查未完成订单（force=True 时跳过，因为止损/止盈会先撤单）
            if not force:
                ret, orders = check_ctx.order_list_query(trd_env=TrdEnv.SIMULATE)
                if ret == RET_OK and orders is not None:
                    pending = orders[orders['order_status'] != 'FILLED_ALL']
                    pending_symbols = [o.code.replace('US.', '').replace('HK.', '') for o in pending.itertuples()]
                    if trade_sym in pending_symbols:
                        print(f"⚠️ {symbol} 有未完成订单，取消下单")
                        return False
        
        # 下单
        success, result = self.place_order(symbol, side, quantity, market)
        
        if success:
            # === 真实成交价回查（防止 quote 价被当成交价；尤其港股 09:30 集合竞价跳价） ===
            quoted_price = price  # 触发判定时读到的报价
            filled_price, filled_qty, fill_status = self._wait_filled_price(
                order_id=result, market=market, timeout=10, poll_interval=0.5
            )
            if filled_price and filled_price > 0:
                drift_pct = abs(filled_price - quoted_price) / max(quoted_price, 1e-9) * 100
                if drift_pct >= 0.5:
                    print(f"  ⚠️ 成交价与报价偏差 {drift_pct:.2f}%: quote=${quoted_price:.4f} → fill=${filled_price:.4f}（status={fill_status}），以真实成交价为准")
                else:
                    print(f"  ✅ 真实成交价 ${filled_price:.4f}（quote=${quoted_price:.4f}, status={fill_status}）")
                price = float(filled_price)
                if filled_qty and filled_qty > 0 and filled_qty != quantity:
                    print(f"  ℹ️ 实际成交数量 {filled_qty} 与下单数量 {quantity} 不一致，以实际成交为准")
                    quantity = int(filled_qty)
            else:
                print(f"  ⚠️ 未拿到真实成交价（status={fill_status}），仍使用报价 ${quoted_price:.4f}（盈亏可能失真）")

            # 先算 signal_details，让入场记录和飞书通知用同一个综合评分（final_score）
            signal_details = None
            if side == 'BUY':
                signal_details = self.build_dynamic_signal_details(
                    symbol=symbol,
                    market=market,
                    score=score,
                    llm_analysis=llm_analysis,
                    reasons=reasons,
                )

            # 入场记录（买入时）——使用综合评分 final_score 保持与飞书通知一致
            if side == 'BUY':
                entry_score = signal_details.get('score_total', score) if signal_details else score
                self.save_open_position(symbol, quantity, price, market, score=entry_score, reasons=reasons)
            
            # 使用新模板发送通知
            from feishu_pusher import FeishuPusher
            pusher = FeishuPusher()
            amount = quantity * price
            if side == 'BUY':
                # 2026-06-24 east 修复：不再泰以死板 -6%/+8% 充当目标价，改为 ATR 动态规则
                risk = self._calc_risk_targets(symbol, price, market)
                pusher.send_buy_notification(
                    symbol=symbol,
                    quantity=quantity,
                    price=price,
                    amount=amount,
                    target_take_profit=risk.get('tp_trend') or risk.get('tp_first'),
                    target_stop_loss=risk.get('atr_stop'),
                    risk_note=risk.get('rule_note', ''),
                    score_total=signal_details['score_total'],
                    score_news=signal_details['score_news'],
                    score_announce=signal_details['score_announce'],
                    score_community=signal_details['score_community'],
                    score_institution=signal_details['score_institution'],
                    signal_type=signal_details['signal_type'],
                    llm_conclusion=signal_details['llm_conclusion'],
                    estimated_keys=signal_details.get('estimated_keys', []),
                    evidences={
                        'news': signal_details.get('evidence_news', ''),
                        'announce': signal_details.get('evidence_announce', ''),
                        'community': signal_details.get('evidence_community', ''),
                        'institution': signal_details.get('evidence_institution', ''),
                    },
                    order_id=result,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
            else:
                sell_reason = reasons[0] if reasons else "自动平仓"
                sell_pnl_pct = 0.0
                entry_price = 0.0
                entry_time = ''
                entry_score = 0
                entry_reasons = []
                source_used = ''

                # 1) 先从 open-positions.json 只补充入场元信息；价格可能来自扫描价，不能优先用于盈亏
                try:
                    positions = []
                    with open(self.open_positions_file, 'r') as f:
                        positions = json.load(f)
                    target = self.normalize_symbol(symbol)
                    for pos in positions:
                        if self.normalize_symbol(pos.get('symbol', '')) == target:
                            entry_time = pos.get('entry_time', '')
                            entry_score = int(pos.get('entry_score', 0) or 0)
                            entry_reasons = pos.get('entry_reasons', []) or []
                            break
                except Exception as e:
                    print(f"⚠️ 卖出入场元信息读取失败 {symbol}: {e}")

                # 2) 优先使用本次卖出调用传入的富途真实持仓成本
                try:
                    override_price = float(entry_price_override or 0)
                except Exception:
                    override_price = 0
                if override_price > 0:
                    entry_price = override_price
                    sell_pnl_pct = (price - entry_price) / entry_price * 100
                    source_used = 'Futu position context'

                # 3) Fallback A：从 trades.json (富途账户同步) 拿 cost_price
                if entry_price <= 0 or sell_pnl_pct == 0.0:
                    try:
                        with open('/home/admin/.openclaw/workspace-stock/data/trades.json', 'r') as f:
                            tdata = json.load(f)
                        target = self.normalize_symbol(symbol)
                        for fp in tdata.get('positions', []):
                            if self.normalize_symbol(fp.get('symbol', '')) == target:
                                fp_cost = float(fp.get('cost_price', 0) or 0)
                                if fp_cost > 0:
                                    entry_price = fp_cost
                                    sell_pnl_pct = (price - entry_price) / entry_price * 100
                                    source_used = 'trades.json (futu sync)'
                                break
                    except Exception as e:
                        print(f"⚠️ trades.json fallback 失败 {symbol}: {e}")

                # 4) Fallback B：最后才用 open-positions.json 的旧入场价，避免扫描价冒充成交价
                if (entry_price <= 0 or sell_pnl_pct == 0.0):
                    try:
                        with open(self.open_positions_file, 'r') as f:
                            positions = json.load(f)
                        target = self.normalize_symbol(symbol)
                        for pos in positions:
                            if self.normalize_symbol(pos.get('symbol', '')) == target:
                                op_entry = float(pos.get('entry_price', 0) or 0)
                                if op_entry > 0:
                                    entry_price = op_entry
                                    sell_pnl_pct = (price - entry_price) / entry_price * 100
                                    source_used = 'open-positions.json fallback'
                                break
                    except Exception as e:
                        print(f"⚠️ open-positions fallback 失败 {symbol}: {e}")

                # 5) Fallback C：从 closed-trades.json 拿刚刚亲手写的 entry_price/pnl_pct　
                if (entry_price <= 0 or sell_pnl_pct == 0.0):
                    try:
                        with open('/home/admin/.openclaw/workspace-stock/data/closed-trades.json', 'r') as f:
                            ctrades = json.load(f)
                        target = self.normalize_symbol(symbol)
                        # 逆序：取最近一条与当前价接近的记录
                        for ct in reversed(ctrades):
                            if self.normalize_symbol(ct.get('symbol', '')) == target and ct.get('side') == 'SELL':
                                ce = float(ct.get('entry_price', 0) or 0)
                                cp = float(ct.get('pnl_pct', 0) or 0)
                                if ce > 0:
                                    entry_price = ce
                                    sell_pnl_pct = cp if cp != 0 else (price - entry_price) / entry_price * 100
                                    source_used = 'closed-trades.json'
                                break
                    except Exception as e:
                        print(f"⚠️ closed-trades.json fallback 失败 {symbol}: {e}")

                if source_used:
                    print(f"ℹ️  {symbol} 入场价${entry_price:.2f}、盈亏{sell_pnl_pct:+.2f}% 来源: {source_used}")
                elif entry_price <= 0:
                    print(f"⚠️  {symbol} 三道 fallback 均未拿到入场价，通知盈亏以 0% 发送")

                # === LLM 动态复盘：让 LLM 基于全套数据分析为什么卖、卖得对不对 ===
                llm_exit_reason = sell_reason  # 失败时回退到原始标签
                try:
                    exit_payload = self._build_exit_payload(
                        symbol=symbol,
                        market=market,
                        raw_reason=sell_reason,
                        entry_price=entry_price,
                        exit_price=price,
                        pnl_pct=sell_pnl_pct,
                        entry_time=entry_time,
                        entry_score=entry_score,
                        entry_reasons=entry_reasons,
                    )
                    from llm_stock_analyzer import analyze_exit
                    exit_result = analyze_exit(symbol, exit_payload)
                    llm_exit_reason = exit_result.get('llm_reason') or sell_reason
                    # 2026-06-18 east 修复: 让 save_closed_trade 取得这份 LLM 复盘
                    self._last_llm_review = llm_exit_reason if llm_exit_reason and llm_exit_reason != sell_reason else None
                except Exception as e:
                    print(f"⚠️ {symbol} LLM 卖出复盘失败，回退到原始原因: {e}")

                pusher.send_sell_notification(
                    symbol=symbol,
                    quantity=quantity,
                    price=price,
                    amount=amount,
                    pnl_pct=sell_pnl_pct,
                    reason=llm_exit_reason,
                    order_id=result,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
        
        return success
    
    def check_technical_signals(self, symbol, market='us'):
        """检查技术指标信号（根据市场类型选择指标模块）
        
        美股v1.6要求:
        - MA20 > MA50, 价格 > MA20
        - 技术信号 >= 2
        - 成交量 >= 1.8x
        - RSI < 65
        
        港股v2.0要求:
        - MA20上升趋势, 价格 > MA20
        - RSI 35-70
        - 成交量 >= 1.5x
        - 增强信号 >= 1个
        """
        if not TECH_INDICATORS_AVAILABLE:
            print(f"⚠️ 技术指标模块不可用")
            return {
                'score': 0,
                'can_enter': False,
                'reasons': ["技术指标模块不可用"]
            }
        
        print(f"\n🔍 检查技术指标 [{market.upper()}]: {symbol}")
        
        try:
            if market.lower() == 'us':
                # 美股指标
                ti = USTechIndicators()
            else:
                # 港股指标
                ti = HKTechIndicators()
            
            signals = ti.get_entry_signals(symbol)
            ti.close()
            
            # 获取最大分数（美股8分，港股6分）
            max_score = signals.get('max_score', 8)
            print(f"   技术评分: {signals['score']}/{max_score}")
            for reason in signals['reasons']:
                print(f"   {reason}")
            
            return signals
            
        except Exception as e:
            print(f"❌ 技术指标检查失败: {e}")
            return {
                'score': 0,
                'can_enter': False,
                'reasons': [f"检查失败: {e}"]
            }
    
    def normalize_symbol(self, symbol):
        """标准化股票代码，便于持仓和订单匹配"""
        sym = str(symbol or '').upper()
        if sym.startswith('US.') or sym.startswith('HK.'):
            sym = sym[3:]
        return sym.split('.')[0]

    def get_account_position_value(self, account):
        """获取账户当前持仓市值。优先用账户字段，缺失时按持仓求和。"""
        if not account:
            return 0.0
        try:
            account_market_val = float(account.get('market_val', 0) or 0)
            if account_market_val > 0:
                return account_market_val
        except:
            pass
        total = 0.0
        for pos in account.get('positions', []):
            try:
                total += float(pos.get('market_val', 0) or 0)
            except:
                pass
        return total

    def get_symbol_position_value(self, account, symbol):
        """获取单个标的当前持仓市值。"""
        target = self.normalize_symbol(symbol)
        value = 0.0
        for pos in (account or {}).get('positions', []):
            if self.normalize_symbol(pos.get('symbol', '')) == target:
                try:
                    value += float(pos.get('market_val', 0) or 0)
                except:
                    pass
        return value

    def get_score_based_position(self, score, market='us'):
        """按评分计算目标仓位。美股按8%-12%动态调整，港股沿用3%。"""
        if market != 'us':
            return self.hk_config.get('position_size', 0.03)
        try:
            score = float(score or 0)
        except:
            score = 0
        if score < 80:
            return 0.0
        if score < 85:
            return 0.08 + (score - 80) * 0.005  # 80-84: 8%-10%
        if score < 90:
            return 0.10 + (score - 85) * 0.0025  # 85-89: 10%-11%
        if score < 95:
            return 0.11 + (score - 90) * 0.0025  # 90-94: 11%-12%
        return 0.12

    def get_vix_multiplier(self):
        """根据VIX返回美股开仓仓位系数。"""
        now = time.time()
        cached_vix = self._vix_cache.get('value')
        if cached_vix is not None and now - self._vix_cache.get('timestamp', 0) < 300:
            vix = cached_vix
        else:
            try:
                from vix_fetcher import get_vix_index
                vix = float(get_vix_index())
            except Exception as e:
                print(f"⚠️ 获取VIX失败，使用默认20: {e}")
                vix = 20.0
            self._vix_cache = {'value': vix, 'timestamp': now}

        if vix < 20:
            return 1.0, vix, 'VIX<20，正常开仓', None
        if vix <= 25:
            return 0.8, vix, 'VIX 20-25，仓位8折', None
        if vix <= 30:
            return 0.6, vix, 'VIX 25-30，仓位6折，总仓位上限不高于50%', 0.50
        return 0.0, vix, 'VIX>30，暂停开仓', 0.0

    def check_position_limits(self, account, symbol, order_value, market='us'):
        """用实际订单金额检查单票和总仓位硬限制。"""
        total_assets = float((account or {}).get('total_assets', 0) or 0)
        if total_assets <= 0:
            return {'can_add_position': False}, '总资产无效'

        single_limit = self.risk_config.get(f'{market}_single_position_limit', 0.12)
        total_limit = self.risk_config.get(f'{market}_total_position_limit', 1.0)
        current_total_value = self.get_account_position_value(account)
        current_symbol_value = self.get_symbol_position_value(account, symbol)
        after_symbol_value = current_symbol_value + order_value
        after_total_value = current_total_value + order_value
        eps = max(1.0, total_assets * 0.0001)

        result = {
            'single_position_ok': after_symbol_value <= total_assets * single_limit + eps,
            'total_position_ok': after_total_value <= total_assets * total_limit + eps,
            'current_pct': current_total_value / total_assets * 100,
            'after_total_pct': after_total_value / total_assets * 100,
            'after_single_pct': after_symbol_value / total_assets * 100,
            'single_limit_pct': single_limit * 100,
            'total_limit_pct': total_limit * 100,
        }
        result['can_add_position'] = result['single_position_ok'] and result['total_position_ok']

        if not result['single_position_ok']:
            return result, f"单票仓位将达到{result['after_single_pct']:.1f}%，超过{result['single_limit_pct']:.1f}%上限"
        if not result['total_position_ok']:
            return result, f"总仓位将达到{result['after_total_pct']:.1f}%，超过{result['total_limit_pct']:.1f}%上限"
        return result, ''

    def prepare_buy_order(self, account, symbol, price, score, market='us', lot_size=1):
        """统一买入仓位计算和下单前风控。"""
        try:
            price = float(price or 0)
            total_assets = float((account or {}).get('total_assets', 0) or 0)
            cash = float((account or {}).get('cash', 0) or 0)
        except:
            return {'can_buy': False, 'reason': '账户或价格数据无效', 'quantity': 0}

        if price <= 0:
            return {'can_buy': False, 'reason': '价格无效', 'quantity': 0}
        if total_assets <= 0:
            return {'can_buy': False, 'reason': '总资产无效', 'quantity': 0}
        if cash <= 0:
            return {'can_buy': False, 'reason': '现金不足', 'quantity': 0}

        single_limit = self.risk_config.get(f'{market}_single_position_limit', 0.12)
        total_limit = self.risk_config.get(f'{market}_total_position_limit', 1.0)
        base_pct = min(self.get_score_based_position(score, market), single_limit)
        multiplier = 1.0
        vix = None
        vix_reason = ''

        vix_total_limit = None
        multiplier, vix, vix_reason, vix_total_limit = self.get_vix_multiplier()
        if multiplier <= 0:
            return {
                'can_buy': False,
                'reason': f'{vix_reason} (VIX={vix:.1f})',
                'quantity': 0,
                'vix': vix,
                'vix_multiplier': multiplier,
            }
        if vix_total_limit is not None:
            total_limit = min(total_limit, vix_total_limit)

        target_pct = min(base_pct * multiplier, single_limit)
        target_value = total_assets * target_pct
        current_total_value = self.get_account_position_value(account)
        current_symbol_value = self.get_symbol_position_value(account, symbol)
        max_single_value = max(0.0, total_assets * single_limit - current_symbol_value)
        max_total_value = max(0.0, total_assets * total_limit - current_total_value)
        allowed_value = min(target_value, max_single_value, max_total_value, cash)

        if allowed_value <= 0:
            current_pct = current_total_value / total_assets * 100
            return {
                'can_buy': False,
                'reason': f'仓位已满或现金不足，当前总仓位{current_pct:.1f}%',
                'quantity': 0,
                'current_total_pct': current_pct,
            }

        raw_quantity = int(allowed_value / price)
        lot_size = max(1, int(lot_size or 1))
        quantity = (raw_quantity // lot_size) * lot_size
        order_value = quantity * price

        if quantity <= 0 or order_value <= 0:
            return {
                'can_buy': False,
                'reason': f'按风控裁剪后数量为0，可用金额${allowed_value:,.2f}',
                'quantity': 0,
                'target_value': target_value,
                'allowed_value': allowed_value,
            }

        # 守卫：实际下单仓位 < 目标仓位的50% 视为废单（如1股0.00%），直接放弃
        # 动态目标仓位是根据评分/VIX算出来的，低于一半说明现金/风控钳得太死，下了也只是占坑
        if target_value > 0 and order_value < target_value * 0.5:
            actual_pct = (order_value / total_assets * 100) if total_assets > 0 else 0
            target_pct_disp = (target_value / total_assets * 100) if total_assets > 0 else 0
            return {
                'can_buy': False,
                'reason': (f'可下单仓位${order_value:,.0f}({actual_pct:.2f}%) '
                           f'不足目标${target_value:,.0f}({target_pct_disp:.2f}%)的50%，放弃废单'),
                'quantity': 0,
                'target_value': target_value,
                'allowed_value': allowed_value,
                'order_value': order_value,
            }

        position_check, reason = self.check_position_limits(account, symbol, order_value, market)
        if not position_check.get('can_add_position', False):
            return {
                'can_buy': False,
                'reason': reason,
                'quantity': 0,
                'order_value': order_value,
                **position_check,
            }

        return {
            'can_buy': True,
            'quantity': quantity,
            'raw_quantity': raw_quantity,
            'order_value': order_value,
            'target_value': target_value,
            'allowed_value': allowed_value,
            'base_pct': base_pct,
            'target_pct': target_pct,
            'vix': vix,
            'vix_multiplier': multiplier,
            'vix_reason': vix_reason,
            **position_check,
        }
    
    def calculate_stop_loss(self, symbol, multiplier=None, market='us'):
        """计算ATR动态止损
        
        美股v1.6: ATR 1.8-2.0x
        港股v2.0: ATR 1.5x
        """
        if not TECH_INDICATORS_AVAILABLE:
            return None
        
        # 根据市场设置默认multiplier
        if multiplier is None:
            multiplier = 2.0 if market.lower() == 'us' else 1.5
        
        try:
            if market.lower() == 'us':
                ti = USTechIndicators()
            else:
                ti = HKTechIndicators()
            
            sl = ti.get_stop_loss(symbol, multiplier)
            ti.close()
            return sl
        except:
            return None
    
    def calculate_take_profit(self, symbol, multiplier=None, market='us'):
        """计算ATR动态止盈
        
        美股v1.6: ATR 4.0-4.5x
        港股v2.0: ATR 3.0x
        """
        if not TECH_INDICATORS_AVAILABLE:
            return None
        
        # 根据市场设置默认multiplier
        if multiplier is None:
            multiplier = 4.0 if market.lower() == 'us' else 3.0
        
        try:
            if market.lower() == 'us':
                ti = USTechIndicators()
            else:
                ti = HKTechIndicators()
            
            tp = ti.get_take_profit(symbol, multiplier)
            ti.close()
            return tp
        except:
            return None
    
    def load_staged_reductions(self):
        """读取分级减仓状态。"""
        try:
            with open(self.staged_reductions_file, 'r') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except:
            return {}

    def save_staged_reductions(self, staged):
        """保存分级减仓状态。"""
        try:
            with open(self.staged_reductions_file, 'w') as f:
                json.dump(staged, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   ⚠️ 保存分级减仓状态失败: {e}")

    def get_staged_key(self, symbol):
        """分级减仓状态键。"""
        sym = str(symbol or '').upper()
        if sym.startswith('US.') or sym.startswith('HK.'):
            return sym
        return f"US.{sym}"

    def get_position_price(self, pos):
        """根据持仓市值估算当前价格。"""
        shares = int(pos.get('shares', 0) or 0)
        market_val = float(pos.get('market_val', 0) or 0)
        return market_val / shares if shares > 0 else 0

    def has_major_negative_alert(self, symbol):
        """检查是否有结构化重大利空命中该标的。"""
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/alerts.json', 'r') as f:
                data = json.load(f)
        except:
            return False, ''

        target = self.normalize_symbol(symbol)
        for alert in data.get('alerts', []):
            alert_symbol = alert.get('symbol') or ''
            if not alert_symbol or self.normalize_symbol(alert_symbol) != target:
                continue
            importance = str(alert.get('importance', ''))
            alert_type = str(alert.get('alert_type', ''))
            title = str(alert.get('title', ''))
            try:
                sentiment = float(alert.get('sentiment', 0.5))
            except:
                sentiment = 0.5
            is_major = importance in ('高', '重大', '高危') or '重大' in alert_type
            is_negative = sentiment <= 0.2 or '利空' in alert_type or '利空' in title
            if is_major and is_negative:
                return True, title[:80] or alert_type
        return False, ''

    def check_macd_stabilized(self, symbol, market='us'):
        """MACD是否企稳：MACD在线上方视为企稳。无法获取时按未企稳处理。"""
        if not TECH_INDICATORS_AVAILABLE:
            return False, '技术指标模块不可用'
        try:
            ti = USTechIndicators() if market == 'us' else HKTechIndicators()
            df = ti.get_kline(symbol, 90)
            if df is None or len(df) < 35:
                ti.close()
                return False, 'K线不足，MACD未确认企稳'
            macd_data = ti.calc_macd(df['close'])
            ti.close()
            if not macd_data:
                return False, 'MACD数据不足'
            macd = macd_data['macd']
            signal = macd_data['signal']
            prev_macd = macd_data['prev_macd']
            prev_signal = macd_data['prev_signal']
            stabilized = macd >= signal and macd >= prev_macd and prev_macd >= prev_signal
            reason = f"MACD={macd:.3f}, Signal={signal:.3f}, PrevMACD={prev_macd:.3f}"
            return stabilized, reason
        except Exception as e:
            return False, f'MACD检查失败: {e}'

    def mark_staged_reduction(self, symbol, sell_shares, remaining_shares, price, reason, market='us'):
        """记录第一步减仓状态，等待30分钟后复核。"""
        staged = self.load_staged_reductions()
        key = self.get_staged_key(symbol)
        staged[key] = {
            'symbol': key,
            'market': market,
            'status': 'stage1_done',
            'reason': reason,
            'stage1_time': datetime.now().isoformat(),
            'stage1_ts': time.time(),
            'stage1_price': price,
            'stage1_sell_shares': sell_shares,
            'remaining_shares': remaining_shares,
        }
        self.save_staged_reductions(staged)

    def clear_staged_reduction(self, symbol):
        """清除分级减仓状态。"""
        staged = self.load_staged_reductions()
        key = self.get_staged_key(symbol)
        if key in staged:
            del staged[key]
            self.save_staged_reductions(staged)

    def tighten_staged_stop(self, symbol, current_price, market='us'):
        """技术面企稳后保留剩余仓位，并记录1.2x ATR收紧止损线。"""
        staged = self.load_staged_reductions()
        key = self.get_staged_key(symbol)
        stop_price = self.calculate_stop_loss(key, multiplier=1.2, market=market)
        if not stop_price:
            # 如果ATR取不到，至少用当前价下方3%作为保护线，避免状态悬空。
            stop_price = current_price * 0.97 if current_price > 0 else 0
        item = staged.get(key, {})
        item.update({
            'status': 'tightened_stop',
            'tightened_time': datetime.now().isoformat(),
            'tightened_ts': time.time(),
            'tightened_stop_price': stop_price,
            'tightened_multiplier': 1.2,
        })
        staged[key] = item
        self.save_staged_reductions(staged)
        print(f"  🛡️ {key}: 技术面企稳，保留剩余仓位，止损线收紧到1.2x ATR (${stop_price:.2f})")

    def execute_position_sell(self, pos_data, shares, reason, stop_type, market='us'):
        """执行持仓卖出并记录平仓。港股必须按整手卖（全平时除外）。"""
        shares = int(shares or 0)
        if shares <= 0:
            return False
        sym = pos_data.get('symbol', '')
        total_shares = int(pos_data.get('shares', 0) or 0)

        # 港股整手保护：仅"全平"允许直接卖（含历史碎股），否则必须按 lot_size 取整
        if market == 'hk':
            full_sym_for_lot = sym if sym.startswith('HK.') else f"HK.{sym}"
            try:
                lot_size = self._get_hk_lot_size(full_sym_for_lot)
            except Exception:
                lot_size = 100
            lot_size = max(1, int(lot_size or 100))
            if shares < total_shares:  # 部分减仓需要按整手
                aligned = (shares // lot_size) * lot_size
                if aligned <= 0:
                    print(f"  ⚠️ {sym}: 减仓 {shares} 股不足 1 手 ({lot_size})，跳过本次")
                    return False
                if aligned != shares:
                    print(f"  ⚠️ {sym}: 减仓取整手 {shares} → {aligned} 股 (每手{lot_size})")
                    shares = aligned

        price = self.get_position_price(pos_data)
        cost_price = float(pos_data.get('cost_price', 0) or 0)
        current_pl_pct = float(pos_data.get('pl_ratio', 0) or 0)
        full_sym = sym if sym.startswith(('US.', 'HK.')) else f"US.{sym}"

        try:
            ctx = self.hk_trade_ctx if market == 'hk' else self.trade_ctx
            ret, orders = ctx.order_list_query(trd_env=TrdEnv.SIMULATE)
            if ret == 0 and orders is not None:
                pending = orders[orders['order_status'] != 'FILLED_ALL']
                for o in pending.itertuples():
                    if self.normalize_symbol(sym) == self.normalize_symbol(o.code):
                        ctx.cancel_order(str(o.order_id))
                        print(f"  撤销挂单: {o.order_id} ({o.code})")
        except Exception as e:
            print(f"  撤单失败: {e}")

        print(f"  执行{reason}: 卖出 {full_sym} {shares}股 @ ${price:.2f}")
        success = self.execute_trade(full_sym, 'SELL', shares, price, market, force=True, skip_llm=True, reasons=[reason], entry_price_override=cost_price)
        if success:
            # 2026-06-18 east 修复: execute_trade 内部生成的 LLM 复盘从 self._last_llm_review 取
            llm_review = getattr(self, '_last_llm_review', None)
            # 2026-06-24 east 修复: 补上入场上下文，避免 LLM 复盘拿不到评分/理由
            ec = self._lookup_entry_context(full_sym)
            self.save_closed_trade(full_sym, 'SELL', shares, cost_price, price, current_pl_pct, reason, market,
                                    stop_type=stop_type, llm_review=llm_review,
                                    entry_score=ec['entry_score'], entry_reasons=ec['entry_reasons'])
            # 用完即清，避免污染下一笔
            self._last_llm_review = None
            if shares >= total_shares:
                self.remove_open_position(full_sym)
                self.clear_staged_reduction(full_sym)
                self.recently_closed[sym] = time.time()
        return success

    def process_staged_exit(self, pos_data, market='us'):
        """处理分级减仓状态。返回True表示该持仓本轮已处理。"""
        sym = pos_data.get('symbol', '')
        key = self.get_staged_key(sym)
        staged = self.load_staged_reductions()
        item = staged.get(key)
        if not item:
            return False

        shares = int(pos_data.get('shares', 0) or 0)
        price = self.get_position_price(pos_data)
        if item.get('status') == 'stage1_done':
            # 复核期硬止损：不管多久，一旦累计亏损 ≤ -10%，立即全平剩余仓位
            # 防止“首次触发-6.94% → 30分钟复核期被动挨打到-12%+”的场景
            try:
                hard_stop_pl = float(pos_data.get('pl_ratio', 0) or 0) * 100  # pl_ratio是小数，转%
            except Exception:
                hard_stop_pl = 0.0
            if hard_stop_pl <= -10.0 and shares > 0:
                print(f"  🚨 {key}: 复核期累计亏损{hard_stop_pl:.2f}% ≤ -10%，穿透复核期硬止损，立即全平")
                self.execute_position_sell(pos_data, shares, '复核期硬止损-10%全平', 'staged_hard_stop', market)
                return True

            elapsed = time.time() - float(item.get('stage1_ts', 0) or 0)
            if elapsed < 1800:
                print(f"  ⏳ {key}: 分级减仓等待复核中，还需{(1800-elapsed)/60:.1f}分钟（当前累计{hard_stop_pl:+.2f}%，硬止损线-10%）")
                return True

            stage1_price = float(item.get('stage1_price', price) or price)
            price_continue_down = price < stage1_price
            macd_stable, macd_reason = self.check_macd_stabilized(key, market)
            print(f"  🔎 {key}: 30分钟复核，价格{'继续下跌' if price_continue_down else '未继续下跌'}，{macd_reason}")

            if price_continue_down and not macd_stable:
                print(f"  ⚠️ {key}: 价格继续下跌且MACD未企稳，全平剩余仓位")
                self.execute_position_sell(pos_data, shares, '分级止损第二步全平', 'staged_stop_full_exit', market)
            else:
                self.tighten_staged_stop(key, price, market)
            return True

        if item.get('status') == 'tightened_stop':
            stop_price = float(item.get('tightened_stop_price', 0) or 0)
            if stop_price > 0 and price <= stop_price:
                print(f"  ⚠️ {key}: 跌破1.2x ATR收紧止损线 ${stop_price:.2f}，全平剩余仓位")
                self.execute_position_sell(pos_data, shares, '收紧止损触发全平', 'tightened_atr_stop', market)
            else:
                print(f"  🛡️ {key}: 分级减仓后持有，当前${price:.2f}，收紧止损${stop_price:.2f}")
            return True

        return False

    def trigger_stage_one_reduction(self, pos_data, reason, market='us'):
        """触发分级减仓第一步：先减50%。港股必须按整手。"""
        sym = pos_data.get('symbol', '')
        shares = int(pos_data.get('shares', 0) or 0)
        if shares <= 0:
            return False
        sell_shares = max(1, shares // 2)
        # 港股裁到整手，避免碎股底层报错
        if market == 'hk':
            full_sym_for_lot = sym if sym.startswith('HK.') else f"HK.{sym}"
            try:
                lot_size = self._get_hk_lot_size(full_sym_for_lot)
            except Exception:
                lot_size = 100
            lot_size = max(1, int(lot_size or 100))
            sell_shares = (sell_shares // lot_size) * lot_size
            if sell_shares <= 0:
                print(f"  ⚠️ {sym}: 50%减仓不足一手（持仓{shares} 每手{lot_size}），改为全平")
                return self.execute_position_sell(pos_data, shares, reason, 'staged_stop_full_for_small_position', market)
        remaining = max(0, shares - sell_shares)
        if remaining == 0:
            return self.execute_position_sell(pos_data, shares, reason, 'staged_stop_full_for_small_position', market)
        price = self.get_position_price(pos_data)
        success = self.execute_position_sell(pos_data, sell_shares, f'{reason}第一步减50%', 'staged_stop_half_exit', market)
        if success:
            self.mark_staged_reduction(sym, sell_shares, remaining, price, reason, market)
            print(f"  ⏳ {self.get_staged_key(sym)}: 已减{sell_shares}股，30分钟后复核剩余{remaining}股")
        return success

    def is_flash_crash_pattern(self, symbol, market='us'):
        """判断当前止损是否符合“瞬间插针”模式，只有插针才走分级减仓。

        三个条件必须同时满足：
        1) 快速下跌：最近 5 分钟跌幅 ≥ 2%（个股分钟K线）
        2) 大盘未同步暴跌：当日大盘指数跌幅 < 1%（恒指/标普）
        3) 无重大利空：调用方应在此前已确认非 major_negative；本函数再兜底一次

        返回 (bool, reason_str)。任意条件不满足返回 False，并给出原因。
        """
        # 兜底：重大利空直接否决
        try:
            mn, _mn_reason = self.has_major_negative_alert(symbol)
            if mn:
                return False, '存在重大利空，禁用分级'
        except Exception:
            pass

        # === 条件1：个股最近 5 分钟跌幅 ≥ 2% ===
        full_sym = symbol
        if market == 'hk' and not full_sym.startswith('HK.'):
            full_sym = f'HK.{symbol}'
        if market == 'us' and not full_sym.startswith('US.'):
            full_sym = f'US.{symbol}'

        recent_drop_pct = None
        try:
            from futu import KLType, AuType
            ctx = self.quote_ctx
            if ctx is None:
                from futu import OpenQuoteContext
                ctx = OpenQuoteContext('127.0.0.1', 11111)
            ret, kl = ctx.get_cur_kline(full_sym, 6, KLType.K_1M, AuType.QFQ)
            if ret == 0 and kl is not None and len(kl) >= 2:
                # 取最早一根（5分钟前）的开盘价 vs 最新一根的收盘价
                start_price = float(kl.iloc[0]['open'])
                cur_price = float(kl.iloc[-1]['close'])
                if start_price > 0:
                    recent_drop_pct = (cur_price - start_price) / start_price * 100
        except Exception as e:
            return False, f'分钟K线获取失败({e})，保守走全平'

        if recent_drop_pct is None:
            return False, '分钟K线数据不足，保守走全平'
        if recent_drop_pct > -2.0:
            return False, f'5分钟跌幅 {recent_drop_pct:+.2f}% 未达-2%阈值（属阴跌/趋势性下跌）'

        # === 条件2：大盘当日跌幅 < 1% ===
        market_change = None
        try:
            import requests
            idx_sym = '%5EGSPC' if market.lower() == 'us' else '%5EHSI'
            r = requests.get(
                f'https://query1.finance.yahoo.com/v8/finance/chart/{idx_sym}',
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=3,
            )
            if r.status_code == 200:
                meta = r.json()['chart']['result'][0]['meta']
                cur = float(meta['regularMarketPrice'])
                prev = float(meta.get('previousClose') or meta.get('chartPreviousClose') or cur)
                if prev:
                    market_change = (cur - prev) / prev * 100
        except Exception as e:
            return False, f'大盘指数获取失败({e})，保守走全平'

        if market_change is None:
            return False, '大盘指数获取失败，保守走全平'
        if market_change <= -1.0:
            return False, f'大盘同步下跌 {market_change:+.2f}% ≤ -1%（系统性抛压）'

        return True, f'5min跌{recent_drop_pct:+.2f}% & 大盘{market_change:+.2f}% → 判定为插针'

    def run(self):
        """执行交易检查"""
        print(f"\n{'='*60}")
        print(f"🤖 自动交易执行器 v2.1 (技术指标版)")
        print(f"{'='*60}")
        # 连接Futu（如果未连接）
        if not self.trade_ctx:
            print("连接Futu...")
            if not self.connect_futu():
                print("❌ 无法连接Futu")
                return
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 检查交易时间
        us_trading = self.check_trading_hours('us')
        hk_trading = self.check_trading_hours('hk')
        
        print(f"\n交易时间状态:")
        print(f"  美股: {'✅ 盘中' if us_trading else '⏸️ 非交易时间'}")
        print(f"  港股: {'✅ 盘中' if hk_trading else '⏸️ 非交易时间'}")
        
        # 获取美股账户信息
        us_account = None
        hk_account = None
        
        if us_trading:
            us_account = self.get_account_and_positions('us')
            if not us_account:
                print("❌ 无法获取美股账户信息")
                us_trading = False
        
        if hk_trading:
            hk_account = self.get_account_and_positions('hk')
            if not hk_account:
                print("❌ 无法获取港股账户信息")
                hk_trading = False
        
        if not us_trading and not hk_trading:
            # 仅美股非交易时间发送机会通知，港股交易时间正常交易不发
            now_time = datetime.now().time()
            market_status = ""
            # 美股非交易时段划分（与 us-scanner 交易时段 21:30-04:00 对齐）
            # 盘后：04:00 - 08:00 ，夜盘（美股休市）：08:00 - 16:00 ，盘前：16:00 - 21:30
            if dt_time(4, 0) <= now_time <= dt_time(8, 0):
                market_status = "盘后"
            elif dt_time(8, 0) < now_time < dt_time(16, 0):
                market_status = "夜盘"
            elif dt_time(16, 0) <= now_time < dt_time(21, 30):
                market_status = "盘前"

            if market_status:
                # 加载美股机会
                opportunities = self.get_opportunities()
                # 2026-06-25 east 决策：非交易时段保留高门槛（默认90），避免在凌晨推中等货
                # 交易时段 min_score=80 走自动下单，这里走推送提醒，两者隔离
                opp_threshold = self.us_config.get('opp_alert_score', 90)
                us_high = [o for o in opportunities['us'] if o.get('score', 0) >= opp_threshold]

                # 发送美股机会
                for o in us_high[:3]:
                    symbol = o.get('symbol', '')
                    score = o.get('score', 0)
                    # 冷却：24小时内同一个股票只发一次（持久化到 notify_cooldown_file，跨进程生效）
                    cool_key = f"opp_{symbol}"
                    last_ts = self.recently_closed.get(cool_key, 0)
                    if last_ts and time.time() - last_ts < 86400:
                        age_h = (time.time() - last_ts) / 3600
                        print(f"  ⏸️ 跳过 {symbol}: 24h冷却中（已过{age_h:.1f}h）")
                        continue
                    try:
                        from feishu_pusher import FeishuPusher
                        pusher = FeishuPusher()
                        # 统一使用动态评分/LLM详情，避免机会通知和买入通知口径不一致
                        signal_details = self.build_dynamic_signal_details(
                            symbol=f"US.{symbol}",
                            market='us',
                            score=score,
                            llm_analysis=None,
                            reasons=o.get('reasons', []),
                        )
                        pusher.send_opportunity_notification(
                            symbol=f"US.{symbol}",
                            score_total=signal_details['score_total'],
                            score_news=signal_details['score_news'],
                            score_announce=signal_details['score_announce'],
                            score_community=signal_details['score_community'],
                            score_institution=signal_details['score_institution'],
                            signal_type=signal_details['signal_type'],
                            llm_conclusion=signal_details['llm_conclusion'],
                            estimated_keys=signal_details.get('estimated_keys', []),
                            evidences={
                                'news': signal_details.get('evidence_news', ''),
                                'announce': signal_details.get('evidence_announce', ''),
                                'community': signal_details.get('evidence_community', ''),
                                'institution': signal_details.get('evidence_institution', ''),
                            },
                            market_status=market_status,
                            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        )
                        self.recently_closed[f"opp_{symbol}"] = time.time()
                        self._save_notify_cooldowns()
                        print(f"  ✅ 已发送美股{market_status}机会通知: US.{symbol} (评分{score}分，已加24h冷却)")
                    except Exception as e:
                        print(f"  ⚠️ 发送美股{market_status}机会通知失败: {e}")

            print("⏸️ 非交易时间，仅发送机会通知")
            return
        
        # 显示账户状态
        if us_account:
            print(f"\n📊 美股账户状态:")
            print(f"  总资产: ${us_account['total_assets']:,.2f}")
            print(f"  现金: ${us_account['cash']:,.2f}")
            print(f"  持仓: {len(us_account['positions'])}只")
        
        if hk_account:
            print(f"\n📊 港股账户状态:")
            print(f"  总资产: ${hk_account['total_assets']:,.2f}")
            print(f"  现金: ${hk_account['cash']:,.2f}")
            print(f"  持仓: {len(hk_account['positions'])}只")
        
        # 止损/止盈检查：使用策略规则
        # 规则：ATR动态止损(1.8-2.0x)、ATR动态止盈(4.0-4.5x)、RSI超买(>70)、MACD死叉、最大持仓6天
        print(f"\n🔍 检查止损/止盈...")
        positions_to_close = []
        positions_to_stage_reduce = []
        stage_reduce_reasons = {}
        positions_to_take_profit = []
        
        # 修复：根据交易时间检查对应的账户持仓
        # 美股交易时间检查美股持仓，港股交易时间检查港股持仓
        account_to_check = None
        market_to_check = ''
        
        if us_trading:
            account_to_check = us_account
            market_to_check = 'us'
            print(f"  📊 检查美股持仓")
        elif hk_trading:
            account_to_check = hk_account
            market_to_check = 'hk'
            print(f"  📊 检查港股持仓")
        else:
            account_to_check = {'positions': []}
            print(f"  ⚠️ 非交易时间，不检查持仓")
        
        account = account_to_check if account_to_check else {'positions': []}
        
        for pos in account['positions']:
            sym = pos.get('symbol', '')
            shares = pos.get('shares', 0)
            if shares <= 0:
                continue
            
            # pl_ratio已经是百分比形式（如-1.01表示-1.01%），不需要转换
            pl_pct = float(pos.get('pl_ratio', 0))  # 已经是百分比形式：-1.01 表示 -1.01%
            
            # 更新峰值浮盈
            self.update_peak_profit(sym, pl_pct)
            
            print(f"  {sym}: 盈亏 {pl_pct:+.2f}%")

            if self.process_staged_exit(pos, market_to_check):
                continue

            major_negative, negative_reason = self.has_major_negative_alert(sym)
            
            # 止损条件：亏损超过6% 或结构化重大利空触发
            if pl_pct < -6 or major_negative:
                # 跳过刚平过的标的（防止重复平仓）
                if sym in self.recently_closed and time.time() - self.recently_closed[sym] < self.cooldown_seconds:
                    print(f"    ⏭️ {sym} 刚平过，跳过")
                    continue

                # 2026-06-23 east 重构：默认直接全平，只有插针场景才走分级
                # 重大利空 → 一律全平（利空不会反弹，等于送钱）
                if major_negative:
                    positions_to_close.append(sym)
                    if pl_pct > 0:
                        stage_reduce_reasons[sym] = '重大利空触发全平(盈利中风控)'
                        print(f"    ⚠️ 重大利空→直接全平! {negative_reason}")
                    else:
                        stage_reduce_reasons[sym] = '重大利空触发全平'
                        print(f"    ⚠️ 重大利空→直接全平! {negative_reason}")
                    continue

                # 纯价格止损：判定是否插针
                is_flash, flash_reason = self.is_flash_crash_pattern(sym, market_to_check)
                if is_flash:
                    positions_to_stage_reduce.append(sym)
                    stage_reduce_reasons[sym] = '插针触发分级减仓'
                    print(f"    ⚠️ 插针模式→分级减仓! ({flash_reason}，亏损{pl_pct:+.2f}%)")
                else:
                    positions_to_close.append(sym)
                    stage_reduce_reasons[sym] = '趋势性下跌触发全平'
                    print(f"    ⚠️ 非插针→直接全平! ({flash_reason}，亏损{pl_pct:+.2f}%)")
            
            # 止盈条件：盈利超过8% (ATR止盈4.0-4.5x的简化)
            elif pl_pct > 8:
                # 跳过刚平过的标的
                if sym in self.recently_closed and time.time() - self.recently_closed[sym] < self.cooldown_seconds:
                    print(f"    ⏭️ {sym} 刚平过，跳过")
                    continue
                positions_to_take_profit.append(sym)
                print(f"    🎯 触发止盈! (盈利{pl_pct:.2f}% > 8%)")
        
        # 执行分级减仓第一步
        print(f"  📋 分级减仓列表: {positions_to_stage_reduce}")
        if positions_to_stage_reduce:
            for sym in positions_to_stage_reduce:
                pos_data = next((p for p in account['positions'] if p.get('symbol','') == sym), None)
                if not pos_data:
                    print(f"  ❌ 分级减仓跳过: 未找到持仓 {sym}，当前持仓={[p.get('symbol','') for p in account['positions']]}")
                    continue
                reason = stage_reduce_reasons.get(sym, '风控触发分级减仓')
                self.trigger_stage_one_reduction(pos_data, reason, market_to_check)

        # 执行需要全平的止损
        if positions_to_close:
            for sym in positions_to_close:
                pos_data = next((p for p in account['positions'] if p.get('symbol','') == sym), None)
                if not pos_data:
                    print(f"  ❌ 全平跳过: 未找到持仓 {sym}")
                    continue
                # 2026-06-23 east: 使用具体原因（重大利空/趋势性下跌）而非通用“止损全平”
                close_reason = stage_reduce_reasons.get(sym, '止损全平')
                close_stop_type = 'major_negative' if '重大利空' in close_reason else 'max_loss_stop'
                self.execute_position_sell(pos_data, int(pos_data.get('shares', 0)), close_reason, close_stop_type, market_to_check)

        # 执行止盈（防重复触发：冷却保护 + 同标的本轮去重）
        if positions_to_take_profit:
            done_syms = set()
            for sym in positions_to_take_profit:
                # 1) 同一执行流程内同标的不重复触发（避免内存中persistence 重复）
                if sym in done_syms:
                    continue
                done_syms.add(sym)

                # 2) recently_closed 冷却检查：防止短时间内对同一标的重复SELL
                if sym in self.recently_closed and time.time() - self.recently_closed[sym] < self.cooldown_seconds:
                    print(f"  ⏭️ {sym}: 最近已平仓，跳过止盈")
                    continue

                pos_data = next((p for p in account['positions'] if p.get('symbol','').replace('US.','').replace('HK.','') == sym.replace('US.','').replace('HK.','')), None)
                if pos_data:
                    shares = int(pos_data.get('shares', 0))
                    if shares <= 0:
                        print(f"  ⏭️ {sym}: 持仓为0，跳过止盈")
                        continue
                    market_val = pos_data.get('market_val', 0)
                    cost_price = pos_data.get('cost_price', 0)
                    price = market_val / shares if shares > 0 else 0
                    # 获取当前股票的盈亏比例
                    current_pl_pct = float(pos_data.get('pl_ratio', 0))
                    
                    # 判断市场
                    if sym.startswith('HK.'):
                        market = 'hk'
                        full_sym = sym
                    else:
                        market = 'us'
                        full_sym = f"US.{sym}" if not sym.startswith('US.') else sym

                    # 3) 下单前再用 Futu 实时查持仓，避免 account[positions] 已过期
                    try:
                        ctx = self.hk_trade_ctx if market == 'hk' else self.trade_ctx
                        ret, real_pos = ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
                        if ret == 0 and real_pos is not None:
                            row = real_pos[real_pos['code'] == full_sym]
                            if len(row) == 0:
                                print(f"  ⏭️ {sym}: 实时查询无持仓，跳过止盈")
                                self.recently_closed[sym] = time.time()
                                continue
                            real_qty = int(row.iloc[0].get('qty', 0) or 0)
                            if real_qty <= 0:
                                print(f"  ⏭️ {sym}: 实时持仓为0，跳过止盈")
                                self.recently_closed[sym] = time.time()
                                continue
                            if real_qty < shares:
                                print(f"  ⚠️ {sym}: 内存{shares}股 vs 实际{real_qty}股，按实际下单")
                                shares = real_qty
                    except Exception as e:
                        print(f"  ⚠️ {sym}: 实时持仓核对失败 ({e})，按内存数据下单")

                    print(f"  执行止盈: 卖出 {sym} {shares}股 @ ${price:.2f}")
                    success = self.execute_trade(full_sym, 'SELL', shares, price, market, force=True, skip_llm=True, reasons=['止盈'], entry_price_override=cost_price)
                    if success:
                        # 保存平仓记录（使用 Futu 的成本价）
                        llm_review = getattr(self, '_last_llm_review', None)
                        # 2026-06-24 east 修复: 同步入场上下文
                        ec = self._lookup_entry_context(full_sym)
                        self.save_closed_trade(full_sym, 'SELL', shares, cost_price, price, current_pl_pct, '止盈', market,
                                                stop_type='take_profit', llm_review=llm_review,
                                                entry_score=ec['entry_score'], entry_reasons=ec['entry_reasons'])
                        self._last_llm_review = None
                        # 移除入场记录
                        self.remove_open_position(full_sym)
                        self.recently_closed[sym] = time.time()
        
        # 获取机会
        opportunities = self.get_opportunities()
        
        # 处理美股
        if us_trading and us_account:
            us_high = [o for o in opportunities['us'] if o.get('score', 0) >= self.config['min_score']]
            print(f"\n🇺🇸 美股高评分({self.config['min_score']}分+): {len(us_high)}只")
            
            for o in us_high[:3]:
                symbol = o.get('symbol', '')
                price = o.get('price', 0)
                score = o.get('score', 0)
                
                # 检查扫描器中LLM是否未通过
                if not o.get('llm_passed', True):
                    print(f"  ⏭️ {symbol}: LLM分析未通过，跳过")
                    continue
                
                futu_symbol = f"US.{symbol}"
                should, reason = self.should_trade(futu_symbol, us_account['positions'], us_account.get('pending_orders', []))
                
                if should:
                    # ===== v1.6 技术指标检查 =====
                    # 检查技术信号（美股: MA趋势、RSI、成交量、MACD）
                    tech_signals = self.check_technical_signals(symbol, market='us')
                    
                    if not tech_signals.get('can_enter', False):
                        print(f"  ⏭️ {symbol}: 技术指标不满足入场条件")
                        for r in tech_signals.get('reasons', []):
                            print(f"      {r}")
                        continue  # 跳过不满足技术条件的股票
                    
                    order_plan = self.prepare_buy_order(us_account, futu_symbol, price, score, market='us')
                    if not order_plan.get('can_buy'):
                        print(f"  ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                        continue

                    quantity = order_plan['quantity']
                    print(
                        f"  💰 {symbol}: 评分仓位{order_plan['base_pct']*100:.1f}% "
                        f"× VIX系数{order_plan.get('vix_multiplier', 1):.1f} "
                        f"→ 实际金额${order_plan['order_value']:,.2f}, "
                        f"总仓位{order_plan['after_total_pct']:.1f}%/{order_plan['total_limit_pct']:.0f}%"
                    )
                    # 构建开仓原因列表
                    entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                    success = self.execute_trade(futu_symbol, 'BUY', quantity, price, 'us', score=score, reasons=entry_reasons)
                    if success:
                        # 更新持仓计数和本轮内存市值，避免同一轮连续突破总仓位
                        us_account['positions'].append({'symbol': futu_symbol, 'shares': quantity, 'market_val': order_plan['order_value']})
                        us_account['market_val'] = us_account['total_assets'] * order_plan['after_total_pct'] / 100
                        us_account['cash'] = max(0, us_account.get('cash', 0) - order_plan['order_value'])
                        if len(us_account['positions']) >= self.config['max_positions']:
                            break
                else:
                    print(f"  ⏭️ {symbol}: {reason}")
        
        # 处理港股
        if hk_trading and hk_account:
            hk_high = [o for o in opportunities['hk'] if o.get('base_score', 0) >= self.config['min_score']]
            print(f"\n🇭🇰 港股高评分({self.config['min_score']}分+): {len(hk_high)}只")
            
            # 检查港股持仓数限制
            if len(hk_account['positions']) >= self.hk_config.get('max_positions', 10):
                print(f"⚠️ 港股已达最大持仓数 {self.hk_config.get('max_positions', 10)}，不执行新交易")
                return
            
            for o in hk_high[:3]:
                symbol = o.get('symbol', '')
                price = o.get('price', 0)
                score = o.get('base_score', 0)
                
                # 检查扫描器中LLM是否未通过
                if not o.get('llm_passed', True):
                    print(f"  ⏭️ {symbol}: LLM分析未通过，跳过")
                    continue
                
                should, reason = self.should_trade(symbol, hk_account['positions'], hk_account.get('pending_orders', []))
                
                if should:
                    # ===== 港股v2.0 技术指标检查 =====
                    # 检查技术信号（港股: MA20趋势、RSI 35-70、成交量1.5x、增强信号）
                    tech_signals = self.check_technical_signals(symbol, market='hk')
                    
                    if not tech_signals.get('can_enter', False):
                        print(f"  ⏭️ {symbol}: 技术指标不满足入场条件")
                        for r in tech_signals.get('reasons', []):
                            print(f"      {r}")
                        continue
                    
                    lot_size = self._get_hk_lot_size(symbol)
                    order_plan = self.prepare_buy_order(hk_account, symbol, price, score, market='hk', lot_size=lot_size)
                    if not order_plan.get('can_buy'):
                        print(f"  ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                        continue

                    quantity = order_plan['quantity']
                    print(
                        f"  💰 {symbol}: 价格{price}, 原始数量{order_plan['raw_quantity']}, "
                        f"整手数量{quantity}(每手{lot_size}), 实际金额${order_plan['order_value']:,.2f}, "
                        f"总仓位{order_plan['after_total_pct']:.1f}%/{order_plan['total_limit_pct']:.0f}%"
                    )
                    # 构建开仓原因列表
                    entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                    success = self.execute_trade(symbol, 'BUY', quantity, price, 'hk', score=score, reasons=entry_reasons)
                    if success:
                        hk_account['positions'].append({'symbol': symbol, 'shares': quantity, 'market_val': order_plan['order_value']})
                        hk_account['market_val'] = hk_account['total_assets'] * order_plan['after_total_pct'] / 100
                        hk_account['cash'] = max(0, hk_account.get('cash', 0) - order_plan['order_value'])
                        if len(hk_account['positions']) >= self.hk_config.get('max_positions', 10):
                            break
                else:
                    print(f"  ⏭️ {symbol}: {reason}")
        
        print(f"\n{'='*60}")
        print(f"✅ 检查完成")
        print(f"{'='*60}")
    
    def llm_analysis_before_trade(self, symbol, price, market='us'):
        """下单前的LLM分析
        
        触发条件：基础评分 ≥ 70分
        使用 ModelStudio API (qwen-plus) 进行分析
        """
        try:
            # 导入LLM调用模块
            sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
            from llm_stock_analyzer import analyze_stock as llm_analyze
            
            # 准备股票数据（从行情获取更完整的数据）
            stock_data = {
                'symbol': symbol,
                'market': market,
                'price': price,
                'change_pct': 0,  # 涨跌幅
                'ma20': 0,
                'ma50': 0,
                'rsi': 50,
                'macd': '未知',
                'volume_ratio': 1.0,
                'atr': 0,
                'news_count': 0,
                'sentiment': '中性',
                'base_score': 75  # 假设基础评分
            }
            
            # 尝试从行情获取更多数据
            try:
                from futu import OpenQuoteContext
                ctx = OpenQuoteContext('127.0.0.1', 11111)
                ret, snapshot = ctx.get_market_snapshot([symbol])
                if ret == 0 and not snapshot.empty:
                    row = snapshot.iloc[0]
                    stock_data['change_pct'] = float(row.get('change_rate', 0))
                    stock_data['volume_ratio'] = float(row.get('volume_ratio', 1.0)) if 'volume_ratio' in row else 1.0
                ctx.close()
            except:
                pass
            
            # 调用LLM分析
            result = llm_analyze(symbol, stock_data)
            
            print(f"\n🧠 LLM分析结果:")
            print(f"   基础评分: {result.get('base_score', 0)}")
            print(f"   评分调整: {result.get('score_adjust', 0):+d}")
            print(f"   最终评分: {result.get('final_score', 0)}")
            print(f"   理由: {result.get('llm_reason', 'N/A')}")
            
            return result
            
        except Exception as e:
            print(f"❌ LLM分析失败: {e}")
            # LLM分析失败时，必须阻止交易
            return {'final_score': 0, 'llm_reason': f'LLM分析失败: {e}', 'passed': False}
    
    def send_notification(self, message):
        """发送通知到飞书"""
        try:
            with open('/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json', 'r') as f:
                keys = json.load(f)
            
            # 获取token
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
            res = requests.post(url, json={
                "app_id": keys['feishu']['appId'],
                "app_secret": keys['feishu']['appSecret']
            }, timeout=10)
            
            if res.status_code == 200 and res.json().get('code') == 0:
                token = res.json().get('tenant_access_token')
                
                # 发送消息
                url = "https://open.feishu.cn/open-apis/im/v1/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                params = {"receive_id_type": "chat_id"}
                data = {
                    "receive_id": self.feishu_chat_id or "oc_f6c5168cb212e624d21ccfabed49b083",
                    "msg_type": "text",
                    "content": json.dumps({"text": message})
                }
                res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
                result = res.json()
                if res.status_code == 200 and result.get('code') == 0:
                    print("✅ 通知已发送到飞书")
                else:
                    print(f"⚠️ 飞书发送失败: {result.get('code')} {result.get('msg', '')}")
        except Exception as e:
            print(f"⚠️ 发送通知失败: {e}")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--daemon', action='store_true', help='守护进程模式（每秒运行）')
    args = parser.parse_args()
    
    if args.daemon:
        # 守护进程模式
        print("=" * 60)
        print("🚀 自动交易守护进程启动 (每秒检查)")
        print("=" * 60)
        
        trader = AutoTrader()
        
        # 连接一次
        if not trader.connect_futu():
            print("无法连接富途，退出")
            exit(1)
        
        print("✅ 就绪，每秒检查交易机会...")
        print("⚠️ 按 Ctrl+C 停止")
        print("=" * 60)
        
        last_positions = []
        
        while True:
            try:
                now = datetime.now().strftime("%H:%M:%S")
                
                # 检查交易时段
                us_trading = trader.check_trading_hours('us')
                hk_trading = trader.check_trading_hours('hk')
                
                if not us_trading and not hk_trading:
                    time.sleep(1)
                    continue
                
                # 获取账户信息
                us_account = None
                hk_account = None
                
                if us_trading:
                    us_account = trader.get_account_and_positions('us')
                if hk_trading:
                    hk_account = trader.get_account_and_positions('hk')
                
                if not us_account and not hk_account:
                    print(f"[{now}] ⚠️ 无可用账户，跳过")
                    time.sleep(1)
                    continue
                
                print(f"[{now}] ✅ 账户获取成功: 美股={'是' if us_account else '否'}, 港股={'是' if hk_account else '否'}")
                
                # ===== 止损/止盈检查 =====
                if us_account and us_account.get('positions'):
                    print(f"[{now}] 🔍 检查止损/止盈...")
                    for pos in us_account['positions']:
                        sym = pos.get('symbol', '')
                        shares = pos.get('shares', 0)
                        if shares <= 0:
                            continue
                        
                        # 跳过最近尝试过平仓的标的（避免频繁下单）
                        if sym in trader.recently_closed:
                            age = time.time() - trader.recently_closed[sym]
                            if age < 86400:  # 24小时冷却期
                                print(f"[{now}]   {sym}: 冷却中({age:.0f}s)，跳过")
                                continue
                        
                        # pl_ratio已经是百分比形式（如-1.01表示-1.01%），不需要转换
                        pl_pct = float(pos.get('pl_ratio', 0))
                        market_val = pos.get('market_val', 0)
                        price = market_val / shares if shares > 0 else 0
                        
                        print(f"[{now}]   {sym}: 盈亏 {pl_pct:+.2f}%")

                        if trader.process_staged_exit(pos, 'us'):
                            continue

                        major_negative, negative_reason = trader.has_major_negative_alert(sym)
                        cost_price = pos.get('cost_price', 0) or 0  # 止盈分支需要
                        
                        # 2026-06-23 east 重构：默认直接全平，只有插针场景走分级
                        if pl_pct < -6 or major_negative:
                            # 重大利空 → 一律全平
                            if major_negative:
                                close_reason = '重大利空触发全平' + ('(盈利中风控)' if pl_pct > 0 else '')
                                print(f"[{now}]   ⚠️ 重大利空→直接全平! {negative_reason}")
                                success = trader.execute_position_sell(pos, int(shares), close_reason, 'major_negative', 'us')
                                if success:
                                    print(f"[{now}]   ✅ 全平完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 全平失败: {sym}")
                                continue

                            # 纯价格止损：判定插针
                            is_flash, flash_reason = trader.is_flash_crash_pattern(sym, 'us')
                            if is_flash:
                                stage_reason = '插针触发分级减仓'
                                print(f"[{now}]   ⚠️ 插针模式→分级减仓! ({flash_reason}，亏损{pl_pct:+.2f}%)")
                                success = trader.trigger_stage_one_reduction(pos, stage_reason, 'us')
                                if success:
                                    print(f"[{now}]   ✅ 分级减仓第一步完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 分级减仓失败，将继续监控")
                            else:
                                close_reason = '趋势性下跌触发全平'
                                print(f"[{now}]   ⚠️ 非插针→直接全平! ({flash_reason}，亏损{pl_pct:+.2f}%)")
                                success = trader.execute_position_sell(pos, int(shares), close_reason, 'max_loss_stop', 'us')
                                if success:
                                    print(f"[{now}]   ✅ 全平完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 全平失败: {sym}")
                        # 止盈：盈利超过8%
                        elif pl_pct > 8:
                            print(f"[{now}]   🎯 触发止盈! (盈利{pl_pct:.2f}% > 8%)")
                            success = trader.execute_trade(sym, 'SELL', shares, price, 'us', force=True, skip_llm=True, reasons=[f'止盈触发：盈利{pl_pct:.2f}% > 8%'], entry_price_override=cost_price)
                            if success:
                                print(f"[{now}]   ✅ 止盈完成: {sym}")
                            else:
                                print(f"[{now}]   ❌ 止盈失败，将在24小时后重试")
                                trader.recently_closed[sym] = time.time()

                # ===== 港股止损/止盈检查（2026-06-23 补上，原本daemon模式遗漏）=====
                if hk_account and hk_account.get('positions'):
                    print(f"[{now}] 🔍 检查港股止损/止盈...")
                    for pos in hk_account['positions']:
                        sym = pos.get('symbol', '')
                        shares = pos.get('shares', 0)
                        if shares <= 0:
                            continue

                        if sym in trader.recently_closed:
                            age = time.time() - trader.recently_closed[sym]
                            if age < 86400:
                                print(f"[{now}]   {sym}: 冷却中({age:.0f}s)，跳过")
                                continue

                        pl_pct = float(pos.get('pl_ratio', 0))
                        market_val = pos.get('market_val', 0)
                        price = market_val / shares if shares > 0 else 0
                        cost_price = pos.get('cost_price', 0) or 0

                        print(f"[{now}]   {sym}: 盈亏 {pl_pct:+.2f}%")

                        if trader.process_staged_exit(pos, 'hk'):
                            continue

                        major_negative, negative_reason = trader.has_major_negative_alert(sym)

                        # 同美股逻辑：默认全平，插针才分级
                        if pl_pct < -6 or major_negative:
                            if major_negative:
                                close_reason = '重大利空触发全平' + ('(盈利中风控)' if pl_pct > 0 else '')
                                print(f"[{now}]   ⚠️ 重大利空→直接全平! {negative_reason}")
                                success = trader.execute_position_sell(pos, int(shares), close_reason, 'major_negative', 'hk')
                                if success:
                                    print(f"[{now}]   ✅ 全平完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 全平失败: {sym}")
                                continue

                            is_flash, flash_reason = trader.is_flash_crash_pattern(sym, 'hk')
                            if is_flash:
                                stage_reason = '插针触发分级减仓'
                                print(f"[{now}]   ⚠️ 插针模式→分级减仓! ({flash_reason}，亏损{pl_pct:+.2f}%)")
                                success = trader.trigger_stage_one_reduction(pos, stage_reason, 'hk')
                                if success:
                                    print(f"[{now}]   ✅ 分级减仓第一步完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 分级减仓失败，将继续监控")
                            else:
                                close_reason = '趋势性下跌触发全平'
                                print(f"[{now}]   ⚠️ 非插针→直接全平! ({flash_reason}，亏损{pl_pct:+.2f}%)")
                                success = trader.execute_position_sell(pos, int(shares), close_reason, 'max_loss_stop', 'hk')
                                if success:
                                    print(f"[{now}]   ✅ 全平完成: {sym}")
                                else:
                                    print(f"[{now}]   ❌ 全平失败: {sym}")
                        elif pl_pct > 8:
                            print(f"[{now}]   🎯 触发止盈! (盈利{pl_pct:.2f}% > 8%)")
                            success = trader.execute_trade(sym, 'SELL', shares, price, 'hk', force=True, skip_llm=True, reasons=[f'止盈触发：盈利{pl_pct:.2f}% > 8%'], entry_price_override=cost_price)
                            if success:
                                print(f"[{now}]   ✅ 止盈完成: {sym}")
                            else:
                                print(f"[{now}]   ❌ 止盈失败，将在24小时后重试")
                                trader.recently_closed[sym] = time.time()

                # 获取机会
                opportunities = trader.get_opportunities()
                
                # 美股交易
                if us_trading and us_account:
                    us_high = [o for o in opportunities['us'] if o.get('score', 0) >= trader.us_config.get('min_score', 80)]
                    us_positions = [p.get('symbol') for p in us_account.get('positions', [])]
                    
                    for o in us_high[:1]:
                        symbol = o.get('symbol', '')
                        futu_symbol = f"US.{symbol}"
                        should, reason = trader.should_trade(futu_symbol, us_account.get('positions', []), us_account.get('pending_orders', []))
                        if not should:
                            print(f"[{now}] ⏭️ {symbol}: {reason}")
                            continue
                        
                        price = o.get('price', 0)
                        score = o.get('score', 0)
                        order_plan = trader.prepare_buy_order(us_account, futu_symbol, price, score, market='us')
                        if not order_plan.get('can_buy'):
                            print(f"[{now}] ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                            continue
                        
                        quantity = order_plan['quantity']
                        print(
                            f"[{now}] 🎯 买入 {symbol} (评分{score}, ${price}, 数量{quantity}, "
                            f"金额${order_plan['order_value']:,.2f}, 总仓位{order_plan['after_total_pct']:.1f}%)"
                        )
                        success = trader.execute_trade(futu_symbol, 'BUY', quantity, price, 'us', score=score, reasons=o.get('reasons', []))
                        if success:
                            us_positions.append(futu_symbol)
                            us_account['positions'].append({'symbol': futu_symbol, 'shares': quantity, 'market_val': order_plan['order_value']})
                            us_account['market_val'] = us_account['total_assets'] * order_plan['after_total_pct'] / 100
                            us_account['cash'] = max(0, us_account.get('cash', 0) - order_plan['order_value'])
                
                # 港股交易
                if hk_trading and hk_account:
                    hk_high = [o for o in opportunities['hk'] if o.get('base_score', 0) >= trader.hk_config.get('min_score', 70)]
                    hk_positions = [p.get('symbol') for p in hk_account.get('positions', [])]
                    
                    print(f"[{now}] 🇭🇰 港股高评分: {len(hk_high)}只, 持仓: {len(hk_positions)}只")
                    
                    for o in hk_high[:1]:
                        symbol = o.get('symbol', '')
                        print(f"[{now}] 🔍 检查 {symbol}")
                        should, reason = trader.should_trade(symbol, hk_account.get('positions', []), hk_account.get('pending_orders', []))
                        if not should:
                            print(f"[{now}] ⏭️ {symbol}: {reason}")
                            continue
                        
                        price = o.get('price', 0)
                        score = o.get('base_score', 0)
                        
                        print(f"[{now}] 💰 {symbol} 价格: {price}, 评分: {score}")
                        
                        lot_size = trader._get_hk_lot_size(symbol)
                        order_plan = trader.prepare_buy_order(hk_account, symbol, price, score, market='hk', lot_size=lot_size)
                        if not order_plan.get('can_buy'):
                            print(f"[{now}] ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                            continue
                        
                        quantity = order_plan['quantity']
                        print(
                            f"[{now}] 📊 仓位计算: 目标${order_plan['target_value']:,.2f}, "
                            f"允许${order_plan['allowed_value']:,.2f}, 原始{order_plan['raw_quantity']}股 "
                            f"-> {quantity}股(每手{lot_size})"
                        )
                        print(f"[{now}] 🎯 买入 {symbol} (评分{score}, 价格{price}, 数量{quantity})")
                        success = trader.execute_trade(symbol, 'BUY', quantity, price, 'hk', score=score, reasons=o.get('reasons', []))
                        if success:
                            hk_positions.append(symbol)
                            hk_account['positions'].append({'symbol': symbol, 'shares': quantity, 'market_val': order_plan['order_value']})
                            hk_account['market_val'] = hk_account['total_assets'] * order_plan['after_total_pct'] / 100
                            hk_account['cash'] = max(0, hk_account.get('cash', 0) - order_plan['order_value'])
                            print(f"[{now}] ✅ 买入成功: {symbol}")
                        else:
                            print(f"[{now}] ❌ 买入失败: {symbol}")
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n🛑 守护进程停止")
                break
            except Exception as e:
                print(f"⚠️ 错误: {e}")
                time.sleep(1)
    else:
        # 单次运行
        trader = AutoTrader()
        try:
            trader.run()
        finally:
            for ctx in (getattr(trader, 'quote_ctx', None), getattr(trader, 'trade_ctx', None), getattr(trader, 'hk_trade_ctx', None)):
                try:
                    if ctx:
                        ctx.close()
                except Exception:
                    pass
