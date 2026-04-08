#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
港股策略自我优化系统 v2.0
深度分析：市场情绪、信号质量、策略参数
"""

import sys
import json
import os
import requests
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')

class HKOptimizer:
    """港股策略自我优化系统 v2.0"""
    
    def __init__(self):
        self.data_dir = '/home/admin/.openclaw/workspace-stock/data'
        self.reports_dir = '/home/admin/.openclaw/workspace-stock/daily-reports'
        self.config_dir = '/home/admin/.openclaw/workspace-stock/config'
        
    def get_data(self):
        """获取所需数据"""
        data = {}
        
        config_path = os.path.join(self.config_dir, 'hk-strategy-dynamic-v2.0.json')
        try:
            with open(config_path, 'r') as f:
                data['config'] = json.load(f)
        except:
            pass
        
        hk_opp_path = os.path.join(self.data_dir, 'hk-opportunities.json')
        try:
            with open(hk_opp_path, 'r') as f:
                data['opportunities'] = json.load(f)
        except:
            pass
        
        return data
    
    def analyze_market_sentiment(self, data):
        """分析港股市场情绪"""
        analysis = {'vhsi': None, 'level': 'unknown', 'suggestions': []}
        
        try:
            from hk_market_sentiment import HKMarketSentiment
            sentiment = HKMarketSentiment()
            result = sentiment.get_market_sentiment()
            if result and result.get('vhsi'):
                vhsi = result['vhsi']
                analysis['vhsi'] = vhsi
                
                if vhsi >= 30:
                    analysis['level'] = '极度恐慌'
                    analysis['suggestions'].append({
                        'type': 'sentiment',
                        'issue': f'VHSI={vhsi:.1f}，市场极度恐慌',
                        'suggestion': '大幅提高入场门槛(≥80分)，仅选择最强信号，减少仓位',
                        'priority': '高'
                    })
                elif vhsi >= 25:
                    analysis['level'] = '恐慌'
                    analysis['suggestions'].append({
                        'type': 'sentiment',
                        'issue': f'VHSI={vhsi:.1f}，市场恐慌',
                        'suggestion': '提高入场门槛到75分，收紧止损条件',
                        'priority': '中'
                    })
                elif vhsi >= 18:
                    analysis['level'] = '正常'
                else:
                    analysis['level'] = '平静'
                    analysis['suggestions'].append({
                        'type': 'sentiment',
                        'issue': f'VHSI={vhsi:.1f}，市场平静',
                        'suggestion': '可以适当放宽条件，提高仓位到5%',
                        'priority': '低'
                    })
        except Exception as e:
            print(f"⚠️ VHSI获取失败: {e}")
        
        return analysis
    
    def analyze_scan_results(self, data):
        """分析港股扫描结果"""
        analysis = {'total': 0, 'valid': 0, 'avg_change': 0, 'suggestions': []}
        
        opps = data.get('opportunities', {}).get('opportunities', [])
        if not opps:
            analysis['suggestions'].append({
                'type': 'signal',
                'issue': '今日无股票达到入选标准',
                'suggestion': '检查策略参数或市场环境',
                'priority': '高'
            })
            return analysis
        
        analysis['total'] = len(opps)
        analysis['valid'] = len([o for o in opps if o.get('base_score', 0) >= 70])
        changes = [o.get('change_pct', 0) for o in opps]
        analysis['avg_change'] = sum(changes) / len(changes) if changes else 0
        
        if analysis['valid'] == 0:
            analysis['suggestions'].append({
                'type': 'signal',
                'issue': f'扫描{len(opps)}只股票，但无入选信号',
                'suggestion': '【核心问题】当前策略只在上涨市场有效，建议增加跌市反弹策略',
                'priority': '高'
            })
        
        return analysis
    
    def analyze_params(self, data):
        """分析策略参数"""
        analysis = {'suggestions': []}
        
        config = data.get('config', {})
        entry = config.get('entry_conditions', {})
        
        rsi_range = entry.get('rsi_range', '35-70')
        if isinstance(rsi_range, str) and '-' in rsi_range:
            parts = rsi_range.split('-')
            rsi_low, rsi_high = int(parts[0]), int(parts[1])
            
            if rsi_low < 35:
                analysis['suggestions'].append({
                    'type': 'param',
                    'issue': f'RSI下限({rsi_low})可能偏低',
                    'suggestion': '建议提高到40，避免超卖陷阱；或降低到30捕捉超跌反弹',
                    'priority': '中'
                })
            
            if rsi_high > 70:
                analysis['suggestions'].append({
                    'type': 'param',
                    'issue': f'RSI上限({rsi_high})可能偏高',
                    'suggestion': '建议降低到65，避免追高',
                    'priority': '中'
                })
        
        return analysis
    
    def generate_proposals(self, data):
        """生成优化方案"""
        proposals = []
        
        # 市场情绪
        for s in self.analyze_market_sentiment(data)['suggestions']:
            proposals.append({**s, 'id': f"HK{len(proposals)+1:03d}", 'category': '市场情绪'})
        
        # 扫描结果
        for s in self.analyze_scan_results(data)['suggestions']:
            proposals.append({**s, 'id': f"HK{len(proposals)+1:03d}", 'category': '信号分析'})
        
        # 策略参数
        for s in self.analyze_params(data)['suggestions']:
            proposals.append({**s, 'id': f"HK{len(proposals)+1:03d}", 'category': '参数优化'})
        
        if not proposals:
            proposals.append({
                'id': 'HK001',
                'category': '例行检查',
                'issue': '策略运行正常',
                'suggestion': '继续监控市场，定期检查策略表现',
                'priority': '低'
            })
        
        return proposals
    
    def print_proposals(self, proposals):
        print("\n" + "="*60)
        print("📊 港股策略优化方案 v2.0")
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

def is_hk_holiday():
    """检查今天是否是港股休市日（香港公众假期）"""
    from datetime import date
    
    # 香港2026年公众假期
    hk_holidays_2026 = [
        '2026-01-01', '2026-01-29', '2026-01-30', '2026-01-31',
        '2026-02-01', '2026-02-02', '2026-04-03', '2026-04-04',
        '2026-04-05', '2026-04-06', '2026-04-07',  # 清明节+复活节假期
        '2026-05-01', '2026-05-03', '2026-07-01',
        '2026-09-30', '2026-10-01', '2026-10-07', '2026-12-25',
        '2026-12-26',
    ]
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    return today_str in hk_holidays_2026


def main():
    # 检查港股休市日
    if is_hk_holiday():
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"⏭️ 今天是港股休市日（{today}），跳过优化")
        return
    
    print("🧠 港股策略自我优化系统 v2.0\n")
    
    opt = HKOptimizer()
    data = opt.get_data()
    proposals = opt.generate_proposals(data)
    opt.print_proposals(proposals)
    
    path = os.path.join(opt.data_dir, 'hk-optimization-proposal.json')
    with open(path, 'w') as f:
        json.dump({'timestamp': datetime.now().isoformat(), 'proposals': proposals}, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存: {path}")
    
    # 发送到飞书群聊
    print("📤 发送到飞书群聊...")
    msg = f"🧠 *港股策略优化方案*\n\n"
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
