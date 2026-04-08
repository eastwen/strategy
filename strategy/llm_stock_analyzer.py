#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
LLM股票分析模块
被港股/美股扫描器调用，对候选股票进行LLM分析
"""

import requests
import json
import re
from datetime import datetime

class LLMStockAnalyzer:
    """LLM股票分析器"""
    
    def __init__(self):
        self.api_key = self._load_api_key()
        self.model = "qwen-coder-turbo-0919"
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    def _load_api_key(self):
        config_path = '/home/admin/.openclaw/openclaw.json'
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get('env', {}).get('MODELSTUDIO_API_KEY', '')
        except:
            return ''
    
    def analyze(self, symbol, market_data):
        """分析股票
        
        Args:
            symbol: 股票代码 (如 US.AAPL, HK.00700)
            market_data: dict 包含:
                - base_score: 基础评分
                - price: 当前价格
                - change_pct: 涨跌幅
                - rsi: RSI值
                - ma20, ma50: 均线
                - volume_ratio: 成交量比率
                - atr: ATR
                - sentiment: 新闻情绪
                - market: 市场类型 (us/hk)
        
        Returns:
            dict: 包含 final_score, score_adjust, llm_reason
        """
        
        if not self.api_key:
            return self._fallback(market_data, "无API Key")
        
        prompt = self._build_prompt(symbol, market_data)
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 150,
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
                return self._parse(content, market_data)
            else:
                return self._fallback(market_data, f"API错误:{resp.status_code}")
                
        except Exception as e:
            return self._fallback(market_data, f"调用失败:{str(e)[:20]}")
    
    def _build_prompt(self, symbol, data):
        market = data.get('market', 'us')
        market_name = '美股' if market == 'us' else '港股'
        
        prompt = f"""你是专业的{market_name}股票分析师。

股票: {symbol}
市场: {market_name}
当前价格: ${data.get('price', 'N/A')}
涨跌幅: {data.get('change_pct', 0):+.2f}%
RSI: {data.get('rsi', 'N/A')}
MA20/MA50: {data.get('ma20', 'N/A')}/{data.get('ma50', 'N/A')}
成交量比率: {data.get('volume_ratio', 'N/A')}x
ATR: {data.get('atr', 'N/A')}
基础评分: {data.get('base_score', 70)}分
新闻情绪: {data.get('sentiment', 'N/A')}

请分析并给出：
1. 评分调整（-10到+10）
2. 一句话理由

格式：调整,理由
例如：+5,技术面强劲

直接回复："""
        
        return prompt
    
    def _parse(self, content, data):
        base_score = data.get('base_score', 70)
        symbol = data.get('symbol', 'UNKNOWN')
        
        try:
            content = content.strip()
            
            if ',' in content:
                parts = content.split(',', 1)
                adjust_str = parts[0].strip()
                reason = parts[1].strip() if len(parts) > 1 else ''
            else:
                adjust_str = content
                reason = ''
            
            match = re.search(r'[-+]?\d+', adjust_str)
            if match:
                adjust = int(match.group())
                if abs(adjust) <= 10:
                    final = max(0, min(100, base_score + adjust))
                else:
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
        except:
            pass
        
        return self._fallback(data, f"解析失败:{content[:20]}")
    
    def _fallback(self, data, reason):
        base = data.get('base_score', 70)
        return {
            'symbol': data.get('symbol', 'UNKNOWN'),
            'base_score': base,
            'score_adjust': 0,
            'llm_reason': reason,
            'final_score': base,
            'timestamp': datetime.now().isoformat()
        }


def analyze_stock(symbol, market_data):
    """便捷函数：分析单只股票"""
    analyzer = LLMStockAnalyzer()
    result = analyzer.analyze(symbol, market_data)
    
    print(f"\n📊 LLM分析 - {symbol}")
    print(f"   基础评分: {result['base_score']}")
    print(f"   LLM调整: {result['score_adjust']:+d}")
    print(f"   最终评分: {result['final_score']}")
    print(f"   理由: {result['llm_reason']}")
    
    return result


if __name__ == '__main__':
    # 测试
    test_us = {
        'symbol': 'AAPL',
        'market': 'us',
        'base_score': 75,
        'price': 175.50,
        'change_pct': 2.5,
        'rsi': 55,
        'ma20': 170,
        'ma50': 168,
        'volume_ratio': 1.8,
        'atr': 3.5,
        'sentiment': '正面'
    }
    
    test_hk = {
        'symbol': 'HK.00700',
        'market': 'hk',
        'base_score': 72,
        'price': 380.00,
        'change_pct': 1.2,
        'rsi': 58,
        'ma20': 375,
        'ma50': 370,
        'volume_ratio': 1.5,
        'atr': 8.5,
        'sentiment': '中性'
    }
    
    print("="*50)
    print("🧪 测试美股分析...")
    result_us = analyze_stock('US.AAPL', test_us)
    print(f"最终评分: {result_us['final_score']}")
    
    print("="*50)
    print("🧪 测试港股分析...")
    result_hk = analyze_stock('HK.00700', test_hk)
    print(f"最终评分: {result_hk['final_score']}")
    print("="*50)
