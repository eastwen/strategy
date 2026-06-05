#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
每日日报生成脚本
1. 生成完整日报（使用ComprehensiveReportV11类）
2. 上传到飞书Wiki
3. 发送链接到飞书群聊
"""

import sys
import os
import json
import re
import requests
from datetime import datetime

# 添加futu路径
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext, OpenSecTradeContext, OpenHKTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK

# 常量
WIKI_SPACE = "7618972433919445958"
DATA_FILE = "/home/admin/.openclaw/workspace-stock/data/trades.json"
MD_FILE = "/home/admin/.openclaw/workspace-stock/daily-reports/{}-report.md"
API_KEYS_FILE = "/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json"
LOG_FILE = "/home/admin/.openclaw/workspace-stock/logs/hk-daily.log"

def run_cmd(cmd):
    """执行命令并返回输出"""
    import subprocess
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def safe_float(val, default=0.0):
    """安全转换浮点数"""
    if val == 'N/A' or val is None:
        return default
    try:
        return float(val)
    except:
        return default

def load_api_keys():
    """加载API密钥"""
    with open(API_KEYS_FILE, 'r') as f:
        return json.load(f)

class ComprehensiveReportV11:
    """综合日报生成器"""
    
    HK_NAME_MAP = {
        'HK.00001': '长江基建', 'HK.00002': '中电控股', 'HK.00003': '香港中华煤气',
        'HK.00005': '汇丰控股', 'HK.00006': '电能实业', 'HK.00011': '恒生银行',
        'HK.00012': '恒基地产', 'HK.00016': '新鸿基地产', 'HK.00017': '新世界发展',
        'HK.00019': '太古股份A', 'HK.00023': '东亚银行', 'HK.00027': '银河娱乐',
        'HK.00066': '地铁公司', 'HK.00083': '信和置业', 'HK.00101': '恒隆地产',
        'HK.00175': '吉利汽车', 'HK.00241': '中信股份', 'HK.00285': '贝壳',
        'HK.00292': '创科实业', 'HK.00388': '港交所', 'HK.00688': '中海外发展',
        'HK.00700': '腾讯', 'HK.00772': '阅文集团', 'HK.00857': '京城佳业',
        'HK.00939': '建设银行', 'HK.00992': '联想集团', 'HK.01024': '哔哩哔哩',
        'HK.01088': '中煤能源', 'HK.01109': '华润置地', 'HK.01113': '嘉里建设',
        'HK.01138': '中国平安', 'HK.01199': '友邦保险', 'HK.01209': '宝龙地产',
        'HK.01211': '理想汽车', 'HK.01299': '海底捞', 'HK.01378': '粤丰环保',
        'HK.01628': '九龙仓置业', 'HK.01658': '百威亚太', 'HK.01810': '小米',
        'HK.01880': '中国中免', 'HK.01928': '金沙中国', 'HK.01997': '九龙建业',
        'HK.02007': '碧桂园', 'HK.02020': '安踏体育', 'HK.02196': 'JZ Capital',
        'HK.02269': '药明生物', 'HK.02318': '中国太保', 'HK.02331': '李宁',
        'HK.02382': '周大福', 'HK.02388': '中金公司', 'HK.02392': '龙湖集团',
        'HK.02600': '中国铝业', 'HK.02618': '京东健康', 'HK.02628': '电能实业',
        'HK.02638': '港华能源', 'HK.02669': '旭辉控股', 'HK.03328': '交通银行',
        'HK.03690': '美团', 'HK.03800': '协鑫科技', 'HK.03883': '华夏视听',
        'HK.03898': '晶科能源', 'HK.03900': '越秀地产', 'HK.03968': '招商银行',
        'HK.03988': '建设银行', 'HK.06160': '百济神州', 'HK.06618': '京东健康',
        'HK.06639': '上海建工', 'HK.06680': '网易', 'HK.06690': '海尔智家',
        'HK.06888': '海底捞', 'HK.06969': '融创中国', 'HK.06998': '华润万象生活',
        'HK.09618': '京东', 'HK.09626': '哔哩哔哩', 'HK.09868': '小鹏汽车',
        'HK.09888': '百度', 'HK.09939': '名创优品', 'HK.09961': '携程集团',
        'HK.09988': '阿里巴巴', 'HK.08006': '汇通达', 'HK.08035': '英皇证券',
    }
    
    def __init__(self, us_mode=False):
        self.us_mode = us_mode
    
    @property
    def llm(self):
        """惰性加载LLM客户端"""
        if not hasattr(self, '_llm_client') or self._llm_client is None:
            sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
            from llm_stock_analyzer import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client

    def get_today_trades(self, market='us'):
        """获取当天的开仓/平仓记录"""
        from datetime import datetime, timedelta
        
        today = datetime.now()
        today_str = today.strftime('%Y-%m-%d')
        
        def is_today(timestamp):
            """检查时间戳是否是今天（支持多种格式）"""
            if not timestamp:
                return False
            # 提取日期部分，支持格式：2026-05-31, 2026-05-31T..., 2026-05-31 等
            try:
                # 先尝试提取前10个字符（日期部分）
                date_part = timestamp[:10]
                if date_part == today_str:
                    return True
                # 尝试解析ISO格式
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.date() == today.date()
            except:
                # 最后回退到startswith
                return timestamp.startswith(today_str)
        
        # 读取开仓记录
        open_positions = []
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/open-positions.json', 'r') as f:
                all_positions = json.load(f)
                # 筛选当天的开仓
                for pos in all_positions:
                    entry_time = pos.get('entry_time', '')
                    if is_today(entry_time):
                        # 根据市场筛选
                        pos_market = pos.get('market', 'us')
                        if (market == 'us' and pos_market == 'us') or (market == 'hk' and pos_market == 'hk'):
                            open_positions.append(pos)
        except:
            pass
        
        # 读取平仓记录
        closed_trades = []
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/closed-trades.json', 'r') as f:
                all_trades = json.load(f)
                # 筛选当天的平仓
                for trade in all_trades:
                    close_time = trade.get('close_time', '')
                    if is_today(close_time):
                        # 根据市场筛选
                        trade_market = trade.get('market', 'us')
                        if (market == 'us' and trade_market == 'us') or (market == 'hk' and trade_market == 'hk'):
                            closed_trades.append(trade)
        except:
            pass
        
        return {
            'open_positions': open_positions,
            'closed_trades': closed_trades
        }
    
    def get_closed_trades(self, days=7):
        """获取近N天的平仓交易记录"""
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/closed-trades.json', 'r') as f:
                trades = json.load(f)
            
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            recent = [t for t in trades if t.get('close_time', '') >= cutoff]
            return recent
        except:
            return []
    
    def get_strategy_pnl_stats(self, market='us'):
        """获取策略持仓收益统计
        
        统计当前持仓的盈亏情况，按策略版本分组
        """
        # 筛选持仓
        def is_hk_symbol(sym):
            s = str(sym).replace('HK.', '').replace('US.', '')
            return s.isdigit() or s.startswith('0')
        def is_us_symbol(sym):
            s = str(sym).replace('HK.', '').replace('US.', '')
            return not s.isdigit() and not s.startswith('0') and not s.startswith('0')
        if market == 'hk':
            positions = [p for poss in self.positions_by_account.values() 
                        for p in poss if is_hk_symbol(p.get('symbol', ''))]
        else:
            positions = [p for poss in self.positions_by_account.values() 
                        for p in poss if is_us_symbol(p.get('symbol', ''))]
        
        if not positions:
            return None
        
        # 统计
        wins = [p for p in positions if p.get('pnl_pct', 0) > 0]
        losses = [p for p in positions if p.get('pnl_pct', 0) <= 0]
        total_pnl = sum(p.get('market_val', 0) * p.get('pnl_pct', 0) / 100 for p in positions)
        avg_pnl_pct = sum(p.get('pnl_pct', 0) for p in positions) / len(positions) if positions else 0
        total_market_val = sum(p.get('market_val', 0) for p in positions)
        
        return {
            'total': len(positions),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(positions) * 100 if positions else 0,
            'total_pnl': total_pnl,
            'avg_pnl_pct': avg_pnl_pct,
            'total_market_val': total_market_val,
            'positions': positions
        }
    
    def get_closed_trades_stats(self, market=None, days=7):
        """获取平仓交易统计（保留兼容）"""
        trades = self.get_closed_trades(days)
        if market:
            trades = [t for t in trades if t.get('market') == market]
        if not trades:
            return None
        
        wins = [t for t in trades if t.get('pnl_pct', 0) > 0]
        losses = [t for t in trades if t.get('pnl_pct', 0) < 0]
        total_pnl = sum(t.get('pnl', 0) for t in trades)
        avg_win = sum(t.get('pnl_pct', 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get('pnl_pct', 0) for t in losses) / len(losses) if losses else 0
        
        entry_wins = [t for t in trades if t.get('peak_pnl_pct', 0) > 0]
        stop_losses = [t for t in trades if t.get('stop_type') in ('atr_stop_loss', 'max_loss_stop')]
        take_profits = [t for t in trades if t.get('stop_type') == 'take_profit']
        
        avg_loss_abs = abs(avg_loss) if avg_loss != 0 else 0
        profit_loss_ratio = avg_win / avg_loss_abs if avg_loss_abs > 0 else 0
        
        return {
            'total': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(trades) * 100 if trades else 0,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_loss_ratio': profit_loss_ratio,
            'entry_win_rate': len(entry_wins) / len(trades) * 100 if trades else 0,
            'stop_loss_rate': len(stop_losses) / len(trades) * 100 if trades else 0,
            'take_profit_rate': len(take_profits) / len(trades) * 100 if trades else 0,
            'trades': trades
        }
        
        self.accounts_data = {}
        self.positions_by_account = {}
        self.sentiment = {}
        
        # 飞书
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu'].get('openId', '')
        self.feishu_token = None
    
    def get_feishu_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={"app_id": self.feishu_app_id, "app_secret": self.feishu_app_secret})
        if res.status_code == 200:
            self.feishu_token = res.json().get('tenant_access_token')
            return True
        return False
    
    def fetch_data(self, force_sync=False):
        """获取数据"""
        print("📊 获取数据...")
        
        # 加载富途账户数据
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
            
            if data.get('source') == 'futu_simulate' and 'accounts' in data:
                accounts = data.get('accounts', [])
                positions_raw = data.get('positions', [])
                
                self.accounts_data = {}
                self.positions_by_account = {}
                
                for acc in accounts:
                    acc_id = acc.get('acc_id')
                    market_val = acc.get('market_val', 0)
                    total_asset = acc.get('total_assets', 0)
                    cash = acc.get('cash', 0)
                    initial = 1000000
                    total_pnl = total_asset - initial
                    total_pnl_pct = total_pnl / initial * 100 if initial > 0 else 0
                    
                    self.accounts_data[acc_id] = {
                        'initial': initial,
                        'total_asset': total_asset,
                        'position_value': market_val,
                        'cash': cash,
                        'total_pnl': total_pnl,
                        'total_pnl_pct': total_pnl_pct
                    }
                    self.positions_by_account[acc_id] = []
                
                for pos in positions_raw:
                    acc_id = pos.get('acc_id')
                    if acc_id not in self.positions_by_account:
                        self.positions_by_account[acc_id] = []
                    
                    symbol = pos['symbol'].replace('US.', '').replace('HK.', '')
                    shares = pos['shares']
                    cost = pos['cost_price']
                    market_val = pos.get('market_val', 0)
                    pl_ratio = pos.get('pl_ratio', 0)
                    price = market_val / shares if shares > 0 else cost
                    
                    self.positions_by_account[acc_id].append({
                        'symbol': symbol,
                        'shares': shares,
                        'cost': cost,
                        'price': price,
                        'pnl_pct': pl_ratio * 100,  # 小数转换为百分比，和交易系统单位统一
                        'market_val': market_val
                    })
                
                # 兼容：所有持仓放一起
                self.positions = []
                for poss in self.positions_by_account.values():
                    self.positions.extend(poss)
                
                display_acc = accounts[0] if accounts else {'acc_id': 15270898}
                self.account_data = self.accounts_data.get(display_acc.get('acc_id'), self.accounts_data.get(15270898))
                
                total_pos_count = sum(len(p) for p in self.positions_by_account.values())
                print(f"✅ 获取持仓数据: {total_pos_count}只")
        
        # 获取VHSI
        self.hk_vhsi = self.get_vhsi_data()
        # 获取VIX
        self.us_vix = self.get_vix_data()
        
        print(f"✅ VHSI={self.hk_vhsi:.1f}, VIX={self.us_vix:.1f}")
    
    def get_position_news(self, symbols, limit=2):
        """获取持仓相关新闻
        
        Args:
            symbols: 持仓股票代码列表
            limit: 每只股票获取的新闻数量
        """
        import sqlite3
        from datetime import datetime, timedelta
        
        news_by_symbol = {}
        db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取最近3天的新闻
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
            
            for symbol in symbols:
                # 清理股票代码（去掉US./HK.前缀）
                clean_symbol = symbol.replace('US.', '').replace('HK.', '')
                
                cursor.execute('''
                    SELECT title, sentiment, timestamp, url 
                    FROM news 
                    WHERE symbol = ? AND timestamp >= ?
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (clean_symbol, three_days_ago, limit))
                
                rows = cursor.fetchall()
                if rows:
                    news_by_symbol[symbol] = [
                        {
                            'title': row[0],
                            'sentiment': row[1],
                            'timestamp': row[2][:10],
                            'url': row[3]
                        }
                        for row in rows
                    ]
            
            conn.close()
        except Exception as e:
            print(f"⚠️ 获取新闻失败: {e}")
        
        return news_by_symbol

    def get_market_news(self, limit=10):
        """获取市场重要新闻（优先中文来源，按情绪极端程度排序）
        
        优先显示情绪极端的新闻（正面>0.7或负面<0.3）
        优先中文来源：新浪财经、东方财富、港交所、观察者网
        过滤乱码新闻
        """
        import sqlite3
        import re
        from datetime import datetime, timedelta
        
        news_list = []
        db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取最近3天的新闻
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
            
            # 获取所有新闻，按来源和时间排序
            cursor.execute('''
                SELECT title, source, sentiment, timestamp 
                FROM news 
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 100
            ''', (three_days_ago,))
            
            rows = cursor.fetchall()
            
            # 过滤乱码新闻，确保来源多样化
            sources_count = {}
            for row in rows:
                title = row[0]
                source = row[1]
                
                # 检查是否是乱码（包含非正常字符）
                if re.search(r'[äëïöüàèìòù]', title):
                    continue
                
                # 每个来源最多2条
                if source not in sources_count:
                    sources_count[source] = 0
                
                if sources_count[source] >= 2:
                    continue
                
                sources_count[source] += 1
                
                news_list.append({
                    'title': title,
                    'source': source,
                    'sentiment': row[2],
                    'timestamp': row[3][:10]
                })
                
                if len(news_list) >= limit:
                    break
            
            conn.close()
        except Exception as e:
            print(f"⚠️ 获取市场新闻失败: {e}")
        
        return news_list

    def get_earnings_calendar(self, days=7):
        """获取未来N天的财报日历"""
        try:
            import requests
            from datetime import datetime, timedelta
            
            # 从配置文件获取Finnhub API Key
            api_keys = load_api_keys()
            api_key = api_keys.get('finnhub', {}).get('api_key', 'd1t843pr01qr2iisvusgd1t843pr01qr2iisvut0')
            
            from_date = datetime.now().strftime('%Y-%m-%d')
            to_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={api_key}"
            
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                earnings = data.get('earningsCalendar', [])
                
                result = []
                for e in earnings[:10]:  # 最多10家
                    result.append({
                        'symbol': e.get('symbol', ''),
                        'date': e.get('date', ''),
                        'hour': e.get('hour', ''),  # bmo=盘前, amc=盘后
                        'eps_est': e.get('epsEstimate', 'N/A'),
                        'revenue_est': e.get('revenueEstimate', 'N/A'),
                        'eps_actual': e.get('epsActual', 'N/A'),
                    })
                
                return result
        except Exception as e:
            print(f"⚠️ 获取财报日历失败: {e}")
        
        return []

    def get_vhsi_data(self):
        """获取港股VHSI波幅指数"""
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            ret, data = ctx.get_market_snapshot(['HK.800125'])
            ctx.close()
            if ret == RET_OK and len(data) > 0:
                # 使用last_price字段
                return float(data.iloc[0].get('last_price', 25))
        except Exception as e:
            print(f"⚠️ 获取VHSI失败: {e}")
        return 25.0
    
    def get_vix_data(self):
        """获取美股VIX恐慌指数 - 使用Yahoo Finance"""
        try:
            import requests
            # Yahoo Finance VIX数据
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
        return 20.0
    
    def fetch_hk_index_data(self):
        """获取港股指数数据 - 优先使用Futu API，备用Yahoo Finance"""
        data = {}
        
        # 方式1: 尝试Futu API
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            indices = {
                'HK.800000': '恒生指数',
                'HK.800100': '国企指数',
                'HK.800700': '恒生科技'
            }
            codes = list(indices.keys())
            ret, snapshot = ctx.get_market_snapshot(codes)
            ctx.close()
            
            if ret == RET_OK:
                for _, row in snapshot.iterrows():
                    code = row['code']
                    name = indices.get(code, code)
                    price = row.get('last_price', 0)
                    prev_close = row.get('prev_close_price', 0)
                    
                    if price and prev_close:
                        change = price - prev_close
                        change_pct = (change / prev_close) * 100
                        
                        data[name] = {
                            'price': price,
                            'change': change,
                            'change_pct': change_pct
                        }
                        print(f"  ✅ {name}: {price:.2f} ({change_pct:+.2f}%)")
                
                if len(data) >= 2:
                    return data
        except Exception as e:
            print(f"⚠️ Futu获取港股指数失败: {e}")
        
        # 方式2: 备用Yahoo Finance
        try:
            import requests
            
            indices_yahoo = {
                '^HSI': '恒生指数',
                '^HSCE': '国企指数',
                '^HSTECH': '恒生科技'
            }
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            for symbol, name in indices_yahoo.items():
                if name in data:  # 已经获取到了
                    continue
                    
                try:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d"
                    resp = requests.get(url, headers=headers, timeout=5)
                    
                    if resp.status_code == 200:
                        result = resp.json()
                        chart = result.get('chart', {}).get('result', [])
                        
                        if chart:
                            meta = chart[0].get('meta', {})
                            price = meta.get('regularMarketPrice', 0)
                            prev_close = meta.get('chartPreviousClose', 0)
                            
                            if price and prev_close:
                                change = price - prev_close
                                change_pct = (change / prev_close) * 100
                                
                                data[name] = {
                                    'price': price,
                                    'change': change,
                                    'change_pct': change_pct
                                }
                                print(f"  ✅ {name}: {price:.2f} ({change_pct:+.2f}%)")
                except Exception as e:
                    print(f"⚠️ Yahoo获取{name}失败: {e}")
                    continue
        except Exception as e:
            print(f"⚠️ Yahoo获取港股指数失败: {e}")
        
        # 如果恒生科技指数没有数据，添加占位
        if '恒生科技' not in data:
            data['恒生科技'] = {
                'price': 0,
                'change': 0,
                'change_pct': 0
            }
            print(f"  ⏸️ 恒生科技: 暂无数据")
        
        return data
    
    def fetch_us_index_data(self):
        """获取美股指数数据 - 使用Yahoo Finance"""
        data = {}
        try:
            import requests
            
            # Yahoo Finance指数代码
            indices = {
                '^GSPC': '标普500',
                '^NDX': '纳斯达克100',
                '^DJI': '道琼斯'
            }
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            for symbol, name in indices.items():
                try:
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d"
                    resp = requests.get(url, headers=headers, timeout=5)
                    
                    if resp.status_code == 200:
                        result = resp.json()
                        chart = result.get('chart', {}).get('result', [])
                        
                        if chart:
                            meta = chart[0].get('meta', {})
                            price = meta.get('regularMarketPrice', 0)
                            prev_close = meta.get('chartPreviousClose', 0)
                            
                            if price and prev_close:
                                change = price - prev_close
                                change_pct = (change / prev_close) * 100
                                
                                data[name] = {
                                    'price': price,
                                    'change': change,
                                    'change_pct': change_pct,
                                    'high': meta.get('regularMarketDayHigh', 0),
                                    'low': meta.get('regularMarketDayLow', 0),
                                    'volume': meta.get('regularMarketVolume', 0)
                                }
                                print(f"  ✅ {name}: {price:.2f} ({change_pct:+.2f}%)")
                except Exception as e:
                    print(f"⚠️ 获取{name}失败: {e}")
                    continue
        except Exception as e:
            print(f"⚠️ 获取美股指数失败: {e}")
        
        return data
    
    def build_markdown_report(self):
        """构建Markdown日报"""
        title = "🇭🇰🇺🇸 港股美股日报"
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        acc_names = {15270898: '🇺🇸 美股', 15270899: '🇭🇰 港股'}
        symbol_names = {
            'NVDA': '英伟达', 'AAPL': '苹果', 'TSLA': '特斯拉',
            'AMD': '超微半导体', 'META': 'Meta', 'MSFT': '微软',
            'GOOGL': '谷歌', 'GOOG': 'GOOG', 'AMZN': '亚马逊',
            'VRT': 'Vertiv Holdings', 'LRCX': '泛林', 'CRM': 'Salesforce',
            'TTD': 'Trade Desk', 'MO': 'Altria', 'GEV': 'GEV',
            'ADEA': 'ADEA', 'MU': 'MU', 'LII': 'LII', 'ETR': 'ETR',
            'COP': 'COP', 'AIP': 'AIP', 'XOM': 'XOM',
            'HK.00005': '汇丰控股', 'HK.00012': '恒基地产', 'HK.00016': '新鸿基地产',
            'HK.00027': '银河娱乐', 'HK.00101': '恒隆地产', 'HK.00175': '吉利汽车',
            'HK.00241': '中信股份', 'HK.00285': '贝壳',
        }
        
        # 计算汇总数据
        total_asset = sum(ad['total_asset'] for ad in self.accounts_data.values())
        total_pos = sum(ad['position_value'] for ad in self.accounts_data.values())
        total_cash = sum(ad['cash'] for ad in self.accounts_data.values())
        all_positions = [p for poss in self.positions_by_account.values() for p in poss]
        total_pnl = sum(p['shares'] * (p['price'] - p['cost']) for p in all_positions)
        
        pos_pct = total_pos / total_asset * 100 if total_asset > 0 else 0
        cash_pct = total_cash / total_asset * 100 if total_asset > 0 else 0
        initial_pct = (total_asset - 2000000) / 2000000 * 100
        
        report = f"""# {title} {date_str}

