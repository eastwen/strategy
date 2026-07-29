#!/usr/bin/env python3
"""
周报生成器 - 统一策略版本
统计本周交易数据、持仓表现、策略分析
"""

import sys
import os
import json
import requests
from datetime import datetime, timedelta
import re

from runtime_config import (
    API_KEYS_PATH, DATA_DIR, FUTU_HOST, FUTU_PORT, PYTHON_BIN, REPORTS_DIR,
    STRATEGY_DIR, STRATEGY_POLICY, format_strategy_policy_compact,
    format_strategy_policy_markdown,
)
from futu import OpenQuoteContext, RET_OK

# 常量
DATA_FILE = str(DATA_DIR / 'trades.json')
CLOSED_TRADES_FILE = str(DATA_DIR / 'closed-trades.json')
WEEKLY_HISTORY_FILE = str(DATA_DIR / 'weekly-history.json')
API_KEYS_FILE = str(API_KEYS_PATH)


def get_llm_weekly_suggestion(portfolio_summary, vix, vhsi, weekly_pnl_pct):
    """用LLM生成下周操作建议 - 通过llm_stock_analyzer统一调用"""
    import sys
    sys.path.insert(0, str(STRATEGY_DIR))
    from llm_stock_analyzer import get_llm_client
    
    client = get_llm_client()
    if not client.api_key:
        return format_strategy_policy_compact()
    
    prompt = f"""你是专业的投资顾问，请基于以下投资组合和市场情况，给出下周操作建议。

**当前投资组合：**
- 总资产: ${portfolio_summary.get('total_asset', 0):,.0f}
- 本周收益: {weekly_pnl_pct:+.2f}%
- 持仓集中度: {portfolio_summary.get('position_pct', 0):.1f}%
- 持仓数量: {portfolio_summary.get('position_count', 0)}只
- 盈利股数: {portfolio_summary.get('win_count', 0)}只
- 平均浮盈: {portfolio_summary.get('avg_pnl_pct', 0):+.2f}%

**市场情绪：**
- VIX恐慌指数: {vix:.1f} ({'恐慌' if vix >= 25 else '正常' if vix >= 20 else '平静'})
- VHSI波幅指数: {vhsi:.1f} ({'恐慌' if vhsi >= 25 else '正常' if vhsi >= 20 else '平静'})

**当前统一策略规则：**
{format_strategy_policy_compact()}

请给出3条具体的下周操作建议，每条建议格式：**标题**：内容

直接回复3条建议："""
    
    result = client.call(prompt, max_tokens=300, temperature=0.7)
    if result:
        return result
    print("⚠️ LLM周报建议调用失败")
    
    # 降级方案
    return format_strategy_policy_compact()



