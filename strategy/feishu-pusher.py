#!/usr/bin/env python3
"""
飞书消息推送模块
主动发送消息给用户
"""

import requests
import json
import time
import os

class FeishuPusher:
    """飞书推送器"""
    
    def __init__(self):
        self.app_id = "cli_a93b169884f8dcc1"
        self.app_secret = self._load_app_secret()
        self.open_id = "ou_571e965fc81a2e887609a06ed6103d66"
        self.chat_id = self._load_chat_id()  # 群聊ID
        self.base_url = "https://open.feishu.cn/open-apis"
        self.tenant_access_token = None
        self.token_expire_time = 0
    
    def _load_chat_id(self):
        """从配置文件加载群聊ID"""
        config_path = '/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json'
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    if 'feishu' in config:
                        return config['feishu'].get('chatId')
            except:
                pass
        return None
    
    def _load_app_secret(self):
        """从配置文件加载 App Secret"""
        config_path = '/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json'
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    if 'feishu' in config:
                        return config['feishu'].get('appSecret')
            except:
                pass
        return None
        
    def set_app_secret(self, secret):
        """设置App Secret"""
        self.app_secret = secret
        
    def get_tenant_access_token(self):
        """获取 tenant_access_token"""
        if not self.app_secret:
            print("❌ 未配置 App Secret")
            return None
            
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal/"
        
        try:
            res = requests.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    self.tenant_access_token = data.get('tenant_access_token')
                    self.token_expire_time = time.time() + data.get('expire', 7200) - 300
                    return self.tenant_access_token
                else:
                    print(f"❌ 获取token失败: {data.get('msg')}")
            else:
                print(f"❌ 请求失败: {res.status_code}")
        except Exception as e:
            print(f"❌ 异常: {e}")
            
        return None
    
    def send_message(self, content, msg_type="text"):
        """发送消息"""
        # 检查token
        if not self.tenant_access_token or time.time() > self.token_expire_time:
            if not self.get_tenant_access_token():
                return False
        
        url = f"{self.base_url}/im/v1/messages"
        
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json"
        }
        
        # 优先使用群聊ID，否则使用用户ID
        if self.chat_id:
            params = {"receive_id_type": "chat_id"}
            receive_id = self.chat_id
        else:
            params = {"receive_id_type": "open_id"}
            receive_id = self.open_id
        
        data = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": json.dumps({"text": content}) if msg_type == "text" else content
        }
        
        try:
            res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
            
            if res.status_code == 200:
                result = res.json()
                if result.get('code') == 0:
                    print(f"✅ 消息发送成功")
                    return True
                else:
                    print(f"❌ 发送失败: {result.get('msg')}")
            else:
                print(f"❌ 请求失败: {res.status_code}")
        except Exception as e:
            print(f"❌ 异常: {e}")
            
        return False
    
    def send_alert(self, title, message):
        """发送警报消息"""
        content = f"⚠️ {title}\n\n{message}\n\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        return self.send_message(content)
    
    def send_trade_notification(self, action, symbol, price, reason):
        """发送交易通知"""
        emoji = "🟢" if action == "BUY" else "🔴"
        content = f"""{emoji} 交易执行通知

动作: {action}
股票: {symbol}
价格: ${price}
原因: {reason}

时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        return self.send_message(content)
    
    def send_daily_report(self, report_content):
        """发送日报"""
        # 截取前4000字符（飞书限制）
        if len(report_content) > 4000:
            report_content = report_content[:4000] + "\n\n... (内容过长，已截断)"
        
        return self.send_message(report_content)


# 测试
if __name__ == '__main__':
    print("=" * 60)
    print("飞书推送模块测试")
    print("=" * 60)
    print(f"App ID: cli_a93b169884f8dcc1")
    print(f"Open ID: ou_571e965fc81a2e887609a06ed6103d66")
    print()
    print("⚠️ 需要 App Secret 才能发送消息")
    print("请在飞书开放平台获取 App Secret 并配置")
