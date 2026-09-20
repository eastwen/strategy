#!/usr/bin/env python3
"""
月报生成器 - 统一策略版本
统计本月交易数据、收益归因、策略分析
"""

import sys
import json
import requests
import time
from datetime import datetime
from calendar import monthrange

from runtime_config import (
    DATA_DIR, REPORTS_DIR, STRATEGY_DIR, STRATEGY_POLICY,
    format_strategy_policy_compact, format_strategy_policy_markdown, load_api_keys,
)
from futu import OpenQuoteContext

class MonthlyReportV2:
    """月报生成器v2 - 基于v12模板"""

    def __init__(self):
        self.load_config()
        self.account_data = {}
        self.accounts_list = []
        self.positions = []
        self.hk_signals = []
        self.us_signals = []
        self.feishu_token = None
    
    def load_config(self):
        keys = load_api_keys()
        self.finnhub_key = keys['finnhub']['api_key']
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
        """获取账户数据"""
        try:
            with open(str(DATA_DIR / 'trades.json'), 'r') as f:
                data = json.load(f)
            
            if data.get('source') == 'futu_simulate':
                accounts = data.get('accounts', [])
                positions_raw = data.get('positions', [])
                
                self.accounts_list = accounts
                
                # 汇总所有账户
                total_assets = sum(a.get('total_assets', 0) for a in accounts)
                total_cash = sum(a.get('cash', 0) for a in accounts)
                total_position = sum(a.get('market_val', 0) for a in accounts)
                
                self.account_data = {
                    'total_asset': total_assets,
                    'cash': total_cash,
                    'position_value': total_position
                }
                
                # 获取持仓（统一化：保留 acc_id 划分市场归属，避免剥掉前缀后港股/美股混淆）
                self.positions = []
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
    
    def calc_month_pnl(self):
        """本月收益：以上月最后周快照为基准（数据统一化：统一用 weekly-history 快照）"""
        try:
            with open(str(DATA_DIR / 'weekly-history.json'), 'r') as f:
                history = json.load(f)
            keys = sorted(history.keys())
            if len(keys) < 2:
                raise ValueError('历史快照不足')
            last_key = keys[-1]
            prev_key = keys[-2]
            cur = sum(a.get('total_asset', 0) for a in history[last_key].get('accounts', {}).values())
            prev = sum(a.get('total_asset', 0) for a in history[prev_key].get('accounts', {}).values())
            self._prev_key = prev_key
            pnl = cur - prev
            pct = (pnl / prev * 100) if prev > 0 else 0
            return cur, prev, pnl, pct
        except Exception as e:
            print(f"⚠️ 计算本月收益失败: {e}")
            total = self.account_data.get('total_asset', 0)
            self._prev_key = 'N/A'
            return total, 0, 0, 0.0

    def calc_max_drawdown(self):
        """真实最大回撤：基于历史周快照序列计算（%）"""
        try:
            with open(str(DATA_DIR / 'weekly-history.json'), 'r') as f:
                history = json.load(f)
            seq = []
            for k, v in sorted(history.items()):
                t = sum(a.get('total_asset', 0) for a in v.get('accounts', {}).values())
                seq.append((k, t))
            if not seq:
                return 0.0
            peak = seq[0][1]
            maxdd = 0.0
            for _, t in seq:
                if t > peak:
                    peak = t
                dd = (t - peak) / peak * 100 if peak > 0 else 0
                if dd < maxdd:
                    maxdd = dd
            return maxdd
        except Exception as e:
            print(f"⚠️ 计算最大回撤失败: {e}")
            return 0.0

    def fetch_signals(self):
        """获取信号数据"""
        # 港股信号
        try:
            with open(str(DATA_DIR / 'hk-opportunities.json'), 'r') as f:
                data = json.load(f)
                self.hk_signals = data.get('opportunities', [])
        except:
            pass
        
        # 美股信号
        try:
            with open(str(DATA_DIR / 'us-opportunities.json'), 'r') as f:
                data = json.load(f)
                self.us_signals = data.get('opportunities', [])
        except:
            pass
    
    def generate_report(self):
        """生成月报"""
        today = datetime.now()
        year = today.year
        month = today.month
        month_start = datetime(year, month, 1)
        month_end = datetime(year, month, monthrange(year, month)[1])
        date_str = today.strftime("%Y-%m")
        
        # 获取数据
        self.fetch_account_data()
        self.fetch_signals()
        
        # 计算指标
        initial = 2000000.0  # 两账户各100万（累计收益基准）
        total_asset = self.account_data.get('total_asset', initial)
        total_pnl = total_asset - initial       # 累计收益（自建仓）
        total_pnl_pct = (total_pnl / initial) * 100 if initial > 0 else 0
        position_pct = (self.account_data.get('position_value', 0) / total_asset * 100) if total_asset > 0 else 0
        cash_pct = (self.account_data.get('cash', 0) / total_asset * 100) if total_asset > 0 else 0

        # 本月收益：以上月最后快照为基准（数据统一化：统一用 weekly-history 快照序列）
        month_asset, month_start_val, month_pnl, month_pnl_pct = self.calc_month_pnl()
        # 真实最大回撤：基于历史周快照序列计算
        max_drawdown = self.calc_max_drawdown()

        # 统计机会（数据统一化：统一用 final_score 作候选口径，阈值取策略 min_score）
        hk_min = STRATEGY_POLICY["hk"]["min_score"]
        us_min = STRATEGY_POLICY["us"]["min_score"]
        hk_high = [s for s in self.hk_signals if (s.get('final_score') or s.get('score') or 0) >= hk_min]
        us_high = [s for s in self.us_signals if (s.get('final_score') or s.get('score') or 0) >= us_min]
        
        # LLM分析
        import sys
        sys.path.insert(0, str(STRATEGY_DIR))
        from llm_stock_analyzer import get_llm_client
        llm_client = get_llm_client()
        
        llm_risk = llm_client.get_risk_assessment({
            'pos_pct': position_pct, 'cash_pct': cash_pct,
            'total_asset': total_asset,
            'positions': [{'symbol': p['symbol'], 'pnl_pct': p.get('pnl_pct', 0)} for p in self.positions],
            'initial': initial
        })
        
        risk_section = ""
        if llm_risk:
            for line in llm_risk.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 4:
                    level_ = parts[0].strip()
                    rtype_ = parts[1].strip()
                    desc_ = parts[2].strip()
                    act_ = parts[3].strip()
                    risk_section += f"• {level_} **{rtype_}**: {desc_} → {act_}\n\n"
        if not risk_section:
            risk_section = "• ⚠️ 持续监控VIX/VHSI波动\n\n• ⚠️ 严格执行止损纪律\n\n"
        
        # LLM下月策略建议
        llm_strategy = llm_client.call(
            "你是专业投资顾问。根据以下月度数据给出下月3条策略建议。\n"
            f"本月收益率: {total_pnl_pct:+.2f}%\n持仓占比: {position_pct:.1f}%\n现金占比: {cash_pct:.1f}%\n"
            f"当前必须遵守的策略规则：\n{format_strategy_policy_compact()}\n"
            "每条格式: 建议类型|具体建议。直接回复3行。",
            max_tokens=200, temperature=0.3
        )
        strategy_section = ""
        if llm_strategy:
            for line in llm_strategy.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|', 1)
                if len(parts) >= 2:
                    strategy_section += f"• 📌 **{parts[0].strip()}**: {parts[1].strip()}\n\n"
        if not strategy_section:
            strategy_section = "• 📌 维持当前策略，关注信号质量\n\n" 
        
        # 生成报告
        report = f"""# 📊 每月交易报告

**报告周期**：{month_start.strftime('%Y-%m-%d')} ~ {month_end.strftime('%Y-%m-%d')}

---

## 📊 一、本月收益概览

| 指标 | 数值 | 备注 |
|------|------|------|
| 初始资金 | $2,000,000.00 | 模拟盘初始本金（两账户） |
| 月末总资产 | ${total_asset:,.2f} | - |
| 本月收益 | ${month_pnl:,.2f} | 较上月快照(2026-{self._prev_key}) |
| 本月收益率 | {month_pnl_pct:+.2f}% | - |
| 累计收益 | ${total_pnl:,.2f} | 自建仓累计 {total_pnl_pct:+.2f}% |
| 最大回撤 | {max_drawdown:.2f}% | 历史周快照回调 |
| 持仓市值 | ${self.account_data.get('position_value', 0):,.2f} | 占比{position_pct:.1f}% |
| 可用资金 | ${self.account_data.get('cash', 0):,.2f} | 占比{cash_pct:.1f}% |

---

## 📦 二、账户明细

"""
        for acc in self.accounts_list:
            acc_id = acc.get('acc_id', 'N/A')
            acc_total = acc.get('total_assets', 0)
            acc_cash = acc.get('cash', 0)
            acc_mv = acc.get('market_val', 0)
            acc_pnl = acc_total - 1000000
            acc_pnl_pct = (acc_pnl / 1000000) * 100
            status = "有持仓" if acc_mv > 0 else "空仓"
            report += f"""**账户 {acc_id}** ({status})
| 指标 | 数值 |
|------|------|
| 总资产 | ${acc_total:,.2f} |
| 现金 | ${acc_cash:,.2f} |
| 持仓市值 | ${acc_mv:,.2f} |
| 收益率 | {acc_pnl_pct:+.2f}% |

"""

        report += """---

## 📦 三、月末持仓明细

| 标的代码 | 市场 | 持仓数量 | 平均成本 | 当前市值 | 盈亏比例 | 止损线 | 目标价 |
|----------|------|----------|----------|----------|----------|--------|--------|
"""
        
        symbol_names = {
            'NVDA': '英伟达', 'VRT': 'Vertiv', 'TSLA': '特斯拉',
            'AMD': 'AMD', 'META': 'Meta', 'AAPL': '苹果',
            '09868': '小鹏汽车', '09866': '蔚来', '02333': '比亚迪'
        }
        
        if self.positions:
            hk_note = "港"
            us_note = "美"
            for pos in self.positions:
                symbol = pos['symbol']
                name = symbol_names.get(symbol, symbol)
                cost = pos['cost']
                stop_loss = cost * 0.94
                target = cost * 1.15
                market_tag = us_note if pos.get('acc_id') == 15270898 else hk_note
                report += f"| {symbol} | {market_tag} | {pos['shares']}股 | ${cost:.2f} | ${pos['market_val']:,.2f} | {pos['pnl_pct']:+.2f}% | ${stop_loss:.2f} | ${target:.2f} |\n"
        else:
            report += "| - | 无持仓 | - | - | - | - | - |\n"

        report += "\n---\n\n## 🎯 四、当前策略说明\n\n" + format_strategy_policy_markdown()
        report += "---\n\n## 🔍 五、本月扫描统计\n\n"
        report += "### 🇭🇰 港股高评分机会（≥{}分）\n\n".format(STRATEGY_POLICY["hk"]["min_score"])
        report += "| 标的 | 行业 | 价格 | 评分 |\n|------|------|------|------|\n"

        if hk_high:
            for s in hk_high[:10]:
                sc = s.get('final_score') or s.get('score') or s.get('base_score') or 0
                report += f"| {s.get('symbol', 'N/A')} | {s.get('sector', 'N/A')} | HK${s.get('price', 0):.2f} | {sc}分 |\n"
        else:
            report += "| - | 无 | - | - |\n"

        report += """
### 🇺🇸 美股高评分机会（≥{}分）".format(STRATEGY_POLICY["us"]["min_score"])

| 标的 | 价格 | 评分 |
|------|------|------|
"""
        
        if us_high:
            for s in us_high[:10]:
                sc = s.get('final_score') or s.get('score') or 0
                report += f"| {s.get('symbol', 'N/A')} | ${s.get('price', 0):.2f} | {sc}分 |\n"
        else:
            report += "| - | 无 |\n"

        report += f"""
---

## 💡 六、下月策略调整建议

{strategy_section}
### 风险控制
{format_strategy_policy_compact()}

---

## ⚠️ 七、风险提示

{risk_section}

---

**报告生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        # 保存报告
        report_path = REPORTS_DIR / f'{date_str}-monthly-report.md'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✅ 月报已保存: {report_path}")
        
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
                print("✅ 月报已发送到飞书")
                return True
            else:
                print(f"❌ 发送失败: {res.text}")
        except Exception as e:
            print(f"❌ 发送异常: {e}")
        
        return False

if __name__ == "__main__":
    report = MonthlyReportV2()
    report.generate_report()
