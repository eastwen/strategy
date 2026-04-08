#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
美股策略自我优化系统 v2.0
深度分析：持仓、市场环境、VIX、ATR止损
"""

import sys
import json
import os
import requests
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock')
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')

class USOptimizer:
    """美股策略自我优化系统 v2.0"""
    
    def __init__(self):
        self.data_dir = '/home/admin/.openclaw/workspace-stock/data'
        self.reports_dir = '/home/admin/.openclaw/workspace-stock/daily-reports'
        self.config_dir = '/home/admin/.openclaw/workspace-stock/config'
        
    def get_data(self):
        data = {}
        
        config_path = os.path.join(self.config_dir, 'us-strategy-v1.6.json')
        try:
            with open(config_path, 'r') as f:
                data['config'] = json.load(f)
        except:
            pass
        
        trades_path = os.path.join(self.data_dir, 'trades.json')
        try:
            with open(trades_path, 'r') as f:
                data['trades'] = json.load(f)
        except:
            pass
        
        return data
    
    def analyze_positions(self, data):
        """分析持仓"""
        analysis = {'losing': [], 'winning': [], 'suggestions': []}
        
        positions = data.get('positions', [])
        for pos in positions:
            pl = pos.get('pl_ratio', 0) * 100
            info = {'symbol': pos.get('symbol'), 'pl_pct': pl}
            if pl < -1:
                analysis['losing'].append(info)
            elif pl > 2:
                analysis['winning'].append(info)
        
        if analysis['losing']:
            ratio = len(analysis['losing']) / len(positions) if positions else 0
            if ratio > 0.5:
                analysis['suggestions'].append({
                    'type': 'position',
                    'issue': f'{len(analysis["losing"])}/{len(positions)}只亏损，比例偏高',
                    'suggestion': '检查选股条件是否过于宽松',
                    'priority': '高'
                })
        
        return analysis
    
    def analyze_vix(self, data):
        """分析VIX"""
        analysis = {'vix': None, 'level': 'unknown', 'suggestions': []}
        
        try:
            from vix_fetcher import get_vix_index
            vix = get_vix_index()
            if vix:
                analysis['vix'] = vix
                if vix > 30:
                    analysis['level'] = '高波动'
                    analysis['suggestions'].append({
                        'type': 'vix',
                        'issue': f'VIX={vix:.1f}，市场恐慌',
                        'suggestion': '提高入场门槛到85分，收紧ATR止损到1.5x',
                        'priority': '高'
                    })
                elif vix < 15:
                    analysis['level'] = '低波动'
                    analysis['suggestions'].append({
                        'type': 'vix',
                        'issue': f'VIX={vix:.1f}，市场平静',
                        'suggestion': '可以放宽条件，提高仓位到15%',
                        'priority': '低'
                    })
        except Exception as e:
            print(f"⚠️ VIX获取失败: {e}")
        
        return analysis
    
    def generate_proposals(self, data):
        proposals = []
        
        for s in self.analyze_positions(data)['suggestions']:
            proposals.append({**s, 'id': f"US{len(proposals)+1:03d}", 'category': '持仓分析'})
        
        for s in self.analyze_vix(data)['suggestions']:
            proposals.append({**s, 'id': f"US{len(proposals)+1:03d}", 'category': '市场环境'})
        
        if not proposals:
            proposals.append({
                'id': 'US001',
                'category': '例行检查',
                'issue': '策略运行正常',
                'suggestion': '继续监控，定期检查技术指标',
                'priority': '低'
            })
        
        return proposals
    
    def print_proposals(self, proposals):
        print("\n" + "="*60)
        print("📊 美股策略优化方案 v2.0")
        print("="*60)
        print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        
        for p in proposals:
            icon = '🔴' if p['priority'] == '高' else '🟡' if p['priority'] == '中' else '🟢'
            print(f"方案 {p['id']} [{p['priority']}优先级] {icon}")
            print(f"- 类别: {p['category']}")
            print(f"- 问题: {p['issue']}")
            print(f"- 建议: {p['suggestion']}\n")
        
        print("="*60)
        return proposals

def send_to_feishu_chat(message, chat_id="oc_f6c5168cb212e624d21ccfabed49b083"):
    """发送消息到飞书群聊"""
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_data = {
        "app_id": "cli_a93b169884f8dcc1",
        "app_secret": "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV"
    }
    
    try:
        resp = requests.post(token_url, json=token_data, timeout=10)
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
        
        resp = requests.post(msg_url, headers=headers, json=msg_data, params=params, timeout=10)
        if resp.status_code == 200:
            print("✅ 已发送到飞书群聊")
            return True
        else:
            print(f"❌ 发送失败: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        return False

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


def main():
    # 检查美股休市日
    if is_us_holiday():
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"⏭️ 今天是美股休市日（{today}），跳过优化")
        return
    
    print("🧠 美股策略自我优化系统 v2.0\n")
    
    opt = USOptimizer()
    data = opt.get_data()
    proposals = opt.generate_proposals(data)
    opt.print_proposals(proposals)
    
    path = os.path.join(opt.data_dir, 'us-optimization-proposal.json')
    with open(path, 'w') as f:
        json.dump({'timestamp': datetime.now().isoformat(), 'proposals': proposals}, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {path}")
    
    # 发送到飞书群聊
    print("📤 发送到飞书群聊...")
    msg = f"🧠 *美股策略优化方案*\n\n"
    msg += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    for p in proposals:
        icon = '🔴' if p['priority'] == '高' else '🟡' if p['priority'] == '中' else '🟢'
        msg += f"{icon} **{p['id']}** [{p['priority']}优先级]\n"
        msg += f"类别: {p['category']}\n"
        msg += f"问题: {p['issue']}\n"
        msg += f"建议: {p['suggestion']}\n\n"
    msg += "请回复 `同意 001` / `同意 002` 等来应用方案"
    send_to_feishu_chat(msg)

if __name__ == '__main__':
    main()