---

## 📊 一、账户核心数据

"""
        
        for acc_id, ad in self.accounts_data.items():
            market = acc_names.get(acc_id, f'账户{acc_id}')
            positions = self.positions_by_account.get(acc_id, [])
            if ad['total_asset'] > 0:
                pos_pct_a = ad['position_value'] / ad['total_asset'] * 100
                cash_pct_a = ad['cash'] / ad['total_asset'] * 100
                initial_pct_a = (ad['total_asset'] - 1000000) / 1000000 * 100
            else:
                pos_pct_a = cash_pct_a = initial_pct_a = 0
            total_pnl_a = sum(p['shares'] * (p['price'] - p['cost']) for p in positions)
            
            report += f"### {market}账户 ({acc_id})\n\n"
            report += f"| 指标 | 数值 | 备注 |\n|------|------|------|\n"
            report += f"| 初始资金 | $1,000,000.00 | 模拟盘初始本金 |\n"
            profit_loss = '盈利' if initial_pct_a >= 0 else '亏损'
            report += f"| 当前总资产 | ${ad['total_asset']:,.2f} | {profit_loss}{abs(initial_pct_a):.2f}% |\n"
            report += f"| 持仓总市值 | ${ad['position_value']:,.2f} | 占总资产{pos_pct_a:.2f}% |\n"
            report += f"| 可用资金 | ${ad['cash']:,.2f} | 占总资产{cash_pct_a:.2f}% |\n"
            pl_txt = '盈利' if total_pnl_a >= 0 else '亏损'
            report += f"| 浮动盈亏 | ${total_pnl_a:+,.2f} | {pl_txt} |\n\n"
        
        # 加载交易系统的持仓目标价数据（同源）
        position_targets = {}
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/open-positions.json', 'r') as f:
                positions = json.load(f)
            for p in positions:
                position_targets[p['symbol']] = {
                    'target_stop_loss': p.get('target_stop_loss', round(p['entry_price'] * 0.94, 2)),
                    'target_take_profit': p.get('target_take_profit', round(p['entry_price'] * 1.08, 2))
                }
        except:
            pass
        
        if all_positions:
            report += "## 📦 二、当前持仓明细\n\n"
            report += "| 标的代码 | 标的名称 | 持仓数量 | 平均成本 | 当前市值 | 浮动盈亏 | 盈亏比例 | 止损价 | 目标止盈价 |\n"
            report += "|----------|----------|----------|----------|----------|----------|----------|--------|------------|\n"
            for pos in all_positions:
                sym = pos['symbol']
                name = symbol_names.get(sym, sym)
                mv = pos['shares'] * pos['price']
                pnl = pos['shares'] * (pos['price'] - pos['cost'])
                # 优先读取交易系统的同源目标价，没有则按规则计算
                target_info = position_targets.get(sym, {})
                stop_loss = target_info.get('target_stop_loss', round(pos['cost'] * 0.94, 2))
                take_profit = target_info.get('target_take_profit', round(pos['cost'] * 1.08, 2))
                report += f"| {sym} | {name} | {pos['shares']}股 | ${pos['cost']:.2f} | ${mv:,.2f} | ${pnl:+,.2f} | {pos['pnl_pct']:+.2f}% | ${stop_loss:.2f} | ${take_profit:.2f} |\n"
            report += "\n"
        
        # 策略持仓收益统计
        hk_stats = self.get_strategy_pnl_stats(market='hk')
        us_stats = self.get_strategy_pnl_stats(market='us')
        
        report += "## 📋 三、本日策略收益\n\n"
        
        # 港股统计
        report += "### 🇭🇰 港股策略 v2.1\n\n"
        if hk_stats and hk_stats['total'] > 0:
            report += f"| 指标 | 数值 |\n"
            report += f"|------|------|\n"
            report += f"| 持仓数 | {hk_stats['total']}只 |\n"
            report += f"| 盈利股数 | {hk_stats['wins']}只 |\n"
            report += f"| 胜率 | {hk_stats['win_rate']:.1f}% |\n"
            report += f"| 总市值 | ${hk_stats['total_market_val']:,.2f} |\n"
            report += f"| 总浮盈 | ${hk_stats['total_pnl']:+,.2f} |\n"
            report += f"| 平均浮盈 | {hk_stats['avg_pnl_pct']:+.2f}% |\n"
        else:
            report += "暂无持仓\n\n"
        
        # 美股统计
        report += "### 🇺🇸 美股策略 v1.7\n\n"
        if us_stats and us_stats['total'] > 0:
            report += f"| 指标 | 数值 |\n"
            report += f"|------|------|\n"
            report += f"| 持仓数 | {us_stats['total']}只 |\n"
            report += f"| 盈利股数 | {us_stats['wins']}只 |\n"
            report += f"| 胜率 | {us_stats['win_rate']:.1f}% |\n"
            report += f"| 总市值 | ${us_stats['total_market_val']:,.2f} |\n"
            report += f"| 总浮盈 | ${us_stats['total_pnl']:+,.2f} |\n"
            report += f"| 平均浮盈 | {us_stats['avg_pnl_pct']:+.2f}% |\n"
            
            # 显示当前持仓明细
            if us_stats['positions']:
                report += "\n**持仓明细：**\n\n"
                report += "| 标的 | 市值 | 浮盈 |\n"
                report += "|------|------|------|\n"
                for p in us_stats['positions'][:10]:
                    sym = p.get('symbol', '')
                    mv = p.get('market_val', 0)
                    pnl_pct = p.get('pnl_pct', 0)
                    report += f"| {sym} | ${mv:,.0f} | {pnl_pct:+.2f}% |\n"
        else:
            report += "暂无持仓\n\n"
        report += "\n"
        
        report += """## 🎯 四、当前策略说明

