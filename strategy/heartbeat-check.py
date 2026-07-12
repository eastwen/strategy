#!/usr/bin/env python3
"""
策略心跳检查脚本 v1.0
整合数据检查功能，可输出到日志或飞书
"""

import os
import sys
import json
import datetime
import requests

from runtime_config import DATA_DIR, FUTU_OPEND_BIN, load_api_keys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_pending_reports():
    """检查待发日报"""
    pending_dir = DATA_DIR / 'pending-reports'
    if os.path.exists(pending_dir):
        count = len([f for f in os.listdir(pending_dir) 
                    if os.path.isfile(os.path.join(pending_dir, f))])
        return count
    return 0

def check_opportunities():
    """检查交易机会"""
    try:
        opportunities_path = DATA_DIR / 'us-opportunities.json'
        with open(opportunities_path, 'r') as f:
            data = json.load(f)
        
        high_score = [o for o in data.get('opportunities', []) 
                     if o.get('news_adjusted_score', o.get('score', 0)) >= 70]
        
        if high_score:
            top3 = sorted(high_score, 
                         key=lambda x: x.get('news_adjusted_score', x.get('score', 0)), 
                         reverse=True)[:3]
            return len(high_score), top3
        return 0, []
    except Exception as e:
        return 0, []

def check_trades():
    """检查交易状态"""
    try:
        trades_path = DATA_DIR / 'trades.json'
        with open(trades_path, 'r') as f:
            data = json.load(f)
        
        accounts = len(data.get('accounts', []))
        positions = len(data.get('positions', []))
        trades = len(data.get('trades', []))
        sync_time = data.get('sync_time', '未知')
        
        return accounts, positions, trades, sync_time
    except Exception as e:
        return 0, 0, 0, '错误'

def check_alerts():
    """检查警报数据时效性"""
    try:
        alerts_path = DATA_DIR / 'alerts.json'
        with open(alerts_path, 'r') as f:
            data = json.load(f)
        
        if 'time' in data:
            alert_time = data['time'][:19]  # 取到秒
            alert_dt = datetime.datetime.strptime(alert_time, "%Y-%m-%dT%H:%M:%S")
            now_dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            hours_diff = (now_dt - alert_dt).total_seconds() / 3600
            return hours_diff
        return 999  # 表示数据异常
    except Exception as e:
        return 999

def check_llm_api():
    """检查 LLM API 是否可用。挂了返回 (False, 错误消息)。"""
    try:
        from llm_stock_analyzer import LLMClient
        client = LLMClient()
        if not client.api_key or client.api_key.startswith('sk-xxx'):
            return False, f"LLM API Key 未配置 (model={client.model})"
        result = client.call('ping', max_tokens=5, temperature=0)
        if result is None:
            return False, f"LLM 调用返回 None (model={client.model}/{client.fallback_model})"
        return True, f"LLM OK (model={client.model})"
    except Exception as e:
        return False, f"LLM 检查异常: {e}"


