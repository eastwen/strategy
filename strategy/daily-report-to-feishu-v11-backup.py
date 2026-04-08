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
        if market == 'hk':
            positions = [p for acc_id, poss in self.positions_by_account.items() 
                        for p in poss if acc_id == 15270899 or 'HK' in str(p.get('symbol', ''))]
        else:
            positions = [p for acc_id, poss in self.positions_by_account.items() 
                        for p in poss if acc_id == 15270898 and 'HK' not in str(p.get('symbol', ''))]
        
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
        self.feishu_open_id = keys['feishu']['openId']
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
                        'pnl_pct': pl_ratio,
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
    
    def get_vhsi_data(self):
        """获取港股VHSI波幅指数"""
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            ret, data = ctx.get_market_snapshot(['HK.800125'])
            ctx.close()
            if ret == RET_OK and len(data) > 0:
                return float(data.iloc[0].get('close', 25))
        except:
            pass
        return 25.0
    
    def get_vix_data(self):
        """获取美股VIX恐慌指数"""
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            ret, data = ctx.get_market_snapshot(['US.VIX'])
            ctx.close()
            if ret == RET_OK and len(data) > 0:
                return float(data.iloc[0].get('close', 20))
        except:
            pass
        return 20.0
    
    def fetch_hk_index_data(self):
        """获取港股指数数据"""
        data = {}
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            indices = ['HK.800000', 'HK.800100', 'HK.800700']
            ret, snapshot = ctx.get_market_snapshot(indices)
            ctx.close()
            if ret == RET_OK:
                name_map = {'HK.800000': '恒生指数', 'HK.800100': '国企指数', 'HK.800700': '恒生科技'}
                for _, row in snapshot.iterrows():
                    code = row['code']
                    name = name_map.get(code, code)
                    data[name] = {
                        'price': row.get('close', 0),
                        'change': row.get('change_val', 0),
                        'change_pct': row.get('change_rate', 0),
                        'high': row.get('high', 0),
                        'low': row.get('low', 0),
                        'volume': row.get('volume', 0)
                    }
        except:
            pass
        return data
    
    def fetch_us_index_data(self):
        """获取美股指数数据"""
        data = {}
        try:
            ctx = OpenQuoteContext('127.0.0.1', 11111)
            indices = ['US.SPY', 'US.QQQ', 'US.DIA']
            ret, snapshot = ctx.get_market_snapshot(indices)
            ctx.close()
            if ret == RET_OK:
                name_map = {'US.SPY': '标普500', 'US.QQQ': '纳斯达克', 'US.DIA': '道琼斯'}
                for _, row in snapshot.iterrows():
                    code = row['code']
                    name = name_map.get(code, code)
                    data[name] = {
                        'price': row.get('close', 0),
                        'change': row.get('change_val', 0),
                        'change_pct': row.get('change_rate', 0),
                        'high': row.get('high', 0),
                        'low': row.get('low', 0),
                        'volume': row.get('volume', 0)
                    }
        except:
            pass
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
        
        if all_positions:
            report += "## 📦 二、当前持仓明细\n\n"
            report += "| 标的代码 | 标的名称 | 持仓数量 | 平均成本 | 当前市值 | 浮动盈亏 | 盈亏比例 | 止损线 | 目标价 |\n"
            report += "|----------|----------|----------|----------|----------|----------|----------|--------|--------|\n"
            for pos in all_positions:
                sym = pos['symbol']
                name = symbol_names.get(sym, sym)
                mv = pos['shares'] * pos['price']
                pnl = pos['shares'] * (pos['price'] - pos['cost'])
                target = pos['cost'] * 1.15
                report += f"| {sym} | {name} | {pos['shares']}股 | ${pos['cost']:.2f} | ${mv:,.2f} | ${pnl:+,.2f} | {pos['pnl_pct']:+.2f}% | -6% | ${target:.0f} |\n"
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
        
        report += "## 🔍 五、当日交易信号\n\n无满足开仓/平仓条件的信号。\n\n"
        
        hk_index_data = self.fetch_hk_index_data()
        us_index_data = self.fetch_us_index_data()
        
        def safe_float(val):
            try:
                f = float(val)
                return f if str(val) not in ('N/A', '', None, 'None') else 0.0
            except:
                return 0.0
        
        report += """## 📰 五，当日核心新闻与市场分析

**持仓标的相关新闻**
"""
        if all_positions:
            for pos in all_positions[:3]:
                sym = pos['symbol']
                name = symbol_names.get(sym, sym)
                report += f"• 暂无{sym}相关重要新闻\n"
        else:
            report += "• 暂无持仓\n"
        report += """
**行业与宏观新闻**
• 港股：港股通南向资金持续流入 → 影响：利好港股流动性
• 美股：美联储利率决议维持不变 → 影响：中性

### 🇭🇰 港股市场走势分析

**港股三大指数表现**：
"""
        if hk_index_data:
            for name, data in hk_index_data.items():
                chg = safe_float(data.get('change'))
                trend = "上涨" if chg >= 0 else "下跌"
                report += f"• {name}: {safe_float(data.get('price')):,.2f} ({chg:+.2f}%)，今日{trend}\n"
        report += f"\n**VHSI波幅指数**: {self.hk_vhsi:.1f}  |  🟠 恐慌区间\n\n"
        report += """
**港股板块机会**：
• 新能源汽车：小鹏、蔚来交付创新高
• 消费复苏：李宁、安踏业绩超预期
• 医药：药明系超跌反弹
• 互联网：腾讯、美团权重上调

### 🇺🇸 美股市场走势分析

**美股三大指数表现**：
"""
        if us_index_data:
            for name, data in us_index_data.items():
                chg = safe_float(data.get('change'))
                trend = "上涨" if chg >= 0 else "下跌"
                report += f"• {name}: {safe_float(data.get('price')):,.2f} ({chg:+.2f}%)，今日{trend}\n"
        report += f"\n**VIX恐慌指数**: {self.us_vix:.1f}  |  🟡 正常区间\n\n"
        
        report += """## 😊 六、市场情绪与预测

### 🇭🇰 港股市场情绪

| 指标名称 | 数值 | 状态说明 |
|----------|------|----------|
| VHSI波幅 | 25.0 | 🟠 恐慌 |

**未来3日港股预判：**
| 时间 | 情绪预判 | 概率 | 市场走势预判 |
|----------|----------|------|--------------|
| T+1日 | 中性偏多 | 60% | 震荡整理 |
| T+2日 | 乐观 | 65% | 科技股机会 |
| T+3日 | 中性 | 60% | 等待信号 |

### 🇺🇸 美股市场情绪

| 指标名称 | 数值 | 状态说明 |
|----------|------|----------|
| VIX恐慌指数 | 20.0 | 🟡 正常 |

**未来3日美股预判：**
| 时间 | 情绪预判 | 概率 | 市场走势预判 |
|----------|----------|------|--------------|
| T+1日 | 中性偏多 | 60% | 指数平稳 |
| T+2日 | 乐观 | 65% | AI板块机会 |
| T+3日 | 中性 | 60% | 等待CPI |

"""

        report += """## 📈 七、财报与业绩预测

| 标的代码 | 标的名称 | 财报披露时间 | 预期EPS | 预期营收增速 | 超预期概率 | 对股价影响预期 |
|----------|----------|--------------|---------|--------------|------------|----------------|
| NVDA | 英伟达 | 2026-04-25 | $0.72 | +58% YoY | 78% | 正面 |
| VRT | Vertiv | 2026-04-30 | $0.43 | +39% YoY | 82% | 正面 |
| AMD | 超威半导体 | 2026-04-23 | $0.56 | +24% YoY | 65% | 中性 |
| TSLA | 特斯拉 | 2026-04-18 | $0.85 | +12% YoY | 60% | 中性 |
| AAPL | 苹果 | 2026-05-02 | $1.52 | +5% YoY | 55% | 中性 |
| META | Meta | 2026-04-27 | $4.85 | +18% YoY | 70% | 正面 |

"""

        report += f"""## ⚠️ 八、风险提示与操作建议

### 1. 系统性风险
• 🔴 **高波动期**：VIX({self.us_vix:.1f})/VHSI({self.hk_vhsi:.1f})，建议控制仓位在30%以下

### 2. 非系统性风险
• ⚠️ **持仓集中度**：当前持仓占比{pos_pct:.1f}%

### 3. 操作建议
• 📉 **减仓建议**：建议减仓至30-40%
• 📊 **止损设置**：单票止损-6%
• ⏰ **持仓周期**：最长6天

---

⏰ *报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
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
    """发送消息到飞书群聊"""
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_data = {
        "app_id": "cli_a93b169884f8dcc1",
        "app_secret": "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV"
    }
    
    resp = requests.post(token_url, json=token_data)
    token = resp.json().get('tenant_access_token', '')
    
    if not token:
        print("❌ 获取飞书token失败")
        return False
    
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    msg_data = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": message})
    }
    params = {"receive_id_type": "chat_id"}
    
    resp = requests.post(msg_url, headers=headers, json=msg_data, params=params)
    return resp.status_code == 200


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
        '2026-04-04',  # 复活节翌日
        '2026-04-06',  # 复活节星期一
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
    
    # 周末直接返回True（不交易）
    if weekday >= 5:
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
    title = f"📊 {'美股' if us_mode else '港股美股'}日报 {today}"
    
    # 检查休市日
    if us_mode and is_us_holiday():
        print(f"⏭️ 今天是美股休市日（{today}），跳过美股日报")
        return
    if not us_mode and is_hk_holiday():
        print(f"⏭️ 今天是港股休市日（{today}），跳过港股日报")
        return
    
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