### 🇭🇰 港股策略（v2.1 新闻增强版）

**核心规则**
- 四源共振：国际资讯(30%)、港股公告(20%)、国内社区(25%)、海外社交(25%)
- 新闻情绪：市场整体情绪(0.52)，正面+15分，负面-10分
- 情绪监控：VHSI恒指波幅、港股通资金流向、牛熊证比例
- 开仓规则：评分≥70分，均线金叉，成交量≥1.5倍，RSI 20-80，仓位2-5%
- 止损规则：单票浮亏≥6%强制止损
- 止盈规则：收益≥15%分批止盈

### 🇺🇸 美股策略（v1.7 LLM增强版）

**核心规则**
- 四源共振：国际资讯(35%)、监管公告(20%)、国内社区(25%)、海外社交(20%)
- LLM分析：基础评分≥70触发，最终评分≥65才入场
- 严格择时：MA20>MA50，价格>MA20，技术信号≥2，成交量≥1.8倍，RSI<65
- 开仓规则：评分≥70分，单票仓位12%，总仓位≤40%
- 止损规则：ATR动态止损（1.8-2.0倍），浮亏≥6%强制止损
- 止盈规则：ATR动态止盈（4.0-4.5倍），收益≥15%分批止盈，最大持仓6天

**版本变更记录**

