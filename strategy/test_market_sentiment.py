#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3
"""
市场情绪因子测试脚本
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')

from us_scanner import USScanner

def test_market_sentiment():
    """测试市场情绪因子"""

    print('='*50)
    print('🧪 市场情绪因子测试')
    print('='*50)

    # 创建扫描器实例
    scanner = USScanner(scan_limit=3)  # 限制3只股票测试

    # 测试1: VIX获取
    print('\n📊 1. VIX恐慌指数测试:')
    try:
        vix = scanner.get_vix_realtime()
        print(f'   ✅ VIX: {vix:.1f}')
        if vix >= 30:
            print(f'   📈 状态: 极度恐慌 (扣分-9分)')
        elif vix >= 25:
            print(f'   📉 状态: 恐慌 (扣分-5分)')
        elif vix <= 15:
            print(f'   🟢 状态: 平静 (加分+6分)')
        else:
            print(f'   🟡 状态: 正常')
    except Exception as e:
        print(f'   ❌ VIX获取失败: {e}')

    # 测试2: CNN恐慌贪婪
    print('\n📊 2. CNN恐慌贪婪指数测试:')
    try:
        cnn = scanner.get_cnn_fear_greed_realtime()
        print(f'   ✅ CNN: {cnn:.1f}')
        if cnn <= 25:
            print(f'   🔴 状态: 极度恐惧 (扣分-4分)')
        elif cnn >= 75:
            print(f'   🟢 状态: 贪婪 (加分+3分)')
        else:
            print(f'   🟡 状态: 中性')
    except Exception as e:
        print(f'   ❌ CNN获取失败: {e}')

    # 测试3: 期权比例
    print('\n📊 3. 期权比例测试:')
    try:
        option_ratio = scanner.get_option_ratio_realtime()
        print(f'   ✅ 期权比例: {option_ratio:.2f}')
        if option_ratio >= 1.2:
            print(f'   📈 状态: 看多 (加分+1.5分)')
        elif option_ratio <= 0.8:
            print(f'   📉 状态: 看空 (扣分-1.5分)')
        else:
            print(f'   🟡 状态: 中性')
    except Exception as e:
        print(f'   ❌ 期权比例获取失败: {e}')

    # 测试4: 市场情绪综合评分（正面新闻）
    print('\n📊 4. 市场情绪综合评分测试 (正面新闻):')
    try:
        emotion_score = scanner.calculate_market_sentiment(news_sentiment=0.7)  # 正面新闻
        print(f'   ✅ 情绪评分: {emotion_score:+.1f}分')
    except Exception as e:
        print(f'   ❌ 情绪评分失败: {e}')

    # 测试5: 市场情绪综合评分（负面新闻）
    print('\n📊 5. 市场情绪综合评分测试 (负面新闻):')
    try:
        emotion_score = scanner.calculate_market_sentiment(news_sentiment=0.3)  # 负面新闻
        print(f'   ✅ 情绪评分: {emotion_score:+.1f}分')
    except Exception as e:
        print(f'   ❌ 情绪评分失败: {e}')

    # 测试6: 完整评分函数
    print('\n📊 6. 完整评分函数测试:')
    try:
        # 模拟AAPL数据
        test_score = scanner.calculate_score(
            price=145.5,
            prev_close=143.0,
            change_pct=1.75,
            news_sentiment=0.6  # 正面情绪
        )
        print(f'   ✅ AAPL测试评分: {test_score:.0f}分')
        if test_score >= 80:
            print(f'   🎯 评级: 高评分机会')
        elif test_score >= 70:
            print(f'   🟡 评级: 中等机会')
        else:
            print(f'   🔴 评级: 低评分机会')
    except Exception as e:
        print(f'   ❌ 完整评分失败: {e}')

    print('\n' + '='*50)
    print('🧪 测试完成')
    print('='*50)

if __name__ == '__main__':
    test_market_sentiment()