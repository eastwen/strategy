#!/usr/bin/env python3
"""
飞书消息推送模块
主动发送消息给用户
"""

import requests
import json
import time
import os

from runtime_config import load_api_keys

class FeishuPusher:
    """飞书推送器"""

    def __init__(self):
        self.config = load_api_keys().get('feishu', {})
        self.app_id = self.config.get('appId', '')
        self.app_secret = self.config.get('appSecret', '')
        self.open_id = self.config.get('openId', '')
        self.chat_id = self.config.get('chatId')  # 群聊ID
        self.base_url = "https://open.feishu.cn/open-apis"
        self.tenant_access_token = None
        self.token_expire_time = 0

    def _load_chat_id(self):
        return load_api_keys().get('feishu', {}).get('chatId')

    def _load_app_secret(self):
        return load_api_keys().get('feishu', {}).get('appSecret')

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

        # 优先使用群聊ID,否则使用用户ID
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

    def send_buy_notification(self, symbol, quantity, price, amount, target_take_profit, target_stop_loss, score_total, score_news, score_announce, score_community, score_institution, score_capital, signal_type, llm_conclusion, order_id, timestamp, risk_note='', estimated_keys=None, evidences=None, score_adjustments=None):
        """发送自动买入通知(真实五源评分版)

        2026-06-24 east 修复：
          - risk_note 携带完整 ATR 风控规则
          - estimated_keys 标记哪些分项是估算值
        target_take_profit / target_stop_loss 可能为 None（ATR 采集失败）。
        """
        def _fmt(v, prefix='$'):
            try:
                if v is None:
                    return '暂无'
                return f"{prefix}{float(v):.2f}"
            except Exception:
                return str(v) if v is not None else '暂无'

        risk_block = risk_note.strip() if risk_note else ''
        if target_take_profit and target_stop_loss:
            target_line = f"🎯 预测: 止盈价: {_fmt(target_take_profit)} / 止损价: {_fmt(target_stop_loss)}"
        else:
            target_line = "🎯 预测: 暂无明确目标价"
        uncov = set(estimated_keys or [])
        def tag(key):
            return ' (未覆盖)' if key in uncov else ''
        ev = evidences or {}
        def ev_line(key):
            txt = ev.get(key, '') if isinstance(ev, dict) else ''
            return f"\n   · {txt}" if txt else ''
        adjustments = score_adjustments or {}
        def adjustment_tag(key):
            value = adjustments.get(key) if isinstance(adjustments, dict) else None
            if key in uncov or value is None:
                return ''
            try:
                return f" (较中性{float(value):+.1f})"
            except (TypeError, ValueError):
                return ''

        content = f"""✅ 买入成功

标的: {symbol}
数量: {quantity}股
买入价: ~${price:.2f}
金额: ~${amount:,.2f}
{target_line}

📊 评分明细: 总分{score_total}
 国际资讯: {score_news}/25{adjustment_tag('news')}{tag('news')}{ev_line('news')}
 官方公告: {score_announce}/20{adjustment_tag('announce')}{tag('announce')}{ev_line('announce')}
 社区情绪: {score_community}/25{adjustment_tag('community')}{tag('community')}{ev_line('community')}
 机构观点: {score_institution}/20{adjustment_tag('institution')}{tag('institution')}{ev_line('institution')}
 资金异动: {score_capital}/10{adjustment_tag('capital')}{tag('capital')}{ev_line('capital')}

🔍 信号类型: {signal_type}
🤖 LLM验真: {llm_conclusion}

订单ID: {order_id}
时间: {timestamp}"""
        return self.send_message(content)

    def send_sell_notification(self, symbol, quantity, price, amount, pnl_pct, reason, order_id, timestamp):
        """发送卖出/平仓通知（reason 可以是多行 LLM 复盘文本）"""
        pnl_emoji = '📈' if pnl_pct >= 0 else '📉'
        content = f"""❌ 卖出完成

标的: {symbol}
数量: {quantity}股
卖出价: ~${price:.2f}
金额: ~${amount:,.2f}
盈亏: {pnl_emoji} {pnl_pct:+.2f}%

原因:
{reason}

订单ID: {order_id}
时间: {timestamp}"""
        return self.send_message(content)

    def send_opportunity_notification(self, symbol, score_total, score_news, score_announce, score_community, score_institution, score_capital, signal_type, llm_conclusion, market_status, timestamp, estimated_keys=None, evidences=None, score_adjustments=None):
        """发送非交易时间交易机会通知(真实五源评分版)"""
        uncov = set(estimated_keys or [])
        def tag(key):
            return ' (未覆盖)' if key in uncov else ''
        ev = evidences or {}
        def ev_line(key):
            txt = ev.get(key, '') if isinstance(ev, dict) else ''
            return f"\n   · {txt}" if txt else ''
        adjustments = score_adjustments or {}
        def adjustment_tag(key):
            value = adjustments.get(key) if isinstance(adjustments, dict) else None
            if key in uncov or value is None:
                return ''
            try:
                return f" (较中性{float(value):+.1f})"
            except (TypeError, ValueError):
                return ''
        content = f"""🔔 【美股非交易时段高价值信号】

市场状态: {market_status}
标的: {symbol}

📊 评分明细: 总分{score_total}
 国际资讯: {score_news}/25{adjustment_tag('news')}{tag('news')}{ev_line('news')}
 官方公告: {score_announce}/20{adjustment_tag('announce')}{tag('announce')}{ev_line('announce')}
 社区情绪: {score_community}/25{adjustment_tag('community')}{tag('community')}{ev_line('community')}
 机构观点: {score_institution}/20{adjustment_tag('institution')}{tag('institution')}{ev_line('institution')}
 资金异动: {score_capital}/10{adjustment_tag('capital')}{tag('capital')}{ev_line('capital')}

🔍 信号类型: {signal_type}
🤖 LLM验真: {llm_conclusion}

时间: {timestamp}

请确认是否执行交易。"""
        return self.send_message(content)

    def send_daily_report(self, report_content):
        """发送日报"""
        # 截取前4000字符(飞书限制)
        if len(report_content) > 4000:
            report_content = report_content[:4000] + "\n\n... (内容过长,已截断)"

        return self.send_message(report_content)


# 测试
if __name__ == '__main__':
    print("=" * 60)
    print("飞书推送模块测试")
    print("=" * 60)
    print(f"Open ID: ou_571e965fc81a2e887609a06ed6103d66")
    print()
    print("⚠️ 需要 App Secret 才能发送消息")
    print("请在飞书开放平台获取 App Secret 并配置")