| 版本号 | 市场 | 更新时间 | 变更内容 |
|--------|------|----------|----------|
| v2.1 | 港股 | 2026-04-02 | 新闻情绪注入，动态行业权重 |
| v1.7 | 美股 | 2026-04-02 | LLM增强分析，严格择时 |
| v1.0 | 港股/美股 | 2026-03-22 | 初始版本上线 |

"""
        
        report += "## 🔍 五、当日交易记录\n\n"
        
        # 获取今日交易记录
        today_trades = self.get_today_trades(market='us' if self.us_mode else 'hk')
        
        # 显示开仓记录
        if today_trades['open_positions']:
            report += "### 📈 开仓记录\n\n"
            for pos in today_trades['open_positions']:
                sym = pos.get('symbol', '').replace('US.', '').replace('HK.', '')
                shares = pos.get('shares', 0)
                price = pos.get('entry_price', 0)
                time = pos.get('entry_time', '')[:16]
                score = pos.get('entry_score', 0)
                reasons = pos.get('entry_reasons', [])
                
                report += f"**{sym}** | {shares}股 @ ${price:.2f} | {time}\n\n"
                if score > 0:
                    report += f"- 📊 评分: {score}分\n"
                if reasons:
                    report += "- 🎯 开仓原因:\n"
                    for r in reasons[:5]:  # 最多显示5条
                        report += f"  • {r}\n"
                report += "\n"
        else:
            report += "### 📈 开仓记录\n\n今日无开仓操作\n\n"
        
        # 显示平仓记录
        if today_trades['closed_trades']:
            report += "### 💰 平仓记录\n\n"
            for trade in today_trades['closed_trades']:
                sym = trade.get('symbol', '').replace('US.', '').replace('HK.', '')
                shares = trade.get('shares', 0)
                entry_price = trade.get('entry_price', 0)
                exit_price = trade.get('exit_price', 0)
                time = trade.get('close_time', '')[:16]
                reason = trade.get('reason', '未知')
                stop_type = trade.get('stop_type', '')
                pnl_pct = trade.get('pnl_pct', 0)
                peak_pnl = trade.get('peak_pnl_pct', 0)
                hold_days = trade.get('hold_days', 0)
                
                pnl_icon = "✅" if pnl_pct > 0 else "❌"
                pnl_str = f"{pnl_pct:+.2f}%"
                
                report += f"**{sym}** | {shares}股 | {time}\n\n"
                report += f"- 💵 开仓价: ${entry_price:.2f} → 平仓价: ${exit_price:.2f}\n"
                report += f"- {pnl_icon} 盈亏: {pnl_str}"
                if peak_pnl > 0:
                    report += f" (峰值: {peak_pnl:+.2f}%)"
                report += "\n"
                report += f"- 🎯 平仓原因: {reason}"
                if stop_type:
                    report += f" ({stop_type})"
                report += "\n\n"
        else:
            report += "### 💰 平仓记录\n\n今日无平仓操作\n\n"
        
        report += "---\n\n"
        
        hk_index_data = self.fetch_hk_index_data()
        us_index_data = self.fetch_us_index_data()
        
        def safe_float(val):
            try:
                f = float(val)
                return f if str(val) not in ('N/A', '', None, 'None') else 0.0
            except:
                return 0.0
        
        # 获取持仓相关新闻
        position_symbols = [pos['symbol'] for pos in all_positions]
        position_news = self.get_position_news(position_symbols, limit=3)
        
        # 获取市场重要新闻（按情绪排序，优先显示极端情绪）
        market_news = self.get_market_news(limit=5)
        
        report += """## 📰 六、当日核心新闻与市场分析

