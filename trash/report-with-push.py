#!/usr/bin/env python3
"""
日报生成器 + 飞书推送
生成后立即发送，不需要等待心跳
"""

import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class DailyReportWithPush:
    """日报生成器（带飞书推送）"""
    
    def __init__(self):
        self.load_config()
        
    def load_config(self):
        """加载配置"""
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu']['openId']
        self.feishu_token = None
        
    def get_feishu_token(self):
        """获取飞书token"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data.get('code') == 0:
                self.feishu_token = data.get('tenant_access_token')
                return True
        return False
    
    def send_to_feishu(self, content):
        """发送到飞书"""
        if not self.feishu_token:
            if not self.get_feishu_token():
                print("❌ 获取飞书token失败")
                return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.feishu_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": content})
        }
        
        res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        
        if res.status_code == 200:
            result = res.json()
            if result.get('code') == 0:
                print("✅ 日报已发送到飞书")
                return True
        
        print(f"❌ 发送失败: {res.text}")
        return False
    
    def generate_hk_report(self):
        """生成港股日报"""
        quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        
        report = f"🇭🇰 港股日报 - {datetime.now().strftime('%Y-%m-%d')}\n"
        report += "=" * 40 + "\n\n"
        
        # 1. 指数
        report += "📈 主要指数:\n"
        indices = [
            ('HK.800000', '恒生指数'),
            ('HK.800100', '国企指数'),
            ('HK.800700', '恒生科技'),
        ]
        
        for code, name in indices:
            ret, data = quote_ctx.get_market_snapshot([code])
            if ret == 0 and not data.empty:
                row = data.iloc[0]
                price = row['last_price']
                prev = row['prev_close_price']
                change = (price - prev) / prev * 100 if prev > 0 else 0
                report += f"  {name}: {price:,.2f} ({change:+.2f}%)\n"
        
        # 2. 推荐股票
        report += "\n📊 推荐股票:\n"
        stocks = [
            ('HK.00700', '腾讯'), ('HK.09988', '阿里'), ('HK.03690', '美团'),
            ('HK.02331', '李宁'), ('HK.02020', '安踏'), ('HK.09868', '小鹏'),
        ]
        
        for code, name in stocks:
            ret, data = quote_ctx.get_market_snapshot([code])
            if ret == 0 and not data.empty:
                row = data.iloc[0]
                price = row['last_price']
                prev = row['prev_close_price']
                change = (price - prev) / prev * 100 if prev > 0 else 0
                report += f"  {name}: ¥{price:.2f} ({change:+.2f}%)\n"
        
        # 3. VHSI
        ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
        if ret == 0 and not data.empty:
            vhsi = data.iloc[0]['last_price']
            report += f"\n📉 VHSI: {vhsi:.2f}"
            if vhsi >= 30:
                report += " (极度恐慌)\n"
            elif vhsi >= 25:
                report += " (恐慌)\n"
            else:
                report += " (正常)\n"
        
        quote_ctx.close()
        
        return report
    
    def run(self):
        """生成并发送日报"""
        print(f"生成日报 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 生成日报
        report = self.generate_hk_report()
        
        print("\n日报内容:")
        print(report)
        
        # 立即发送到飞书
        print("\n发送到飞书...")
        if self.send_to_feishu(report):
            print("✅ 成功！")
            
            # 保存发送记录
            import os
            os.makedirs('/home/admin/.openclaw/workspace-arashi/data/sent-reports', exist_ok=True)
            sent_file = f'/home/admin/.openclaw/workspace-arashi/data/sent-reports/{datetime.now().strftime("%Y-%m-%d")}.json'
            with open(sent_file, 'w') as f:
                json.dump({
                    'date': datetime.now().isoformat(),
                    'content': report,
                    'sent': True
                }, f)
        else:
            print("❌ 发送失败")


if __name__ == '__main__':
    reporter = DailyReportWithPush()
    reporter.run()