def check_futu_opend():
    """检查 Futu OpenD 是否运行，如果没运行则重启"""
    import subprocess
    import time
    
    # 检查进程是否在运行
    result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    if 'FutuOpenD' in result.stdout:
        return True, "运行中"
    
    # 如果没运行，尝试重启
    print("⚠️ Futu OpenD 未运行，尝试重启...")
    
    try:
        # 启动 Futu OpenD
        subprocess.Popen(
            [str(FUTU_OPEND_BIN), str(FUTU_OPEND_BIN.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        
        # 再次检查
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'FutuOpenD' in result.stdout:
            return True, "已重启"
        else:
            return False, "重启失败"
    except Exception as e:
        return False, f"重启失败: {e}"

def send_to_feishu(message):
    """发送消息到飞书"""
    try:
        # 获取 token
        token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        feishu = load_api_keys().get('feishu', {})
        token_data = {
            "app_id": feishu.get('appId', ''),
            "app_secret": feishu.get('appSecret', ''),
        }
        
        resp = requests.post(token_url, json=token_data, timeout=10)
        token = resp.json().get('tenant_access_token', '')
        
        if not token:
            print(f"[飞书通知失败] 获取token失败")
            return False
        
        # 发送消息到群聊
        msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        msg_data = {
            "receive_id": feishu.get("chatId", ""),
            "msg_type": "text",
            "content": json.dumps({"text": message})
        }
        
        resp = requests.post(msg_url, headers=headers, json=msg_data, timeout=10)
        if resp.status_code == 200:
            print(f"[飞书通知] {message}")
            return True
        else:
            print(f"[飞书通知失败] {resp.status_code}")
            return False
    except Exception as e:
        print(f"[飞书通知异常] {e}")
        return False

def main():
    """主函数"""
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 0. 检查 Futu OpenD
    futu_ok, futu_msg = check_futu_opend()
    
    # 0.5 检查 LLM API（挂了自动下单会被限住，必报）
    llm_ok, llm_msg = check_llm_api()
    
    # 1. 检查待发日报
    pending_reports = check_pending_reports()
    
    # 2. 检查交易机会
    opp_count, top_opps = check_opportunities()
    
    # 3. 检查交易状态
    accounts, positions, trades, sync_time = check_trades()
    
    # 4. 检查警报时效性
    alert_age = check_alerts()
    
    # 总结问题（去重）
    issues = []
    if not futu_ok:
        issues.append(f"Futu OpenD: {futu_msg}")
    if not llm_ok:
        issues.append(f"⚠️ LLM API 不可用 → 自动开仓已阻断 ({llm_msg})")
    if pending_reports > 0:
        issues.append(f"{pending_reports}个日报待发")
    if alert_age > 24:
        issues.append(f"警报数据过期({alert_age:.0f}小时前)")
    
    # 去重
    issues = list(dict.fromkeys(issues))
    
    # 高评分机会检查（只记录，不作为问题）
    high_score_opportunities = []
    if opp_count >= 5:  # 如果有5个以上高评分机会
        high_score_opportunities = top_opps[:3]
    
    # 只在有问题或特殊情况下输出日志
    if issues or opp_count >= 8:  # 有问题或机会特别多
        print(f"🔍 策略心跳检查 - {current_time}")
        print("=" * 50)
        
        # Futu OpenD 状态
        if futu_ok:
            print(f"✅ Futu OpenD: {futu_msg}")
        else:
            print(f"🚨 Futu OpenD: {futu_msg}")
        
        if llm_ok:
            print(f"✅ {llm_msg}")
        else:
            print(f"🚨 {llm_msg}")
        
        if pending_reports > 0:
            print(f"🚨 有 {pending_reports} 个日报待发")
        
        if opp_count > 0:
            print(f"📈 高评分机会: {opp_count} 个")
            for opp in top_opps[:3]:
                symbol = opp.get('symbol', '未知')
                score = opp.get('news_adjusted_score', opp.get('score', 0))
                print(f"   ⭐ {symbol}: {score}分")
        
        print(f"💼 账户: {accounts}, 持仓: {positions}, 交易: {trades}")
        print(f"🔄 上次同步: {sync_time}")
        
        if alert_age < 24:
            print(f"📢 警报数据: {alert_age:.1f}小时前")
        elif alert_age < 999:
            print(f"🚨 警报数据已过期: {alert_age:.1f}小时前")
        else:
            print("⚠️  警报数据检查失败")
        
        print("=" * 50)
        
        if issues:
            summary = f"🚨 发现问题: {', '.join(issues)}"
            print(summary)
            # 如果有问题，发送到飞书
            send_to_feishu(summary)
            return 1
        else:
            print(f"✅ 一切正常 (高评分机会: {opp_count}个)")
            return 0
    else:
        # 正常状态，静默运行，只返回状态码
        return 0 if not issues else 1

if __name__ == "__main__":
    sys.exit(main())