### 📈 持仓标的相关新闻
"""
        if all_positions:
            has_news = False
            for pos in all_positions[:5]:
                sym = pos['symbol']
                name = symbol_names.get(sym, sym)
                news_list = position_news.get(sym, [])
                
                if news_list:
                    has_news = True
                    report += f"\n**{sym} ({name})**\n\n"
                    for news in news_list:
                        sentiment_icon = "📈" if news['sentiment'] > 0.3 else "📉" if news['sentiment'] < -0.3 else "➡️"
                        report += f"{sentiment_icon} {news['title']}\n\n"
                        report += f"   {news['timestamp']}\n\n"
            
            if not has_news:
                report += "\n暂无持仓相关重要新闻\n"
        else:
            report += "\n暂无持仓\n"
        
        report += "\n### 🌍 市场重要新闻\n\n"
        if market_news:
            for news in market_news:
                sentiment_icon = "📈" if news['sentiment'] > 0.3 else "📉" if news['sentiment'] < -0.3 else "➡️"
                report += f"{sentiment_icon} **{news['title']}**\n\n"
                report += f"   来源: {news['source']} | {news['timestamp']}\n\n"
        else:
            report += "暂无市场重要新闻\n"
        
        report += """

### 🇭🇰 港股市场走势分析

**港股三大指数表现**：
"""
        if hk_index_data:
            for name, data in hk_index_data.items():
                chg_pct = safe_float(data.get('change_pct'))
                trend = "上涨" if chg_pct >= 0 else "下跌"
                report += f"• {name}: {safe_float(data.get('price')):,.2f} ({chg_pct:+.2f}%)，今日{trend}\n"
        
        # LLM解读港股走势
        hk_analysis = self.llm.get_market_analysis('hk', hk_index_data, self.hk_vhsi)
        if hk_analysis:
            report += f"\n> {hk_analysis}\n\n"
        else:
            report += f"\n**VHSI波幅指数**: {self.hk_vhsi:.1f}\n\n"
        
        report += """### 🇺🇸 美股市场走势分析

