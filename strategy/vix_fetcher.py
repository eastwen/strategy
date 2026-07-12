#!/usr/bin/env python3
"""VIX恐慌指数获取模块"""
import requests
import json

from runtime_config import load_api_keys
import yfinance as yf

def get_vix_index():
    """获取当前VIX恐慌指数"""
    try:
        # 使用雅虎财经yfinance获取
        vix = yf.Ticker("^VIX")
        data = vix.history(period='1d')
        if len(data) > 0:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"雅虎财经获取VIX失败: {e}")
    
    try:
        # 使用AlphaVantage获取
        API_KEYS = load_api_keys()
        ALPHA_KEY = API_KEYS['alphavantage']['api_key']
        
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=VIX&apikey={ALPHA_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if 'Time Series (Daily)' in data:
            latest = list(data['Time Series (Daily)'].values())[0]
            return float(latest['4. close'])
    except Exception as e:
        print(f"AlphaVantage获取VIX失败: {e}")
    
    return 20.0  # 默认值

def get_market_sentiment(vix=None):
    """根据VIX判断市场情绪"""
    if vix is None:
        vix = get_vix_index()
    
    if vix < 15:
        return "极度乐观", vix
    elif 15 <= vix < 20:
        return "乐观", vix
    elif 20 <= vix < 25:
        return "中性", vix
    elif 25 <= vix < 30:
        return "恐慌", vix
    else:
        return "极度恐慌", vix

if __name__ == "__main__":
    sentiment, vix = get_market_sentiment()
    print(f"当前VIX指数: {vix:.2f}，市场情绪: {sentiment}")
