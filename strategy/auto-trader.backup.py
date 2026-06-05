import time
#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
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
import json
import requests
from datetime import datetime, time as dt_time

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext, OpenUSTradeContext, OpenHKTradeContext, RET_OK, OrderType, TrdSide, TrdEnv

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
        self.get_open_positions()_file = '/home/admin/.openclaw/workspace-stock/data/open-positions.json'
    
    def save_open_position(self, symbol, shares, entry_price, market='us', score=0, reasons=None, entry_snapshot=None, entry_llm_raw=None):
        """保存入场记录
        
        Args:
            symbol: 标的代码
            shares: 持仓数量
            entry_price: 开仓价格
            market: 市场（us/hk）
            score: 开仓评分
            reasons: 开仓原因列表（技术信号、新闻等）
            entry_snapshot: 开仓时技术指标快照（新增）
            entry_llm_raw: 开仓时LLM分析原始数据（新增）
        """
        try:
            positions = []
            try:
                with open(self.get_open_positions()_file, 'r') as f:
                    positions = json.load(f)
            except:
                positions = []
            
            # 检查是否已存在
            positions = [p for p in positions if p.get('symbol') != symbol]
            
            # 计算目标价
            target_stop_loss = entry_price * 0.94  # 固定6%止损
            target_take_profit = entry_price * 1.08  # 保守8%止盈，后续可改为ATR动态值
            
            positions.append({
                'symbol': symbol,
                'shares': shares,
                'entry_price': entry_price,
                'target_stop_loss': round(target_stop_loss, 2),
                'target_take_profit': round(target_take_profit, 2),
                'entry_time': datetime.now().isoformat(),
                'market': market,
                'entry_score': score,
                'entry_reasons': reasons or [],
                'entry_snapshot': entry_snapshot or {},
                'entry_llm_raw': entry_llm_raw or {},
                'peak_pnl_pct': 0.0,  # 峰值浮盈
                'peak_time': datetime.now().isoformat()
            })
            
            with open(self.get_open_positions()_file, 'w') as f:
                import fcntl
            with open(self.get_open_positions()_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                json.dump(positions, f, ensure_ascii=False, indent=2)
            print(f"   💾 已记录入场: {symbol} @ ${entry_price} (评分{score})")
        except Exception as e:
            print(f"   ⚠️ 记录入场失败: {e}")
    
    def update_peak_profit(self, symbol, current_pnl_pct):
        """更新持仓峰值浮盈"""
        try:
            try:
                with open(self.get_open_positions()_file, 'r') as f:
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
                with open(self.get_open_positions()_file, 'w') as f:
                    json.dump(positions, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def get_llm_trade_attribution(self, symbol, entry_record, exit_price, pnl_pct):
        """LLM买入决策归因分析（止损时调用）
        Args:
            symbol: 标的代码
            entry_record: 开仓时的完整记录（含快照和LLM原始数据）
            exit_price: 平仓价格
            pnl_pct: 实际盈亏比例（百分比）
        Returns:
            dict: 归因结果
        """
        try:
            from llm_stock_analyzer import get_llm_client
            client = get_llm_client()
            if not client.api_key:
                return None
            
            prompt = f"""
            你是专业的交易复盘分析师，请对下面的亏损交易做买入决策归因分析，找出亏损的根因和改进建议。
            
            【交易基本信息】
            标的：{symbol}
            买入价格：${entry_record['entry_price']:.2f}
            卖出价格：${exit_price:.2f}
            实际盈亏：{pnl_pct:.2f}%
            买入时间：{entry_record['entry_time']}
            开仓评分：{entry_record['entry_score']}分
            开仓理由：{','.join(entry_record['entry_reasons'])}
            
            【开仓时技术指标快照】
            {json.dumps(entry_record.get('entry_snapshot', {}), ensure_ascii=False, indent=2)}
            
            请按以下格式输出，不要有多余内容：
            📝 【买入决策反思】
            1. **错误根因**：（明确说明是技术信号失效/消息面假阳性/大盘系统性下跌/行业黑天鹅/评分误判/风控漏洞），要具体
            2. **当时买入信号瑕疵**：（说明开仓时哪些信号不满足要求，或者判断错误）
            3. **改进建议**：给出可落地的具体优化方向，不要空泛
            """
            
            result = client.call(prompt, max_tokens=400, temperature=0.3)
            if result:
                return {'content': result, 'time': datetime.now().isoformat()}
            return None
        except Exception as e:
            print(f"❌ LLM归因失败: {e}")
            return None
        try:
            try:
                with open(self.get_open_positions()_file, 'r') as f:
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
                with open(self.get_open_positions()_file, 'w') as f:
                    json.dump(positions, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def remove_open_position(self, symbol):
        """移除入场记录"""
        try:
            try:
                with open(self.get_open_positions()_file, 'r') as f:
                    positions = json.load(f)
            except:
                return None
            
            # 找到并移除
            result = None
            positions = [p for p in positions if p.get('symbol') != symbol]
            
            with open(self.get_open_positions()_file, 'w') as f:
                json.dump(positions, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def get_open_position(self, symbol):
        """获取入场记录"""
        try:
            with open(self.get_open_positions()_file, 'r') as f:
                positions = json.load(f)
            for p in positions:
                if p.get('symbol') == symbol:
                    return p
            return None
        except:
            return None
    
    def save_closed_trade(self, symbol, side, shares, entry_price, exit_price, pnl_pct, reason, market='us', stop_type=None, entry_score=0, llm_attribution=None):
        """保存平仓记录
        
        Args:
            symbol: 标的代码
            side: 买卖方向
            shares: 数量
            entry_price: 开仓价（从Futu持仓获取）
            exit_price: 平仓价
            pnl_pct: 盈亏比例
            reason: 平仓原因
            llm_attribution: LLM买入决策归因结果（新增）
            market: 市场
            stop_type: 止损类型
            entry_score: 开仓评分
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
        self.us_config = {'min_score': 80, 'position_size': 0.12, 'max_positions': 999}
        self.hk_config = {'min_score': 70, 'position_size': 0.03, 'max_positions': 999}
        self.cooldown_seconds = 60
        self.recently_closed = {}  # {symbol: timestamp} 记录最近平仓的标的，防止重复平仓
        self.peak_profits = {}  # {symbol: peak_pnl_pct} 记录每只股票的峰值浮盈
        self.partial_stop_status = {}  # {symbol: {first_step_time, remaining_shares, original_shares, trigger_reason}} 分级减仓状态
        
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
            # 美股交易上下文
            self.trade_ctx = OpenUSTradeContext('127.0.0.1', 11111)
            
            # 港股交易上下文
            self.hk_trade_ctx = OpenHKTradeContext('127.0.0.1', 11111)
            
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
    
    def _get_hk_lot_size(self, symbol):
        """获取港股每手股数 - 优先从Futu API动态获取"""
        # 先尝试从Futu API获取
        try:
            if self.quote_ctx:
                ret, data = self.quote_ctx.get_market_snapshot([symbol])
                if ret == RET_OK and len(data) > 0:
                    lot_size = int(data.iloc[0].get('lot_size', 0))
                    if lot_size > 0:
                        return lot_size
        except:
            pass
        
        # 常见港股每手股数映射（备用）
        lot_sizes = {
            'HK.00005': 400,   # 汇丰控股
            'HK.00012': 1000,  # 恒基地产
            'HK.00016': 1000,  # 新鸿基地产
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
        return lot_sizes.get(symbol, 100)  # 默认100股
    
    def check_trading_hours(self, market='us'):
        """检查是否在交易时间（包含盘前+盘中+盘后）"""
        now = datetime.now().time()
        
        if market == 'us':
            # 美股交易时段：盘中(21:00-04:00) + 盘后(04:00-08:00)
            # 盘中: 21:00 - 次日04:00
            market_start = dt_time(21, 0)
            market_end = dt_time(4, 0)
            # 盘后: 04:00 - 08:00
            after_hours_start = dt_time(4, 0)
            after_hours_end = dt_time(8, 0)
            
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
            
            print(f"  💰 {market.upper()}账户: 总资产=${total_assets:,.2f}, 现金=${total_cash:,.2f}")
            
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
                'positions': positions,
                'pending_orders': pending_orders
            }
        except Exception as e:
            print(f"❌ 获取{market.upper()}账户信息失败: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def get_opportunities(self):
        """获取交易机会"""
        opportunities = {'us': [], 'hk': []}
        
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/opportunities.json', 'r') as f:
                data = json.load(f)
            opportunities['us'] = data.get('opportunities', [])
        except:
            pass
        
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/hk-opportunities.json', 'r') as f:
                data = json.load(f)
            opportunities['hk'] = data.get('opportunities', [])
        except:
            pass
        
        return opportunities
    
    def should_trade(self, symbol, positions, pending_orders=None, score=0, current_price=0):
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
        full_sym = symbol
        
        # ===== 新增：平仓冷却规则检查 =====
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/closed-trades.json', 'r') as f:
                closed_trades = json.load(f)
            from datetime import datetime, timedelta
            now = datetime.now()
            # 找最近24小时内该标的的平仓记录
            recent_closed = [
                t for t in closed_trades 
                if normalize(t.get('symbol', '')) == sym 
                and datetime.fromisoformat(t.get('close_time', now.isoformat())) > now - timedelta(hours=24)
            ]
            if recent_closed:
                # 取最近一笔平仓记录
                last_trade = recent_closed[-1]
                last_close_price = last_trade.get('exit_price', 0)
                last_close_time = last_trade.get('close_time', '')
                
                # 规则3：95分以上例外，仅推送告警不自动开仓
                if score >= 95:
                    # 使用新模板发送告警
                    from feishu_pusher import FeishuPusher
                    pusher = FeishuPusher()
                    message = f"⚠️ 平仓冷却期告警：{full_sym} 评分{score}分达到例外阈值，24小时内曾平仓，需人工确认是否开仓\n最近平仓时间: {last_close_time[:16]}，平仓价: ${last_close_price:.2f}，当前价: ${current_price:.2f}"
                    pusher.send_message(message)
                    return False, f"冷却期内，评分{score}分达到例外阈值，待人工确认"
                
                # 规则2：价差过滤：当前价比平仓价低不足2%，禁止开仓
                if current_price > 0 and last_close_price > 0:
                    price_diff_pct = (last_close_price - current_price) / last_close_price * 100
                    if price_diff_pct < 2:
                        return False, f"冷却期内，当前价较平仓价下跌仅{price_diff_pct:.1f}%，不足2%，禁止开仓"
                
                # 规则1：24小时冷却期，禁止开仓
                return False, f"冷却期内，24小时内曾平仓，禁止开仓"
        except Exception as e:
            print(f"⚠️ 冷却规则检查异常: {e}")
        
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
    
    def execute_trade(self, symbol, side, quantity, price, market='us', force=False, skip_llm=False, score=0, reasons=None, opportunity=None):
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
                from feishu_pusher import FeishuPusher
                pusher = FeishuPusher()
                pusher.send_message(f"❌ 无法连接Futu，下单失败\n\n标的: {symbol}")
                return False
        
        # 下单前检查持仓和订单（避免重复购买/下单）
        check_ret, check_data = self.trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE)
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
                ret, orders = self.trade_ctx.order_list_query(trd_env=TrdEnv.SIMULATE)
                if ret == RET_OK and orders is not None:
                    pending = orders[orders['order_status'] != 'FILLED_ALL']
                    pending_symbols = [o.code.replace('US.', '').replace('HK.', '') for o in pending.itertuples()]
                    if trade_sym in pending_symbols:
                        print(f"⚠️ {symbol} 有未完成订单，取消下单")
                        return False
        
        # 下单
        success, result = self.place_order(symbol, side, quantity, market)
        
        if success:
            # 入场记录（买入时）
            if side == 'BUY':
                # 获取技术指标快照
                tech_snapshot = {}
                try:
                    if market == 'us':
                        from technical_indicators_us import USTechIndicators
                        tech_ind = USTechIndicators()
                        tech_snapshot = tech_ind.get_all_indicators(symbol)
                    elif market == 'hk':
                        from technical_indicators_hk import HKTechIndicators
                        tech_ind = HKTechIndicators()
                        tech_snapshot = tech_ind.get_all_indicators(symbol)
                except Exception as e:
                    print(f"⚠️ 技术指标快照获取失败: {e}")
                
                # 获取LLM原始数据
                llm_raw_data = {}
                try:
                    if not skip_llm:
                        llm_analysis = self.llm_analysis_before_trade(symbol, price, market)
                        if llm_analysis:
                            llm_raw_data = llm_analysis
                except Exception as e:
                    print(f"⚠️ LLM原始数据获取失败: {e}")
                
                self.save_open_position(symbol, quantity, price, market, score=score, reasons=reasons, entry_snapshot=tech_snapshot, entry_llm_raw=llm_raw_data)
                # 计算目标价
                target_take_profit = round(price * 1.08, 2)
                target_stop_loss = round(price * 0.94, 2)
                # 格式化买入逻辑
                buy_logic = "\n".join([f"  - {r}" for r in reasons[:3]]) if reasons else "  - 暂无"
                
                # 从机会数据读取真实四源分项评分
                opp = opportunity  # 优先使用调用方传入的机会数据
                if not opp:
                    try:
                        opportunities_data = self.get_opportunities().get(market, [])
                        for item in opportunities_data:
                            if item.get('symbol', '').replace('US.', '').replace('HK.', '') == symbol.replace('US.', '').replace('HK.', ''):
                                opp = item
                                break
                    except:
                        pass
                
                score_total = score
                
                # 从本地数据库查询真实四源评分
                clean_sym = symbol.replace('US.', '').replace('HK.', '')
                score_news = 0       # 国际资讯 (0-30)
                score_announce = 0   # 官方公告 (0-20)
                score_community = 0  # 社区情绪 (0-25)
                score_institution = 0 # 机构观点 (0-25)
                try:
                    import sqlite3
                    db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
                    conn = sqlite3.connect(db_path)
                    
                    # 国际资讯: Yahoo Finance, Finnhub, Google News
                    c = conn.execute('''
                        SELECT ROUND(AVG(n.sentiment),2), COUNT(*)
                        FROM news n
                        WHERE (n.symbol = ? OR n.title LIKE ?)
                        AND n.source IN ("Yahoo Finance", "Finnhub", "Google News Tech")
                        AND n.timestamp > datetime("now", "-24 hours")
                    ''', (clean_sym, f'%{clean_sym}%'))
                    row = c.fetchone()
                    if row and row[1] > 0:
                        score_news = min(30, max(0, int((row[0] - 0.2) * 60)))
                    
                    # 官方公告: SEC EDGAR, Tushare-公告, 港交所
                    c = conn.execute('''
                        SELECT ROUND(AVG(n.sentiment),2), COUNT(*)
                        FROM news n
                        WHERE (n.symbol = ? OR n.title LIKE ?)
                        AND n.source IN ("SEC EDGAR", "Tushare-公告", "港交所")
                        AND n.timestamp > datetime("now", "-72 hours")
                    ''', (clean_sym, f'%{clean_sym}%'))
                    row = c.fetchone()
                    if row and row[1] > 0:
                        score_announce = min(20, max(0, int((row[0] - 0.3) * 40)))
                    
                    # 社区情绪: 新浪财经, 东方财富, 观察者网
                    c = conn.execute('''
                        SELECT ROUND(AVG(n.sentiment),2), COUNT(*)
                        FROM news n
                        WHERE (n.symbol = ? OR n.title LIKE ?)
                        AND n.source IN ("新浪财经", "东方财富", "观察者网")
                        AND n.timestamp > datetime("now", "-24 hours")
                    ''', (clean_sym, f'%{clean_sym}%'))
                    row = c.fetchone()
                    if row and row[1] > 0:
                        score_community = min(25, max(0, int((row[0] - 0.3) * 50)))
                    
                    # 机构观点: 含评级/上调/下调关键词的新闻
                    c = conn.execute('''
                        SELECT ROUND(AVG(n.sentiment),2), COUNT(*)
                        FROM news n
                        WHERE (n.symbol = ? OR n.title LIKE ?)
                        AND (n.title LIKE "%analyst%" OR n.title LIKE "%upgrade%" OR n.title LIKE "%downgrade%"
                             OR n.title LIKE "%rating%" OR n.title LIKE "%target%" OR n.title LIKE "%评级%"
                             OR n.title LIKE "%上调%" OR n.title LIKE "%下调%")
                        AND n.timestamp > datetime("now", "-72 hours")
                    ''', (clean_sym, f'%{clean_sym}%'))
                    row = c.fetchone()
                    if row and row[1] > 0:
                        score_institution = min(25, max(0, int((row[0] - 0.3) * 50)))
                    
                    conn.close()
                except:
                    pass
                
                # 读取真实LLM分析结论
                signal_type = opp.get('signal_type', "多因子共振（技术面+基本面）") if opp else "多因子共振（技术面+基本面）"
                llm_conclusion = opp.get('llm_reason', f"当前信号综合评分{score_total}分，技术面满足所有入场条件，基本面无明显利空，信号可靠性较高；关注大盘整体波动风险") if opp else f"当前信号综合评分{score_total}分，技术面满足所有入场条件，基本面无明显利空，信号可靠性较高；关注大盘整体波动风险"
                
                message = f"""✅ 买入成功

标的: {symbol}
数量: {quantity}股
买入价: ~${price:.2f}
金额: ~${quantity * price:,.2f}
🎯 预测: 止盈价: ${target_take_profit} / 止损价: ${target_stop_loss}

📊 评分明细: 总分{score_total}
 国际资讯: {score_news}/30
 官方公告: {score_announce}/20
 社区情绪: {score_community}/25
 机构观点: {score_institution}/25

🔍 信号类型: {signal_type}
🤖 LLM验真: {llm_conclusion}

订单ID: {result}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            else:
                # 统一使用新模板 - 全部通过FeishuPusher
                if side == 'SELL':
                    # 获取成本价和计算盈亏
                    entry_price = 0
                    try:
                        with open('/home/admin/.openclaw/workspace-stock/data/open-positions.json', 'r') as f:
                            positions = json.load(f)
                        for pos in positions:
                            if pos.get('symbol') == symbol:
                                entry_price = pos.get('entry_price', 0)
                                break
                    except:
                        pass
                    
                    pl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                    amount = quantity * price
                    
                    # 调用FeishuPusher的卖出通知
                    from feishu_pusher import FeishuPusher
                    pusher = FeishuPusher()
                    success = pusher.send_sell_notification(
                        symbol=symbol,
                        quantity=quantity,
                        price=price,
                        amount=amount,
                        pnl_pct=pl_pct,
                        reason="自动平仓",
                        order_id=result,
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )
                    return success
                else:
                    # 开仓也使用新模板
                    amount = quantity * price
                    # 获取目标止盈止损价
                    target_stop_loss = price * 0.94
                    target_take_profit = price * 1.08
                    
                    # 调用FeishuPusher的买入通知
                    from feishu_pusher import FeishuPusher
                    pusher = FeishuPusher()
                    success = pusher.send_buy_notification(
                        symbol=symbol,
                        quantity=quantity,
                        price=price,
                        amount=amount,
                        target_take_profit=target_take_profit,
                        target_stop_loss=target_stop_loss,
                        score_total=0,
                        score_news=0,
                        score_announce=0,
                        score_community=0,
                        score_institution=0,
                        signal_type="自动交易",
                        llm_conclusion="系统自动执行",
                        order_id=result,
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )
                    return success
            
            # 发送通知
            self.send_notification(message)
        
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
    
    def get_score_based_position(self, score):
        """根据评分获取动态仓位
        
        评分 80-84分：仓位 8%-10%
        评分 85-89分：仓位 10%-11%
        评分 90-94分：仓位 11%-12%
        评分 ≥ 95分：仓位 12%
        单票上限不超过12%
        """
        if score >= 95:
            return 0.12
        elif score >= 90:
            return 0.11 + (score - 90) * 0.001  # 90-94分: 11%-12%
        elif score >= 85:
            return 0.10 + (score - 85) * 0.001  # 85-89分: 10%-11%
        elif score >= 80:
            return 0.08 + (score - 80) * 0.002  # 80-84分: 8%-10%
        else:
            return 0.05  # 80分以下保守
    
    def get_vix_multiplier(self):
        """根据VIX获取仓位系数
        
        VIX < 20：仓位正常执行 (1.0)
        VIX 20-25：所有仓位打8折 (0.8)
        VIX 25-30：所有仓位打6折 (0.6)，总仓位上限降到50%
        VIX > 30：暂停开仓 (0.0)
        """
        try:
            vix = self.get_vix_realtime()
            if vix > 30:
                return 0.0, 0.50, "VIX过高，暂停开仓"
            elif vix >= 25:
                return 0.6, 0.50, "VIX恐慌，仓位6折，总仓位上限50%"
            elif vix >= 20:
                return 0.8, 0.40, "VIX警戒，仓位8折"
            else:
                return 1.0, 0.40, "VIX平静，正常仓位"
        except Exception as e:
            print(f"⚠️ 获取VIX失败: {e}")
            return 1.0, 0.40, "VIX获取失败，默认正常"
    
    def get_vix_realtime(self):
        """获取实时VIX数据"""
        try:
            import requests
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get('chart', {}).get('result', [])
                if result:
                    meta = result[0].get('meta', {})
                    price = meta.get('regularMarketPrice', 20)
                    if price and price > 0:
                        return float(price)
        except Exception as e:
            print(f"⚠️ 获取VIX失败: {e}")
        return 20.0  # 默认返回中性值
    
    def check_technical_stabilization(self, symbol, current_price, market='us'):
        """检查技术面是否企稳
        
        判断标准：
        1. MACD柱状图连续3个周期缩短
        2. RSI从超卖区(<30)反弹到35以上
        3. 价格在MA10上方或接近MA10
        
        Returns: True (企稳) / False (未企稳)
        """
        if not TECH_INDICATORS_AVAILABLE:
            return False
        
        try:
            if market == 'us':
                tech = USTechIndicators(symbol)
            else:
                tech = HKTechIndicators(symbol)
            
            indicators = tech.get_all_indicators()
            
            if not indicators:
                return False
            
            # 1. MACD柱状图缩短趋势
            macd_histogram = indicators.get('macd_histogram', [])
            if len(macd_histogram) >= 4:
                # 检查最近3个周期是否缩短
                shrinking = all(macd_histogram[i] > macd_histogram[i+1] for i in range(3))
                if not shrinking:
                    return False
            
            # 2. RSI从超卖反弹
            rsi = indicators.get('rsi', 50)
            if rsi < 35:
                return False
            
            # 3. 价格与MA10关系
            ma10 = indicators.get('ma10', 0)
            if ma10 > 0:
                price_diff_pct = abs(current_price - ma10) / ma10 * 100
                if price_diff_pct > 2:  # 偏离MA10超过2%
                    return False
            
            # 所有条件满足，认为企稳
            return True
            
        except Exception as e:
            print(f"⚠️ 检查技术面企稳失败: {e}")
            return False
    
    def check_position_limits(self, total_assets, current_position_value, vix_multiplier=1.0, total_limit=0.40):
        """检查仓位限制（支持动态调整）"""
        # 计算当前仓位
        position_pct = current_position_value / total_assets if total_assets > 0 else 0
        
        # 单票12%上限
        single_limit_ok = position_pct <= 0.12
        
        # 总仓位上限（可动态调整）
        total_limit_ok = position_pct <= total_limit
        
        return {
            'single_position_ok': single_limit_ok,
            'total_position_ok': total_limit_ok,
            'current_pct': position_pct * 100,
            'can_add_position': total_limit_ok,
            'vix_multiplier': vix_multiplier,
            'total_limit': total_limit * 100
        }, ""
    
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
            print("❌ 无可用交易账户")
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
        positions_to_take_profit = []
        
        # 只检查美股持仓（港股目前没有持仓）
        account = us_account if us_account else {'positions': []}
        for pos in account['positions']:
            sym = pos.get('symbol', '')
            shares = pos.get('shares', 0)
            if shares <= 0:
                continue
            
            # pl_ratio是小数形式（如-0.0753表示-7.53%），转换为百分比
            pl_pct = float(pos.get('pl_ratio', 0)) * 100  # 转换为百分比：-0.0753 → -7.53%
            
            # 更新峰值浮盈
            try:
                try:
                    self.update_peak_profit(sym, pl_pct)
                except Exception as e:
                    print(f"   ⚠️ 更新峰值浮盈失败: {e}")
            except Exception as e:
                print(f"   ⚠️ 更新峰值浮盈失败: {e}")

            print(f"  {sym}: 盈亏 {pl_pct:+.2f}%")
            
            # 止损条件：亏损超过6% 或 ATR止损触发
            if pl_pct < -6:
                # 跳过刚平过的标的（防止重复平仓）
                if sym in self.recently_closed and time.time() - self.recently_closed[sym] < self.cooldown_seconds:
                    print(f"    ⏭️ {sym} 刚平过，跳过")
                    continue
                positions_to_close.append(sym)
                print(f"    ⚠️ 触发止损! (亏损{pl_pct:.2f}% > 6%)")
            
            # 止盈条件：盈利超过8% (ATR止盈4.0-4.5x的简化)
            elif pl_pct > 8:
                # 跳过刚平过的标的
                if sym in self.recently_closed and time.time() - self.recently_closed[sym] < self.cooldown_seconds:
                    print(f"    ⏭️ {sym} 刚平过，跳过")
                    continue
                positions_to_take_profit.append(sym)
                print(f"    🎯 触发止盈! (盈利{pl_pct:.2f}% > 8%)")
        
        # 执行止损
        print(f"  📋 止损列表: {positions_to_close}")
        if positions_to_close:
            for sym in positions_to_close:
                # 获取持仓的实际数量和价格
                pos_data = next((p for p in account['positions'] if p.get('symbol','').replace('US.','') == sym), None)
                if pos_data:
                    shares = int(pos_data.get('shares', 0))
                    market_val = pos_data.get('market_val', 0)
                    cost_price = pos_data.get('cost_price', 0)
                    price = market_val / shares if shares > 0 else 0
                    # 获取当前股票的盈亏比例
                    current_pl_pct = float(pos_data.get('pl_ratio', 0))
                    print(f"  执行止损: 卖出 {sym} {shares}股 @ ${price:.2f}")
                    # 先撤掉该标的的所有未完成订单
                    try:
                        ret, orders = self.trade_ctx.order_list_query(trd_env=TrdEnv.SIMULATE)
                        if ret == 0 and orders is not None:
                            pending = orders[orders['order_status'] != 'FILLED_ALL']
                            for o in pending.itertuples():
                                if sym in o.code:
                                    self.trade_ctx.cancel_order(str(o.order_id))
                                    print(f"  撤销挂单: {o.order_id} ({o.code})")
                    except Exception as e:
                        print(f"  撤单失败: {e}")
                    # 判断市场
                    if sym.startswith('HK.'):
                        market = 'hk'
                        full_sym = sym
                    else:
                        market = 'us'
                        full_sym = f"US.{sym}"
                    
                    # 止损交易跳过LLM分析，直接执行
                    success = self.execute_trade(full_sym, 'SELL', shares, price, market, force=True, skip_llm=True)
                    if success:
                        # 获取开仓记录做归因分析
                        entry_record = next((p for p in self.get_open_positions() if p.get('symbol') == full_sym), None)
                        llm_attr = None
                        attr_content = ""
                        if entry_record:
                            llm_attr = self.get_llm_trade_attribution(full_sym, entry_record, price, current_pl_pct*100)
                            if llm_attr:
                                attr_content = f"\n📝 【买入决策反思】\n{llm_attr['content']}"
                        # 保存平仓记录
                        self.save_closed_trade(full_sym, 'SELL', shares, cost_price, price, current_pl_pct, '止损', market, stop_type='max_loss_stop', llm_attribution=llm_attr)
                        # 统一使用新模板 - 调用FeishuPusher
                        from feishu_pusher import FeishuPusher
                        pusher = FeishuPusher()
                        
                        # 构建原因信息
                        reason_text = f"止损触发 - 浮亏{current_pl_pct*100:.2f}%"
                        if attr_content:
                            reason_text += f"\n{attr_content.replace('📝 【买入决策反思】', '📝 买入决策反思:')}"
{attr_content.replace(📝
                        
                        success = pusher.send_sell_notification(
                            symbol=full_sym,
                            quantity=shares,
                            price=price,
                            amount=shares * price,
                            pnl_pct=current_pl_pct * 100,
                            reason=reason_text,
                            order_id="auto-stop-loss",
                            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        )
                        # 移除入场记录
                        self.remove_open_position(full_sym)
                        self.recently_closed[sym] = time.time()
        
        # 执行止盈
        if positions_to_take_profit:
            for sym in positions_to_take_profit:
                pos_data = next((p for p in account['positions'] if p.get('symbol','').replace('US.','').replace('HK.','') == sym.replace('US.','').replace('HK.','')), None)
                if pos_data:
                    shares = int(pos_data.get('shares', 0))
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
                    
                    print(f"  执行止盈: 卖出 {sym} {shares}股 @ ${price:.2f}")
                    success = self.execute_trade(full_sym, 'SELL', shares, price, market, force=True, skip_llm=True)
                    if success:
                        # 止盈也附加简单分析
                        entry_record = next((p for p in self.get_open_positions() if p.get('symbol') == full_sym), None)
                        attr_content = ""
                        if entry_record:
                            try:
                                from llm_stock_analyzer import get_llm_client
                                client = get_llm_client()
                                if client.api_key:
                                    prompt = f"""标的{full_sym}盈利{current_pl_pct*100:.2f}%止盈，开仓评分{entry_record['entry_score']}分，开仓理由是{','.join(entry_record['entry_reasons'])}，请给出1条止盈优化建议，不超过30字。"""
                                    res = client.call(prompt, max_tokens=50, temperature=0.3)
                                    if res:
                                        attr_content = f"\n💡 优化建议：{res.strip()}"
                            except:
                                pass
                        # 统一使用新模板 - 调用FeishuPusher
                        from feishu_pusher import FeishuPusher
                        pusher = FeishuPusher()
                        
                        # 构建原因信息
                        reason_text = f"止盈触发 - 盈利{current_pl_pct*100:.2f}%"
                        if attr_content:
                            reason_text += f"\n{attr_content.replace('💡 优化建议：', '💡 优化建议:')}")
                        
                        success = pusher.send_sell_notification(
                            symbol=full_sym,
                            quantity=shares,
                            price=price,
                            amount=shares * price,
                            pnl_pct=current_pl_pct * 100,
                            reason=reason_text,
                            order_id="auto-take-profit",
                            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        )
                        # 保存平仓记录（使用 Futu 的成本价）
                        self.save_closed_trade(full_sym, 'SELL', shares, cost_price, price, current_pl_pct, '止盈', market, stop_type='take_profit')
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
                should, reason = self.should_trade(futu_symbol, us_account['positions'], us_account.get('pending_orders', []), score=score, current_price=price)
                
                if not should:
                    print(f"  ⏭️ {symbol}: {reason}")
                    continue
                
                # ===== v1.6 技术指标检查 =====
                # 检查技术信号（美股: MA趋势、RSI、成交量、MACD）
                tech_signals = self.check_technical_signals(symbol, market='us')
                
                if not tech_signals.get('can_enter', False):
                    print(f"  ⏭️ {symbol}: 技术指标不满足入场条件")
                    for r in tech_signals.get('reasons', []):
                        print(f"      {r}")
                    continue  # 跳过不满足技术条件的股票
                
                # 检查VIX市场环境
                vix_multiplier, total_limit, vix_msg = self.get_vix_multiplier()
                if vix_multiplier == 0.0:
                    print(f"  ⏭️ {symbol}: {vix_msg}")
                    continue
                print(f"  📊 VIX环境: {vix_msg}")
                
                # 检查仓位限制（支持动态调整）
                current_position_value = us_account.get('market_val', 0)
                position_check, _ = self.check_position_limits(us_account['total_assets'], current_position_value, vix_multiplier, total_limit)
                
                if not position_check.get('can_add_position', False):
                    print(f"  ⏭️ {symbol}: 仓位已满 ({position_check.get('current_pct', 0):.1f}% / {position_check.get('total_limit', 40):.1f}%)")
                    continue
                
                # 根据评分获取动态仓位
                base_position_pct = self.get_score_based_position(score)
                
                # 应用VIX系数
                final_position_pct = base_position_pct * vix_multiplier
                
                # 单票上限12%
                final_position_pct = min(final_position_pct, 0.12)
                
                # 计算仓位
                position_size = us_account['total_assets'] * final_position_pct
                quantity = int(position_size / price) if price > 0 else 0
                
                print(f"  💰 {symbol}: 评分{score}分 → 基础仓位{base_position_pct*100:.1f}% → VIX调整{final_position_pct*100:.1f}% → 数量{quantity}股")
                
                if quantity > 0:
                    # 构建开仓原因列表
                    entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                    success = self.execute_trade(futu_symbol, 'BUY', quantity, price, 'us', score=score, reasons=entry_reasons, opportunity=o)
                    if success:
                        # 更新持仓计数
                        us_account['positions'].append({'symbol': futu_symbol})
                        if len(us_account['positions']) >= self.config['max_positions']:
                            break
        
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
                    
                    position_size = hk_account['total_assets'] * self.hk_config.get('position_size', 0.03)
                    raw_quantity = int(position_size / price) if price > 0 else 0
                    lot_size = self._get_hk_lot_size(symbol)
                    quantity = (raw_quantity // lot_size) * lot_size  # 整手交易
                    
                    if quantity > 0:
                        print(f"  💰 {symbol}: 价格{price}, 原始数量{raw_quantity}, 整手数量{quantity}(每手{lot_size})")
                        # 构建开仓原因列表
                        entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                        success = self.execute_trade(symbol, 'BUY', quantity, price, 'hk', score=score, reasons=entry_reasons, opportunity=o)
                        if success:
                            hk_account['positions'].append({'symbol': symbol})
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
    
    def send_notification(self, message, force_path=False):
        """发送通知到飞书 - 使用新的FeishuPusher"""
        try:
            from feishu_pusher import FeishuPusher
            pusher = FeishuPusher()
            success = pusher.send_message(message)
            if success:
                print("✅ 通知已发送到飞书")
            else:
                print("⚠️ 飞书发送失败")
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
                
                # 非交易时间：检查高置信度机会并发送通知
                if not us_trading and not hk_trading:
                    try:
                        # 读取已分析的机会数据
                        opportunities_file = '/home/admin/.openclaw/workspace-stock/data/opportunities.json'
                        if os.path.exists(opportunities_file):
                            with open(opportunities_file, 'r') as f:
                                opps_data = json.load(f)
                            
                            # 筛选高置信度机会（final_score >= 90）
                            high_confidence = []
                            for opp in opps_data.get('opportunities', []):
                                final_score = opp.get('final_score', opp.get('score', 0))
                                if final_score >= 90:
                                    high_confidence.append(opp)
                            
                            if high_confidence:
                                # 发送非交易时间机会通知
                                from feishu_pusher import FeishuPusher
                                pusher = FeishuPusher()
                                
                                # 判断当前市场状态
                                current_time = datetime.now().time()
                                market_status = "盘后"
                                if current_time >= dt_time(8, 0) and current_time < dt_time(21, 0):
                                    market_status = "夜盘"
                                
                                top_opp = high_confidence[0]
                                symbol = top_opp.get('symbol', 'Unknown')
                                score = top_opp.get('final_score', top_opp.get('score', 0))
                                signal_type = top_opp.get('signal_type', '多因子共振（技术面+基本面）')
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                # 提取评分明细（从本地数据库查询真实新闻情绪）
                                score_total = score
                                score_news = 0  # 新闻情绪分(0-30)
                                try:
                                    import sqlite3
                                    db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
                                    conn = sqlite3.connect(db_path)
                                    clean_sym = symbol.replace('US.', '').replace('HK.', '')
                                    c = conn.execute('''
                                        SELECT ROUND(AVG(n.sentiment),2), COUNT(*)
                                        FROM stock_mentions sm
                                        JOIN news n ON n.id = sm.news_id
                                        WHERE sm.symbol = ? AND n.timestamp > datetime('now', '-24 hours')
                                    ''', (clean_sym,))
                                    row = c.fetchone()
                                    conn.close()
                                    if row and row[1] > 0:
                                        avg_sent = row[0]
                                        score_news = min(30, max(0, int((avg_sent - 0.2) * 60)))
                                except:
                                    score_news = min(int(score_total * 0.32), 30)
                                score_tech = max(0, score_total - score_news - 25)
                                
                                score_announce = top_opp.get('score_announce', 0)
                                score_community = top_opp.get('score_community', 0)
                                score_institution = top_opp.get('score_institution', 0)
                                llm_conclusion = top_opp.get('llm_reason', f'当前信号综合评分{score_total}分，技术面满足所有入场条件，基本面无明显利空，信号可靠性较高；关注大盘整体波动风险')
                                
                                pusher.send_opportunity_notification(
                                    symbol=symbol,
                                    score_total=score_total,
                                    score_news=score_news,
                                    score_tech=score_tech,
                                    signal_type=signal_type,
                                    llm_conclusion=llm_conclusion,
                                    market_status=market_status,
                                    timestamp=timestamp
                                )
                    except Exception as e:
                        print(f"[{now}] ⚠️ 非交易时间机会通知失败: {e}")
                    
                    time.sleep(60)  # 非交易时间降低检查频率
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
                            if age < 60:  # 60秒冷却期
                                print(f"[{now}]   {sym}: 冷却中({age:.0f}s)，跳过")
                                continue
                        
                        # 获取当前价格和浮亏
                        market_val = pos.get('market_val', 0)
                        price = market_val / shares if shares > 0 else 0
                        pl_pct = float(pos.get('pl_ratio', 0)) * 100
                        
                        # ===== 完整动态止损逻辑 (v1.6) =====
                        # 1. 首先检查ATR动态止损
                        atr_stop_price = trader.calculate_stop_loss(sym, market='us')
                        should_stop_loss = False
                        stop_reason = ""
                        
                        if atr_stop_price and price <= atr_stop_price:
                            should_stop_loss = True
                            stop_reason = f"ATR动态止损 (当前价${price:.2f} <= 止损价${atr_stop_price:.2f})"
                        # 2. 如果ATR止损未触发，检查保底6%止损
                        elif pl_pct < -6:
                            should_stop_loss = True
                            stop_reason = f"保底止损 (亏损{pl_pct:.2f}% > 6%)"
                        
                        print(f"[{now}]   {sym}: 盈亏 {pl_pct:+.2f}%, ATR止损价: ${atr_stop_price:.2f} if atr_stop_price else 'N/A'")
                        
                        if should_stop_loss:
                            # 检查是否在失败冷却期（避免频繁重试）
                            if sym in trader.recently_closed:
                                age = time.time() - trader.recently_closed[sym]
                                if age < 120:  # 失败后等待120秒再重试
                                    print(f"[{now}]   {sym}: 止损失败冷却中({age:.0f}s)，跳过")
                                    continue
                            
                            print(f"[{now}]   ⚠️ 触发止损! {stop_reason}")
                            success = trader.execute_trade(sym, 'SELL', shares, price, 'us', force=True, skip_llm=True)
                            if success:
                                print(f"[{now}]   ✅ 止损完成: {sym}")
                                trader.recently_closed[sym] = time.time()  # 成功后记录，防止重复平仓
                            else:
                                print(f"[{now}]   ❌ 止损失败，120秒后重试")
                                trader.recently_closed[sym] = time.time()  # 失败后进入长冷却期
                        # 止盈：盈利超过8%
                        elif pl_pct > 8:
                            print(f"[{now}]   🎯 触发止盈! (盈利{pl_pct:.2f}% > 8%)")
                            success = trader.execute_trade(sym, 'SELL', shares, price, 'us', force=True, skip_llm=True)
                            if success:
                                print(f"[{now}]   ✅ 止盈完成: {sym}")
                            else:
                                print(f"[{now}]   ❌ 止盈失败，将在60秒后重试")
                                trader.recently_closed[sym] = time.time()
                
                # ===== 检查分级减仓第二步 =====
                if trader.partial_stop_status:
                    now_time = time.time()
                    to_remove = []
                    
                    for sym, status in trader.partial_stop_status.items():
                        if now_time - status['first_step_time'] >= 1800:  # 30分钟后检查
                            print(f"[{now}]   🔍 检查分级减仓第二步: {sym}")
                            
                            # 获取当前价格
                            quote, err = trader.quote_ctx.get_market_quote([sym])
                            if err != 0 or not quote:
                                print(f"[{now}]   ❌ 获取报价失败，全平剩余")
                                remaining_shares = status['remaining_shares']
                                success = trader.execute_trade(sym, 'SELL', remaining_shares, price, 'us', force=True, skip_llm=True)
                                if success:
                                    to_remove.append(sym)
                                continue
                            
                            current_price = quote[0]['last_price']
                            
                            # 检查技术面是否企稳
                            is_stabilized = trader.check_technical_stabilization(sym, current_price, 'us')
                            
                            if not is_stabilized:
                                # 价格继续下跌+MACD未企稳 → 全平剩余
                                print(f"[{now}]   📉 技术面未企稳，全平剩余{status['remaining_shares']}股")
                                success = trader.execute_trade(sym, 'SELL', status['remaining_shares'], current_price, 'us', force=True, skip_llm=True)
                                if success:
                                    to_remove.append(sym)
                                    trader.recently_closed[sym] = time.time()
                            else:
                                # 技术面企稳 → 保留剩余仓位，收紧止损线
                                print(f"[{now}]   🟢 技术面企稳，保留{status['remaining_shares']}股，收紧止损线")
                                
                                # 收紧止损线到1.2倍ATR
                                new_stop_loss = trader.calculate_stop_loss(sym, multiplier=1.2, market='us')
                                if new_stop_loss:
                                    print(f"[{now}]   🛡️ 新止损线: ${new_stop_loss:.2f}")
                                    
                                    # 更新持仓止损线
                                    for pos in trader.positions:
                                        if pos['symbol'] == sym:
                                            pos['target_stop_loss'] = new_stop_loss
                                            break
                                
                                to_remove.append(sym)  # 移除分级减仓状态，但保留持仓
                    
                    # 清理已处理的记录
                    for sym in to_remove:
                        if sym in trader.partial_stop_status:
                            del trader.partial_stop_status[sym]
                
                # 获取机会
                opportunities = trader.get_opportunities()
                
                # 美股交易
                if us_trading and us_account:
                    us_high = [o for o in opportunities['us'] if o.get('score', 0) >= trader.us_config.get('min_score', 80)]
                    us_positions = [p.get('symbol') for p in us_account.get('positions', [])]
                    
                    for o in us_high[:1]:
                        symbol = o.get('symbol', '')
                        if f"US.{symbol}" in us_positions:
                            continue
                        
                        price = o.get('price', 0)
                        score = o.get('score', 0)
                        
                        position_value = us_account['total_assets'] * trader.us_config.get('position_size', 0.12)
                        quantity = int(position_value / price) if price > 0 else 0
                        
                        if quantity > 0:
                            print(f"[{now}] 🎯 买入 {symbol} (评分{score}, ${price})")
                            success = trader.execute_trade(f"US.{symbol}", 'BUY', quantity, price, 'us', score=score, opportunity=o)
                            if success:
                                us_positions.append(f"US.{symbol}")
                
                # 港股交易
                if hk_trading and hk_account:
                    hk_high = [o for o in opportunities['hk'] if o.get('base_score', 0) >= trader.hk_config.get('min_score', 70)]
                    hk_positions = [p.get('symbol') for p in hk_account.get('positions', [])]
                    
                    print(f"[{now}] 🇭🇰 港股高评分: {len(hk_high)}只, 持仓: {len(hk_positions)}只")
                    
                    for o in hk_high[:1]:
                        symbol = o.get('symbol', '')
                        print(f"[{now}] 🔍 检查 {symbol}")
                        
                        if symbol in hk_positions:
                            print(f"[{now}] ⏭️ {symbol} 已在持仓中")
                            continue
                        
                        price = o.get('price', 0)
                        score = o.get('base_score', 0)
                        
                        print(f"[{now}] 💰 {symbol} 价格: {price}, 评分: {score}")
                        
                        if price <= 0:
                            print(f"[{now}] ❌ {symbol} 价格无效")
                            continue
                        
                        position_value = hk_account['total_assets'] * trader.hk_config.get('position_size', 0.03)
                        raw_quantity = int(position_value / price) if price > 0 else 0
                        
                        # 港股需要整手交易，根据股票代码获取每手股数
                        lot_size = trader._get_hk_lot_size(symbol)
                        quantity = (raw_quantity // lot_size) * lot_size  # 向下取整到整手
                        
                        print(f"[{now}] 📊 仓位计算: ${position_value:,.2f} / {price} = {raw_quantity}股 -> 调整为{quantity}股(每手{lot_size})")
                        
                        if quantity > 0:
                            print(f"[{now}] 🎯 买入 {symbol} (评分{score}, 价格{price}, 数量{quantity})")
                            success = trader.execute_trade(symbol, 'BUY', quantity, price, 'hk', score=score, opportunity=o)
                            if success:
                                hk_positions.append(symbol)
                                print(f"[{now}] ✅ 买入成功: {symbol}")
                            else:
                                print(f"[{now}] ❌ 买入失败: {symbol}")
                        else:
                            print(f"[{now}] ❌ 计算数量为零")
                
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
        trader.run()