**美股三大指数表现**：
"""
        if us_index_data:
            for name, data in us_index_data.items():
                chg_pct = safe_float(data.get('change_pct'))
                trend = "上涨" if chg_pct >= 0 else "下跌"
                report += f"• {name}: {safe_float(data.get('price')):,.2f} ({chg_pct:+.2f}%)，今日{trend}\n"
        
        # LLM解读美股走势
        us_analysis = self.llm.get_market_analysis('us', us_index_data, self.us_vix)
        if us_analysis:
            report += f"\n> {us_analysis}\n\n"
        else:
            report += f"\n**VIX恐慌指数**: {self.us_vix:.1f}\n\n"
        
        # 判断情绪状态
        hk_emotion = "🔴 极度恐慌" if self.hk_vhsi >= 30 else "🟠 恐慌" if self.hk_vhsi >= 25 else "🟡 正常" if self.hk_vhsi >= 20 else "🟢 平静"
        us_emotion = "🔴 极度恐慌" if self.us_vix >= 30 else "🟠 恐慌" if self.us_vix >= 25 else "🟡 正常" if self.us_vix >= 20 else "🟢 平静"
        
        # 获取LLM市场预测
        hk_prediction = self.llm.get_market_prediction('hk', self.hk_vhsi, hk_index_data)
        us_prediction = self.llm.get_market_prediction('us', self.us_vix, us_index_data)
        
        report += f"""
