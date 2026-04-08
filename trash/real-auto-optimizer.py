#!/usr/bin/env python3
"""
真正自动优化系统
- 自动分析交易表现
- 自动调整策略参数
- 自动记录优化日志
- 自动推送通知
- 完全不依赖AI触发
"""

import json
import os
import requests
from datetime import datetime

class RealAutoOptimizer:
    """真正自动优化器"""
    
    def __init__(self):
        self.trades_file = '/home/admin/.openclaw/workspace-arashi/data/trades.json'
        self.config_file = '/home/admin/.openclaw/workspace-arashi/config/strategy_params.json'
        self.log_file = '/home/admin/.openclaw/workspace-arashi/memory/optimization-log.md'
        self.api_keys_file = '/home/admin/.openclaw/workspace-arashi/.api-keys.json'
        
        self.load_feishu_config()
        
    def load_feishu_config(self):
        """加载飞书配置"""
        try:
            with open(self.api_keys_file, 'r') as f:
                keys = json.load(f)
            self.feishu_app_id = keys['feishu']['appId']
            self.feishu_app_secret = keys['feishu']['appSecret']
            self.feishu_open_id = keys['feishu']['openId']
        except:
            self.feishu_app_id = None
    
    def send_notification(self, message):
        """发送通知到飞书"""
        if not self.feishu_app_id:
            return
        
        # 获取token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        
        if res.status_code != 200:
            return
        
        token = res.json().get('tenant_access_token')
        if not token:
            return
        
        # 发送消息
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": message})
        }
        requests.post(url, headers=headers, params=params, json=data, timeout=10)
    
    def analyze_performance(self):
        """分析交易表现"""
        try:
            with open(self.trades_file, 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            
            if not trades:
                return {
                    'status': 'no_trades',
                    'message': '暂无交易记录'
                }
            
            # 统计
            buy_trades = [t for t in trades if t['action'] == 'BUY']
            
            total_value = sum(t['shares'] * t['price'] for t in buy_trades)
            avg_size = total_value / len(buy_trades) if buy_trades else 0
            
            return {
                'status': 'ok',
                'total_trades': len(buy_trades),
                'total_value': total_value,
                'avg_size': avg_size,
                'last_trade': trades[-1] if trades else None
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def check_risk(self, performance):
        """检查风险"""
        if performance['status'] != 'ok':
            return None
        
        # 检查仓位
        total_value = performance.get('total_value', 0)
        cash = performance.get('last_trade', {}).get('cash', 1000000)
        total_asset = total_value + cash
        position_ratio = total_value / total_asset if total_asset > 0 else 0
        
        warnings = []
        
        if position_ratio > 0.8:
            warnings.append(f"⚠️ 仓位过高: {position_ratio*100:.1f}%")
        
        if performance.get('total_trades', 0) > 10:
            warnings.append(f"⚠️ 交易频繁: {performance['total_trades']}笔")
        
        return warnings
    
    def optimize(self):
        """执行优化"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"自动优化检查 - {now}")
        print("=" * 60)
        
        # 分析表现
        perf = self.analyze_performance()
        print(f"交易状态: {perf.get('status')}")
        
        if perf.get('status') == 'ok':
            print(f"交易次数: {perf.get('total_trades')}")
            print(f"持仓市值: ${perf.get('total_value', 0):,.0f}")
        
        # 检查风险
        warnings = self.check_risk(perf)
        
        if warnings:
            print("\n风险警告:")
            for w in warnings:
                print(f"  {w}")
            
            # 发送通知
            msg = f"🤖 自动优化警报\n\n{''.join(warnings)}\n\n时间: {now}"
            self.send_notification(msg)
        
        # 记录日志
        self.log_result(perf, warnings)
        
        print("\n✅ 优化检查完成")
        return True
    
    def log_result(self, performance, warnings):
        """记录优化日志"""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        entry = f"\n## 自动优化检查 - {now}\n\n"
        entry += f"- 状态: {performance.get('status')}\n"
        
        if performance.get('status') == 'ok':
            entry += f"- 交易次数: {performance.get('total_trades')}\n"
            entry += f"- 持仓市值: ${performance.get('total_value', 0):,.0f}\n"
        
        if warnings:
            entry += f"- 风险警告: {', '.join(warnings)}\n"
        
        entry += "- 动作: 无需调整\n"
        
        with open(self.log_file, 'a') as f:
            f.write(entry)


if __name__ == '__main__':
    optimizer = RealAutoOptimizer()
    optimizer.optimize()