class WeeklyReportV3:
    """周报生成器v3 - 动态数据版"""
    
    def __init__(self):
        self.load_api_keys()
        self.accounts_data = {}
        self.positions = []
        self.closed_trades = []
        self.last_week_assets = {}
        self.feishu_token = None
        
    def load_api_keys(self):
        with open(API_KEYS_FILE, 'r') as f:
            keys = json.load(f)
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_chat_id = keys['feishu'].get('chatId', '')
    
    def get_feishu_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        if res.status_code == 200 and res.json().get('code') == 0:
            self.feishu_token = res.json().get('tenant_access_token')
            return True
        return False
    
    def fetch_account_data(self):
        """获取当前账户数据"""
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
            
            if data.get('source') == 'futu_simulate':
                accounts = data.get('accounts', [])
                positions_raw = data.get('positions', [])
                
                for acc in accounts:
                    acc_id = acc.get('acc_id')
                    self.accounts_data[acc_id] = {
                        'total_asset': acc.get('total_assets', 0),
                        'cash': acc.get('cash', 0),
                        'position_value': acc.get('market_val', 0)
                    }
                
                for pos in positions_raw:
                    symbol = pos['symbol'].replace('US.', '').replace('HK.', '')
                    self.positions.append({
                        'symbol': symbol,
                        'shares': pos['shares'],
                        'cost': pos['cost_price'],
                        'pnl_pct': pos.get('pl_ratio', 0),  # trades.json 使用百分比数值
                        'market_val': pos.get('market_val', 0),
                        'acc_id': pos.get('acc_id')
                    })
                
                print(f"✅ 获取账户数据: {len(self.positions)}只持仓")
                return True
        except Exception as e:
            print(f"❌ 获取账户数据失败: {e}")
        return False
    
    def fetch_closed_trades(self):
        """获取本周平仓交易"""
        try:
            with open(CLOSED_TRADES_FILE, 'r') as f:
                all_trades = json.load(f)
            
            # 本周一的时间
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())
            week_start_str = week_start.strftime('%Y-%m-%d')
            
            # 筛选本周交易
            self.closed_trades = []
            for t in all_trades:
                close_time = t.get('close_time', '')
                if close_time and close_time >= week_start_str:
                    self.closed_trades.append(t)
            
            print(f"✅ 本周平仓: {len(self.closed_trades)}笔")
            return True
        except Exception as e:
            print(f"⚠️ 获取平仓记录失败: {e}")
            return False
    
    def load_last_week_data(self):
        """加载上周数据"""
        try:
            with open(WEEKLY_HISTORY_FILE, 'r') as f:
                history = json.load(f)
            
            # 获取上周的记录
            if history:
                last_week = max(history.keys())
                self.last_week_assets = history[last_week].get('accounts', {})
                print(f"✅ 上周数据: {last_week}")
        except:
            print("⚠️ 无上周数据")
    
    def save_this_week_data(self):
        """保存本周数据"""
        try:
            # 读取现有历史
            try:
                with open(WEEKLY_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            except:
                history = {}
            
            # 保存本周数据
            week_key = datetime.now().strftime('%Y-%m-%d')
            history[week_key] = {
                'accounts': self.accounts_data,
                'closed_trades': len(self.closed_trades)
            }
            
            with open(WEEKLY_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            
            print(f"✅ 已保存本周数据")
        except Exception as e:
            print(f"⚠️ 保存失败: {e}")
    
    def get_vix_data(self):
        """获取VIX"""
        try:
            ctx = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
            ret, data = ctx.get_market_snapshot(['US.VIX'])
            ctx.close()
            if ret == RET_OK and len(data) > 0:
                return float(data.iloc[0].get('close', 20))
        except:
            pass
        return 20.0
    
    def get_vhsi_data(self):
        """获取VHSI"""
        try:
            ctx = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
            ret, data = ctx.get_market_snapshot(['HK.800125'])
            ctx.close()
            if ret == RET_OK and len(data) > 0:
                return float(data.iloc[0].get('close', 25))
        except:
            pass
        return 25.0
    
    def calculate_weekly_stats(self):
        """计算本周统计数据"""
        # 分市场统计平仓
        hk_trades = [t for t in self.closed_trades if t.get('market') == 'hk' or 'HK' in t.get('symbol', '')]
        us_trades = [t for t in self.closed_trades if t.get('market') == 'us' or 'US' in t.get('symbol', '') or (t.get('market') != 'hk' and 'HK' not in t.get('symbol', ''))]
        
        def calc_stats(trades):
            if not trades:
                return None
            wins = [t for t in trades if t.get('pnl_pct', 0) > 0]
            losses = [t for t in trades if t.get('pnl_pct', 0) < 0]
            total_pnl = sum(t.get('pnl', 0) for t in trades)
            avg_win = sum(t.get('pnl_pct', 0) for t in wins) / len(wins) if wins else 0
            avg_loss = sum(t.get('pnl_pct', 0) for t in losses) / len(losses) if losses else 0
            return {
                'total': len(trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins) / len(trades) * 100 if trades else 0,
                'total_pnl': total_pnl,
                'avg_win_pct': avg_win,
                'avg_loss_pct': avg_loss
            }
        
        return {
            'hk': calc_stats(hk_trades),
            'us': calc_stats(us_trades)
        }
    
    def get_strategy_pnl_stats(self, market='us'):
        """获取策略持仓收益统计"""
        # 筛选持仓
        if market == 'hk':
            positions = [p for p in self.positions if p.get('acc_id') == 15270899 or 'HK' in str(p.get('symbol', ''))]
        else:
            positions = [p for p in self.positions if 'HK' not in str(p.get('symbol', ''))]
        
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
    
    def generate_report(self):
        """生成周报"""
        # 获取数据
        self.fetch_account_data()
        self.fetch_closed_trades()
        self.load_last_week_data()
        
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        date_str = today.strftime("%Y-%m-%d")
        
        # 计算本周收益
        total_asset = sum(a['total_asset'] for a in self.accounts_data.values())
        initial = 2000000.0
        
        # 上周资产
        last_week_total = sum(a.get('total_asset', 0) for a in self.last_week_assets.values()) if self.last_week_assets else total_asset
        weekly_pnl = total_asset - last_week_total
        weekly_pnl_pct = (weekly_pnl / last_week_total * 100) if last_week_total > 0 else 0
        
        total_pnl = total_asset - initial
        total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0
        
        # 统计
        stats = self.calculate_weekly_stats()
        vix = self.get_vix_data()
        vhsi = self.get_vhsi_data()
        
        # 持仓集中度
        total_pos_val = sum(a['position_value'] for a in self.accounts_data.values())
        pos_pct = total_pos_val / total_asset * 100 if total_asset > 0 else 0
        
        # 用LLM生成下周操作建议
        portfolio_summary = {
            'total_asset': total_asset,
            'position_pct': pos_pct,
            'position_count': len(self.positions),
            'win_count': len([p for p in self.positions if p.get('pnl_pct', 0) > 0]),
            'avg_pnl_pct': sum(p.get('pnl_pct', 0) for p in self.positions) / len(self.positions) if self.positions else 0
        }
        print("🧠 生成LLM操作建议...")
        llm_suggestion = get_llm_weekly_suggestion(portfolio_summary, vix, vhsi, weekly_pnl_pct)
        
        # LLM风险评估
        from llm_stock_analyzer import get_llm_client
        llm_client = get_llm_client()
        llm_risk = llm_client.get_risk_assessment({
            'pos_pct': pos_pct, 'cash_pct': 100 - pos_pct,
            'vix': vix, 'vhsi': vhsi,
            'total_asset': total_asset, 'positions': self.positions,
            'initial': initial
        })
        
        # 生成报告
        acc_names = {15270902: '🇺🇸 美股', 15270899: '🇭🇰 港股'}
        
        # 构建LLM风险提示文本
        risk_section = "### 1. 风险评估\n\n"
        if llm_risk:
            for line in llm_risk.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 4:
                    level = parts[0].strip()
                    rtype = parts[1].strip()
                    desc = parts[2].strip()
                    action = parts[3].strip()
                    risk_section += f"• {level} **{rtype}风险**：{desc} → {action}\n\n"
                elif len(parts) >= 2:
                    risk_section += f"• {line}\n\n"
        else:
            vix_level = "🔴高" if vix >= 25 else "🟠中" if vix >= 20 else "🟡低"
            risk_section += f"• {vix_level} **系统性风险**：VIX({vix:.1f})/VHSI({vhsi:.1f})\n\n"
            if pos_pct > 60:
                risk_section += f"• 🟠 **集中度风险**：持仓占比{pos_pct:.1f}%偏高\n\n"
        
        report = f"""# 📊 每周交易报告

**报告周期**：{week_start.strftime('%Y-%m-%d')} ~ {week_end.strftime('%Y-%m-%d')}

---

## 📊 一、账户收益明细

| 账户 | 周初资产 | 周末资产 | 本周收益 | 累计收益 | 持仓市值 |
|------|----------|----------|----------|----------|----------|
"""
        
        for acc_id, acc in self.accounts_data.items():
            name = acc_names.get(acc_id, f'账户{acc_id}')
            last_week = self.last_week_assets.get(acc_id, {}).get('total_asset', acc['total_asset'])
            weekly_pnl_a = acc['total_asset'] - last_week
            weekly_pnl_pct_a = (weekly_pnl_a / last_week * 100) if last_week > 0 else 0
            total_pnl_a = acc['total_asset'] - 1000000
            total_pnl_pct_a = (total_pnl_a / 1000000 * 100)
            
            report += f"| {name} | ${last_week:,.0f} | ${acc['total_asset']:,.0f} | {weekly_pnl_pct_a:+.2f}% | {total_pnl_pct_a:+.2f}% | ${acc['position_value']:,.0f} |\n"
        
        report += f"| **合计** | ${last_week_total:,.0f} | ${total_asset:,.0f} | **{weekly_pnl_pct:+.2f}%** | {total_pnl_pct:+.2f}% | ${sum(a['position_value'] for a in self.accounts_data.values()):,.0f} |\n"

        # 策略持仓收益统计
        hk_stats = self.get_strategy_pnl_stats(market='hk')
        us_stats = self.get_strategy_pnl_stats(market='us')
        
        report += """---

## 📋 二、本周策略收益

"""
        
        # 港股统计
        report += "### 🇭🇰 港股策略 " + STRATEGY_POLICY["hk"]["version"] + "\n\n"
        if hk_stats and hk_stats['total'] > 0:
            report += f"""| 指标 | 数值 |
|------|------|
| 持仓数 | {hk_stats['total']}只 |
| 盈利股数 | {hk_stats['wins']}只 |
| 胜率 | {hk_stats['win_rate']:.1f}% |
| 总市值 | ${hk_stats['total_market_val']:,.2f} |
| 总浮盈 | ${hk_stats['total_pnl']:+,.2f} |
| 平均浮盈 | {hk_stats['avg_pnl_pct']:+.2f}% |

"""
        else:
            report += "暂无持仓\n\n"
        
        # 美股统计
        report += "### 🇺🇸 美股策略 " + STRATEGY_POLICY["us"]["version"] + "\n\n"
        if us_stats and us_stats['total'] > 0:
            report += f"""| 指标 | 数值 |
|------|------|
| 持仓数 | {us_stats['total']}只 |
| 盈利股数 | {us_stats['wins']}只 |
| 胜率 | {us_stats['win_rate']:.1f}% |
| 总市值 | ${us_stats['total_market_val']:,.2f} |
| 总浮盈 | ${us_stats['total_pnl']:+,.2f} |
| 平均浮盈 | {us_stats['avg_pnl_pct']:+.2f}% |

"""
            # 显示持仓明细
            if us_stats['positions']:
                report += "**持仓明细：**\n\n"
                report += "| 标的 | 市值 | 浮盈 |\n"
                report += "|------|------|------|\n"
                for p in us_stats['positions'][:10]:
                    sym = p.get('symbol', '')
                    mv = p.get('market_val', 0)
                    pnl_pct = p.get('pnl_pct', 0)
                    report += f"| {sym} | ${mv:,.0f} | {pnl_pct:+.2f}% |\n"
                report += "\n"
        else:
            report += "暂无持仓\n\n"

        # 策略说明
        report += "---\n\n## 📦 三、策略说明\n\n" + format_strategy_policy_markdown()

        # 当前持仓（移到后面）
        report += """---

## 🎯 四、当前持仓明细

| 标的代码 | 持仓数量 | 平均成本 | 当前市值 | 盈亏比例 | 止损线 | 目标价 |
|----------|----------|----------|----------|----------|--------|--------|
"""
        
        symbol_names = {
            'NVDA': '英伟达', 'VRT': 'Vertiv', 'TSLA': '特斯拉',
            'AMD': 'AMD', 'META': 'Meta', 'AAPL': '苹果',
            'MU': '美光', 'ETR': 'Entergy', 'CEG': 'CEG',
            'SNDK': 'SanDisk', 'COP': '康菲石油', 'CIEN': 'Ciena',
            'MO': 'Altria', 'XOM': '埃克森美孚',
            'CRM': 'Salesforce', 'GOOG': '谷歌', 'GEV': 'GE',
            'LRCX': '泛林', 'TTD': 'Trade Desk', 'ADEA': 'ADEA', 'LII': 'LII'
        }
        
        if self.positions:
            for pos in self.positions:
                symbol = pos['symbol']
                cost = pos['cost']
                stop_loss = cost * 0.94
                target = cost * 1.15
                report += f"| {symbol} | {pos['shares']}股 | ${cost:.2f} | ${pos['market_val']:,.2f} | {pos['pnl_pct']:+.2f}% | ${stop_loss:.2f} | ${target:.2f} |\n"
        else:
            report += "| - | 无持仓 | - | - | - | - | - |\n"

        report += f"""

---

## 😊 五、市场情绪

| 指标 | 数值 | 状态 |
|------|------|------|
| VIX恐慌指数 | {vix:.1f} | {'🟢 平静' if vix < 15 else '🟡 正常' if vix < 20 else '🟠 恐慌' if vix < 30 else '🔴 极度恐慌'} |
| VHSI波幅指数 | {vhsi:.1f} | {'🟢 平静' if vhsi < 15 else '🟡 正常' if vhsi < 20 else '🟠 恐慌' if vhsi < 30 else '🔴 极度恐慌'} |

---

## 💡 六、下周操作建议

{llm_suggestion}

---

## ⚠️ 七、风险提示

{risk_section}

---

**报告生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        # 保存报告
        report_path = REPORTS_DIR / f'{date_str}-weekly-report.md'
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✅ 周报已保存: {report_path}")
        
        # 保存本周数据（供下周对比）
        self.save_this_week_data()
        
        # 发送飞书
        self.send_to_feishu(report)
        
        return report_path
    
    def send_to_feishu(self, content):
        """发送到飞书"""
        if not self.feishu_token:
            self.get_feishu_token()
        
        if not self.feishu_token:
            print("❌ 获取飞书token失败")
            return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.feishu_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "chat_id"}
        
        # 截取前4000字符
        content_short = content[:4000] if len(content) > 4000 else content
        
        data = {
            "receive_id": self.feishu_chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content_short})
        }
        
        try:
            res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
            if res.status_code == 200 and res.json().get('code') == 0:
                print("✅ 周报已发送到飞书")
                return True
            else:
                print(f"❌ 发送失败: {res.text}")
        except Exception as e:
            print(f"❌ 发送异常: {e}")
        
        return False


def sync_futu_data():
    """同步富途账户数据"""
    import subprocess
    try:
        print("🔄 同步富途账户数据...")
        result = subprocess.run(
            [str(PYTHON_BIN),
             str(STRATEGY_DIR / 'sync-futu-account.py')],
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


if __name__ == "__main__":
    sync_futu_data()
    report = WeeklyReportV3()
    report.generate_report()