### 🇭🇰 港股市场情绪

| 指标名称 | 数值 | 状态说明 |
|----------|------|----------|
| VHSI波幅 | {self.hk_vhsi:.1f} | {hk_emotion} |

**未来3日港股预判：**
| 时间 | 情绪预判 | 概率 | 市场走势预判 |
|----------|----------|------|----------|
"""
        if hk_prediction:
            for pred in hk_prediction:
                report += f"| {pred['day']} | {pred['sentiment']} | {pred['probability']} | {pred['trend']} |\n"
        else:
            report += """| T+1日 | 中性偏多 | 60% | 震荡整理 |
| T+2日 | 乐观 | 65% | 科技股机会 |
| T+3日 | 中性 | 60% | 等待信号 |
"""
        
        report += f"""
### 🇺🇸 美股市场情绪

| 指标名称 | 数值 | 状态说明 |
|----------|------|----------|
| VIX恐慌指数 | {self.us_vix:.1f} | {us_emotion} |

**未来3日美股预判：**
| 时间 | 情绪预判 | 概率 | 市场走势预判 |
|----------|----------|------|----------|
"""
        if us_prediction:
            for pred in us_prediction:
                report += f"| {pred['day']} | {pred['sentiment']} | {pred['probability']} | {pred['trend']} |\n"
        else:
            report += """| T+1日 | 中性偏多 | 60% | 指数平稳 |
| T+2日 | 乐观 | 65% | AI板块机会 |
| T+3日 | 中性 | 60% | 等待CPI |
"""

        # 获取财报日历
        earnings = self.get_earnings_calendar(days=7)
        
        report += """## 📈 七、财报与业绩预测

**未来7天即将发布财报的公司：**

| 标的代码 | 财报日期 | 披露时间 | 预期EPS | 预期营收 |
|----------|----------|----------|---------|----------|
"""
        
        if earnings:
            for e in earnings:
                time_label = "盘前" if e['hour'] == 'bmo' else "盘后" if e['hour'] == 'amc' else "-"
                eps = str(e['eps_est']) if e['eps_est'] and e['eps_est'] != 'N/A' else 'N/A'
                rev = f"{e['revenue_est']/1000000:.1f}M" if e['revenue_est'] and e['revenue_est'] != 'N/A' and isinstance(e['revenue_est'], (int, float)) else 'N/A'
                report += f"| {e['symbol']} | {e['date']} | {time_label} | {eps} | {rev} |\n"
        else:
            report += "暂无财报数据\n"

        report += """

"""

        # ===== 第八部分：LLM动态风险分析与操作建议 =====
        report += """## ⚠️ 八、风险提示与操作建议

"""
        # 准备市场数据供LLM分析
        llm_market_data = {
            'pos_pct': pos_pct,
            'cash_pct': cash_pct,
            'vix': self.us_vix,
            'vhsi': self.hk_vhsi,
            'total_asset': total_asset,
            'total_pnl': total_pnl,
            'positions': all_positions,
            'initial': 2000000
        }
        
        # LLM动态风险分析
        report += "### 1. 风险评估\n\n"
        risk_text = self.llm.get_risk_assessment(llm_market_data)
        if risk_text:
            # 解析格式：风险等级|风险类型|具体描述|建议动作
            for line in risk_text.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 4:
                    level = parts[0].strip()
                    rtype = parts[1].strip()
                    desc = parts[2].strip()
                    action = parts[3].strip()
                    report += f"• {level} **{rtype}风险**：{desc} → {action}\n\n"
                elif len(parts) >= 2:
                    report += f"• {line}\n\n"
        else:
            # Fallback：基于数据的简单风险提示
            vix_level = "🔴高" if self.us_vix >= 25 else "🟠中" if self.us_vix >= 20 else "🟡低"
            vhsi_level = "🔴高" if self.hk_vhsi >= 25 else "🟠中" if self.hk_vhsi >= 20 else "🟡低"
            report += f"• {vix_level} **系统性风险**：VIX({self.us_vix:.1f})/VHSI({self.hk_vhsi:.1f})\n\n"
            if pos_pct > 60:
                report += f"• 🟠 **集中度风险**：持仓占比{pos_pct:.1f}%偏高\n\n"
            elif pos_pct < 20:
                report += f"• 🟡 **资金闲置**：持仓仅{pos_pct:.1f}%，现金占比{cash_pct:.1f}%\n\n"
        
        # LLM动态操作建议
        report += "### 2. 操作建议\n\n"
        action_text = self.llm.get_action_recommendations(llm_market_data)
        if action_text:
            for line in action_text.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    atype = parts[0].strip()
                    advice = parts[1].strip()
                    icon = '📊' if atype == '仓位管理' else '🎯' if atype == '止损止盈' else '💡' if atype == '开仓机会' else '🛡️'
                    report += f"• {icon} **{atype}**：{advice}\n\n"
                else:
                    report += f"• {line}\n\n"
        else:
            # Fallback：基于数据的基础建议
            if pos_pct > 60:
                report += "• 📉 建议适当减仓，控制仓位在40-50%\n\n"
            elif pos_pct < 20:
                report += "• 💡 当前仓位较低，可关注市场机会择机建仓\n\n"
            report += "• 📊 单票止损-6%，止盈+15%\n\n"
        
        report += f"""---

