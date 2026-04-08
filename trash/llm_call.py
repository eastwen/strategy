#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
LLM股票分析模块
使用ModelStudio API调用LLM进行分析
"""

import requests
import json
import os
import re
import time
from datetime import datetime

class LLMCaller:
    """简单的LLM调用"""
    
    def __init__(self):
        self.api_key = self._load_api_key()
        self.model = "qwen-coder-turbo-0919"  # 通义千问 coder turbo
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    def _load_api_key(self):
        """从OpenClaw配置加载API Key"""
        config_path = '/home/admin/.openclaw/openclaw.json'
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get('env', {}).get('MODELSTUDIO_API_KEY', '')
        except:
            return ''
    
    def analyze_stock(self, symbol, stock_data):
        """分析股票并返回评分调整"""
        
        if not self.api_key:
            return self._fallback_result(stock_data, "无API Key")
        
        prompt = self._build_prompt(symbol, stock_data)
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': self.model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 100,
            'temperature': 0.3
        }
        
        try:
            resp = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )
            
            if resp.status_code == 200:
                result = resp.json()
                content = result['choices'][0]['message']['content']
                return self._parse_response(content, stock_data)
            else:
                return self._fallback_result(stock_data, f"API错误:{resp.status_code}")
                
        except Exception as e:
            return self._fallback_result(stock_data, f"调用失败:{str(e)[:20]}")
    
    def _build_prompt(self, symbol, stock_data):
        """构建分析提示"""
        
        return f"""你是专业股票分析师。分析这只股票：

股票代码: {symbol}
当前价格: ${stock_data.get('price', 'N/A')}
涨跌幅: {stock_data.get('change_pct', 0):+.2f}%
RSI: {stock_data.get('rsi', 'N/A')}
MA20/MA50: {stock_data.get('ma20', 'N/A')}/{stock_data.get('ma50', 'N/A')}
成交量比率: {stock_data.get('volume_ratio', 'N/A')}x
ATR: {stock_data.get('atr', 'N/A')}
基础评分: {stock_data.get('base_score', 70)}分

请直接给出：
1. 评分调整(-10到+10，如+5或-3)
2. 一句话理由

格式：调整,理由
例如：+5,基本面强劲

直接回复，不要解释。"""
    
    def _parse_response(self, content, stock_data):
        """解析LLM响应"""
        base_score = stock_data.get('base_score', 70)
        symbol = stock_data.get('symbol', 'UNKNOWN')
        
        try:
            content = content.strip()
            
            # 尝试解析 "调整,理由" 格式
            if ',' in content:
                parts = content.split(',', 1)
                adjust_str = parts[0].strip()
                reason = parts[1].strip() if len(parts) > 1 else ''
            else:
                # 只有数字
                adjust_str = content
                reason = ''
            
            # 提取数字（可能是 +5 或 -3 或 75）
            match = re.search(r'[-+]?\d+', adjust_str)
            if match:
                adjust = int(match.group())
                # 判断是调整值还是绝对评分
                if abs(adjust) <= 10:
                    # 这是调整值
                    adjust = max(-10, min(10, adjust))
                    final = max(0, min(100, base_score + adjust))
                else:
                    # 这是绝对评分
                    final = max(0, min(100, adjust))
                    adjust = final - base_score
                
                return {
                    'symbol': symbol,
                    'base_score': base_score,
                    'score_adjust': adjust,
                    'llm_reason': reason[:100] if reason else 'LLM分析',
                    'final_score': final,
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            pass
        
        return self._fallback_result(stock_data, f"解析失败: {content[:20]}")
    
    def _fallback_result(self, stock_data, reason):
        """降级结果"""
        base = stock_data.get('base_score', 70)
        return {
            'symbol': stock_data.get('symbol', 'UNKNOWN'),
            'base_score': base,
            'score_adjust': 0,
            'llm_reason': reason,
            'final_score': base,
            'timestamp': datetime.now().isoformat()
        }


def analyze_stock(symbol, stock_data):
    """便捷函数：分析单只股票"""
    caller = LLMCaller()
    result = caller.analyze_stock(symbol, stock_data)
    
    print(f"\n📊 LLM分析 - {symbol}")
    print(f"   基础评分: {result['base_score']}")
    print(f"   LLM调整: {result['score_adjust']:+d}")
    print(f"   最终评分: {result['final_score']}")
    print(f"   理由: {result['llm_reason']}")
    
    return result


# 测试
if __name__ == '__main__':
    test = {
        'symbol': 'AAPL',
        'price': 175.50,
        'change_pct': 2.5,
        'rsi': 55,
        'ma20': 170.00,
        'ma50': 168.00,
        'volume_ratio': 1.8,
        'atr': 3.5,
        'base_score': 72
    }
    
    print("🧪 测试LLM调用...")
    result = analyze_stock('AAPL', test)
    print(f"\n✅ 完成 - 最终评分: {result['final_score']}")
