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
        
        config_path = os.path.join(self.config_dir, 'us-strategy-v1.7.json')
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
        
        # LLM深度分析
        llm_proposals = self.llm_deep_analysis(data)
        if llm_proposals:
            for p in llm_proposals:
                proposals.append({**p, 'id': f"US{len(proposals)+1:03d}", 'category': 'LLM深度分析'})
        
        if not proposals:
            proposals.append({
                'id': 'US001',
                'category': '例行检查',
                'issue': '策略运行正常',
                'suggestion': '继续监控，定期检查技术指标',
                'priority': '低'
            })
        
        return proposals
    
    def llm_deep_analysis(self, data):
        """LLM深度分析 - 通过llm_stock_analyzer统一调用"""
        try:
            from llm_stock_analyzer import get_llm_client
            client = get_llm_client()
            
            config = data.get('config', {})
            opportunities = data.get('opportunities', {})
            
            prompt = f"""你是专业的美股策略分析师。根据以下实时数据给出优化建议。

当前策略配置: RSI范围{config.get('entry_conditions', {}).get('rsi_range', 'N/A')}, 成交量阈值{config.get('entry_conditions', {}).get('volume_threshold', 'N/A')}x
候选机会: {len(opportunities) if isinstance(opportunities, list) else len(opportunities.get('opportunities', []))}个

请分析策略是否有优化空间，如果有给出1-2条建议，每条格式：
问题|建议|优先级

优先级用: 高/中/低
如果策略运行良好无需调整，回复: OK

直接回复，不要其他内容。"""
            
            result = client.call(prompt, max_tokens=200, temperature=0.3)
            if not result or 'OK' in result:
                return []
            
            proposals = []
            for line in result.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 3:
                    proposals.append({
                        'type': 'llm_analysis',
                        'issue': parts[0].strip(),
                        'suggestion': parts[1].strip(),
                        'priority': parts[2].strip()
                    })
            return proposals
        except Exception as e:
            print(f"⚠️ LLM深度分析失败: {e}")
            return []


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
    # 从.api-keys.json读取凭据
    try:
        with open('/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json', 'r') as f:
            keys_feishu = json.load(f).get('feishu', {})
    except:
        keys_feishu = {}
    
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_data = {
        "app_id": keys_feishu.get("appId", "cli_a93b169884f8dcc1"),
        "app_secret": keys_feishu.get("appSecret", "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV")
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
    
    # 周日不交易（weekday=6），但周六凌晨需分析周五数据
    if weekday >= 6:
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