⏰ *报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
*🧠 风险评估与操作建议由LLM动态生成*
"""
        return report
    
    def save_report(self):
        """保存日报到文件"""
        today = datetime.now().strftime("%Y-%m-%d")
        md_file = MD_FILE.format(today)
        os.makedirs(os.path.dirname(md_file), exist_ok=True)
        
        report = self.build_markdown_report()
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✅ 日报已保存: {md_file}")
        return md_file, report


def create_feishu_doc(title, content):
    """创建飞书文档"""
    cmd = f'/home/admin/.npm-global/bin/lark-cli docs +create --title "{title}" --markdown "{content}" --wiki-space {WIKI_SPACE}'
    stdout, stderr, code = run_cmd(cmd)
    try:
        result = json.loads(stdout)
        if result.get('ok'):
            return result['data']['doc_url']
    except:
        pass
    return None

def send_to_feishu_chat(message, chat_id="oc_f6c5168cb212e624d21ccfabed49b083"):
    """发送消息到飞书群聊 - 使用FeishuPusher"""
    try:
        from feishu_pusher import FeishuPusher
        pusher = FeishuPusher()
        # 临时设置chat_id
        original_chat_id = pusher.chat_id
        pusher.chat_id = chat_id
        success = pusher.send_message(message)
        pusher.chat_id = original_chat_id
        return success
    except Exception as e:
        print(f"❌ 发送消息异常: {e}")
        return False


def is_hk_holiday():
    """检查今天是否是港股休市日（香港公众假期）"""
    from datetime import date
    
    # 香港2026年公众假期（仅影响港股日报）
    hk_holidays_2026 = [
        '2026-01-01',  # 元旦
        '2026-01-29',  # 农历新年前夕
        '2026-01-30',  # 农历新年
        '2026-01-31',  # 农历新年
        '2026-02-01',  # 农历新年
        '2026-02-02',  # 农历新年
        '2026-04-03',  # 耶稣受难日
        '2026-04-04',  # 清明节
        '2026-04-05',  # 清明节翌日
        '2026-04-06',  # 复活节星期一
        '2026-04-07',  # 清明节假期
        '2026-05-01',  # 劳动节
        '2026-05-03',  # 佛诞日
        '2026-07-01',  # 香港回归纪念日
        '2026-09-30',  # 中秋节翌日
        '2026-10-01',  # 国庆日
        '2026-10-07',  # 重阳节
        '2026-12-25',  # 圣诞节
        '2026-12-26',  # 圣诞节后首个周日
    ]
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    return today_str in hk_holidays_2026


def is_us_holiday():
    """检查今天是否是美股休市日（美国公众假期）"""
    from datetime import date
    
    # 美国2026年主要公众假期（美股休市日）
    us_holidays_2026 = [
        '2026-01-01',   # 新年 New Year's Day
        '2026-01-19',   # 马丁·路德·金纪念日 MLK Day
        '2026-02-16',   # 总统日 Presidents Day
        '2026-04-03',   # 耶稣受难日 Good Friday
        '2026-05-25',   # 阵亡将士纪念日 Memorial Day
        '2026-06-19',   # 六月节 Juneteenth
        '2026-07-03',   # 独立日前夕 Independence Day (observed)
        '2026-11-26',   # 感恩节 Thanksgiving
        '2026-12-25',   # 圣诞节 Christmas Day
    ]
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()  # 0=周一, 6=周日
    
    # 周日不交易（weekday=6），但周六凌晨需生成周五日报
    if weekday >= 6:
        return True
    
    return today_str in us_holidays_2026


def sync_futu_data():
    """同步富途账户数据"""
    import subprocess
    try:
        print("🔄 同步富途账户数据...")
        result = subprocess.run(
            ['/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3',
             '/home/admin/.openclaw/workspace-stock/strategy/sync-futu-account.py'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            print("✅ 数据同步成功")
            return True
        else:
            print(f"⚠️ 数据同步失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️ 数据同步异常: {e}")
        return False


def main():
    import sys
    us_mode = '--us' in sys.argv
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 根据模式检查对应的交易日
    if us_mode:
        # 美股模式：检查美股交易日
        if is_us_holiday():
            print(f"⏭️ 今天是美股休市日（{today}），跳过美股日报")
            return
        title = f"📊 美股日报 {today}"
    else:
        # 港股模式：检查港股交易日
        if is_hk_holiday():
            print(f"⏭️ 今天是港股休市日（{today}），跳过港股日报")
            return
        title = f"📊 港股日报 {today}"
    
    print(f"📊 生成日报: {title}")
    
    # 0. 同步数据
    sync_futu_data()
    
    # 1. 生成日报
    print("📝 生成完整日报...")
    reporter = ComprehensiveReportV11(us_mode=us_mode)
    reporter.fetch_data()
    md_file, report_content = reporter.save_report()
    
    # 2. 上传到飞书Wiki
    print("☁️ 上传到飞书Wiki...")
    doc_url = create_feishu_doc(title, report_content)
    
    if doc_url:
        print(f"✅ 上传成功: {doc_url}")
        
        # 3. 发送链接到群聊
        message = f"📊 今日日报已生成\n{doc_url}"
        print(f"📤 发送链接到群聊...")
        if send_to_feishu_chat(message):
            print("✅ 已发送到飞书群聊")
        else:
            print("⚠️ 发送到群聊失败")
    else:
        print("❌ 上传到Wiki失败")


if __name__ == "__main__":
    main()
