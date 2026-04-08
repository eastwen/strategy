#!/usr/bin/env python3
"""
日报生成器 - 包含自选股票池动态
自动读取扫描结果，生成日报
"""

import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class DailyReportGenerator:
    """日报生成器"""
    
    def __init__(self, market='hk'):
        self.market = market
        self.scan_file = '/home/admin/.openclaw/workspace-arashi/data/scan_results.json'
        self.watchlist_file = '/home/admin/.openclaw/workspace-arashi/data/watchlist.json'
        
    def load_scan_data(self):
        """加载扫描数据"""
        try:
            with open(self.scan_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    
    def load_watchlist(self):
        """加载自选股票池"""
        try:
            with open(self.watchlist_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None
    
    def generate_report(self):
        """生成日报"""
        scan_data = self.load_scan_data()
        watchlist = self.load_watchlist()
        
        if not scan_data:
            return None
        
        # 生成报告
        report = f"""# 每日交易报告 {datetime.now().strftime('%Y-%m-%d')}
---

## 📊 一、账户核心数据
| 指标 | 数值 | 备注 |
| :--- | :--- | :--- |
| 初始资金 | $1,000,000.00 | 模拟盘初始本金 |
| 当前总资产 | $1,000,000.00 | 无持仓 |
| 持仓总市值 | $0.00 | 无持仓 |
| 可用资金 | $1,000,000.00 | 100%可用 |

---

## 👀 八、自选关注股票池动态
"""
        
        # 添加自选股票池
        if watchlist:
            if self.market == 'hk' and 'hk' in watchlist:
                report += "### 🇭🇰 港股自选池\n"
                report += "| 标的代码 | 标的名称 | 当前价格 | 当日涨跌幅 | 最新综合评分 | 异动提醒 |\n"
                report += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                
                for stock in watchlist['hk'][:10]:  # 最多显示10只
                    change_str = f"{stock['change_pct']:+.2f}%" if stock['change_pct'] else "0.00%"
                    alert = "接近开仓阈值" if stock['score'] >= 70 else "无"
                    report += f"| {stock['code']} | {stock['name']} | ${stock['price']:.2f} | {change_str} | {stock['score']:.0f}分 | {alert} |\n"
            
            if self.market == 'us' and 'us' in watchlist:
                report += "\n### 🇺🇸 美股自选池\n"
                report += "| 标的代码 | 标的名称 | 当前价格 | 当日涨跌幅 | 最新综合评分 | 异动提醒 |\n"
                report += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                
                for stock in watchlist['us'][:10]:
                    change_str = f"{stock['change_pct']:+.2f}%" if stock['change_pct'] else "0.00%"
                    alert = "接近开仓阈值" if stock['score'] >= 70 else "无"
                    report += f"| {stock['symbol']} | {stock['name']} | ${stock['price']:.2f} | {change_str} | {stock['score']:.0f}分 | {alert} |\n"
        
        # 添加扫描时间
        report += f"\n---\n**扫描时间**: {scan_data.get('last_scan', 'N/A')}\n"
        
        return report
    
    def save_report(self, report):
        """保存报告"""
        if not report:
            return
        
        import os
        
        # 1. 保存到日报目录
        filename = f"/home/admin/.openclaw/workspace-arashi/daily-reports/{datetime.now().strftime('%Y-%m-%d')}-{self.market}.md"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 日报已生成: {filename}")
        
        # 2. 写入待发送目录（让心跳检查时主动汇报）
        os.makedirs('/home/admin/.openclaw/workspace-arashi/data/pending-reports', exist_ok=True)
        pending_file = f"/home/admin/.openclaw/workspace-arashi/data/pending-reports/{self.market}-{datetime.now().strftime('%Y-%m-%d')}.json"
        
        pending_data = {
            'market': self.market,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'content': report,
            'generated_at': datetime.now().isoformat(),
            'sent': False
        }
        
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 已写入待发送队列: {pending_file}")


def main():
    """主函数"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', default='hk', help='hk or us')
    args = parser.parse_args()
    
    market = args.market
    
    generator = DailyReportGenerator(market)
    report = generator.generate_report()
    
    if report:
        print(report)
        generator.save_report(report)
    else:
        print("❌ 无法生成报告")


if __name__ == '__main__':
    main()