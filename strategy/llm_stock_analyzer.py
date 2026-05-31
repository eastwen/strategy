#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
LLM股票分析模块
- 被港股/美股扫描器调用，对候选股票进行LLM分析
- 被日报/周报调用，生成市场分析、风险提示、操作建议等

换模型只改文件顶部的 4 个常量，其他不用动。
"""

import requests
import json
import re
from datetime import datetime


# ===== 换模型只改这里 =====
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL    = "qwen-turbo"
LLM_FALLBACK = "qwen-plus-0112"
LLM_API_KEY  = "sk-xxx（请替换为你的通义千问API Key）"
# ==========================


class LLMClient:
    """LLM通用客户端 - 所有LLM调用统一走这里"""

    def __init__(self):
        self.base_url      = LLM_BASE_URL
        self.model         = LLM_MODEL
        self.fallback_model = LLM_FALLBACK
        self.api_key       = LLM_API_KEY

        if not self.api_key or self.api_key.startswith("sk-xxx"):
            print("⚠️ LLM API Key 未配置，请修改文件顶部 LLM_API_KEY")

    def call(self, prompt, max_tokens=500, temperature=0.3, model=None):
        """通用LLM调用，失败自动 fallback 到 fallback_model

        Args:
            prompt: 提示词
            max_tokens: 最大token数
            temperature: 温度
            model: 指定模型，默认用顶部常量 LLM_MODEL
        Returns:
            str: LLM回复内容，失败返回None
        """
        if not self.api_key or self.api_key.startswith("sk-xxx"):
            return None

        use_model = model or self.model

        try:
            resp = requests.post(
                f'{self.base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': use_model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': max_tokens,
                    'temperature': temperature
                },
                timeout=30
            )

            if resp.status_code == 200:
                result = resp.json()
                return result['choices'][0]['message']['content'].strip()
            else:
                if use_model == self.model and self.fallback_model:
                    print(f"⚠️ {use_model} 失败({resp.status_code})，尝试 {self.fallback_model}")
                    return self.call(prompt, max_tokens, temperature, model=self.fallback_model)
                print(f"⚠️ LLM调用失败: HTTP {resp.status_code} - {resp.text[:100]}")
                return None

        except Exception as e:
            print(f"⚠️ LLM调用异常: {e}")
            return None

    # ===== 日报/周报用的LLM功能 =====

    def get_market_prediction(self, market, vix_val, index_data):
        """使用LLM生成未来3日市场预判

        Args:
            market: 'hk' 或 'us'
            vix_val: VIX/VHSI数值
            index_data: 指数数据dict {name: {price, change_pct}}
        Returns:
            list[dict]: 预测结果 [{day, sentiment, probability, trend}]，失败返回None
        """
        market_name = '港股' if market == 'hk' else '美股'

        index_context = ''
        for name, data in index_data.items():
            chg = data.get('change_pct', 0)
            try: chg = float(chg)
            except: chg = 0
            index_context += f"- {name}: {float(data.get('price', 0)):,.2f} ({chg:+.2f}%)\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时数据预测未来3个交易日的市场走势。

当前市场数据：
{index_context}
- 恐慌指数: {vix_val:.1f}
- 情绪状态: {'恐慌' if vix_val > 25 else '正常' if vix_val > 20 else '平静'}

请给出未来3个交易日的预测，格式如下：
T+1日|情绪预判|概率|市场走势
T+2日|情绪预判|概率|市场走势
T+3日|情绪预判|概率|市场走势

每行一个交易日，用|分隔。情绪预判用：乐观/中性偏多/中性/中性偏空/悲观。概率用百分比。市场走势用简短描述（不超过10字）。

直接回复3行预测，不要其他内容。"""

        content = self.call(prompt, max_tokens=200, temperature=0.5)
        if content:
            return self._parse_prediction(content)
        return None

    def _parse_prediction(self, content):
        """解析LLM返回的预测内容"""
        predictions = []
        for line in content.strip().split('\n'):
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 4:
                    predictions.append({
                        'day': parts[0].strip(),
                        'sentiment': parts[1].strip(),
                        'probability': parts[2].strip(),
                        'trend': parts[3].strip()
                    })
        return predictions if predictions else None

    def get_market_analysis(self, market, index_data, vix_val):
        """使用LLM解读市场走势

        Args:
            market: 'hk' 或 'us'
            index_data: 指数数据dict {name: {price, change_pct}}
            vix_val: VIX/VHSI数值
        Returns:
            str: 市场分析文本，失败返回None
        """
        market_name = '港股' if market == 'hk' else '美股'

        index_lines = ''
        for name, data in index_data.items():
            price = float(data.get('price', 0))
            chg = data.get('change_pct', 0)
            try: chg = float(chg)
            except: chg = 0
            index_lines += f"- {name}: {price:,.2f} ({chg:+.2f}%)\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时数据解读今日市场走势。

今日{market_name}指数表现：
{index_lines}
恐慌指数: {vix_val:.1f}

请用2-3句话解读今日{market_name}市场走势，要点：
1. 整体趋势判断（上涨/下跌/震荡）
2. 板块或风格特征（如有）
3. 对短期（1-3日）的展望

直接回复分析内容，不要加标题。"""

        return self.call(prompt, max_tokens=300, temperature=0.4)

    def get_risk_assessment(self, market_data):
        """使用LLM生成动态风险分析

        Args:
            market_data: dict 包含 pos_pct, cash_pct, vix, vhsi, total_asset, positions, initial
        Returns:
            str: 风险分析文本，失败返回None
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix', 20)
        vhsi       = market_data.get('vhsi', 25)
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = ''
        for p in positions[:8]:
            pos_list += f"  - {p.get('symbol', '')}: 浮盈{p.get('pnl_pct', 0):+.2f}%\n"

        prompt = f"""你是专业的风险管理分析师。请根据以下实时数据给出风险分析。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细:
{pos_list if pos_list else '  无持仓'}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请给出2-3条风险提示，每条格式：
风险等级|风险类型|具体描述|建议动作

风险等级用：🔴高/🟠中/🟡低
风险类型用：系统性/非系统性/流动性/集中度
建议动作用简短描述（不超过15字）

每行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=300, temperature=0.3)

    def get_action_recommendations(self, market_data):
        """使用LLM生成针对性操作建议

        Args:
            market_data: dict 包含 pos_pct, cash_pct, vix, vhsi, total_asset, positions, initial
        Returns:
            str: 操作建议文本，失败返回None
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix', 20)
        vhsi       = market_data.get('vhsi', 25)
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = ''
        for p in positions[:8]:
            pos_list += f"  - {p.get('symbol', '')}: 浮盈{p.get('pnl_pct', 0):+.2f}%\n"

        prompt = f"""你是专业的交易策略顾问。请根据以下实时数据给出针对性操作建议。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细:
{pos_list if pos_list else '  无持仓'}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请给出3条操作建议，每条格式：
建议类型|具体建议

建议类型用：仓位管理/止损止盈/开仓机会/风险规避
具体建议要结合实际数据，简明扼要（不超过20字）

每行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=300, temperature=0.3)


class LLMStockAnalyzer:
    """LLM股票分析器 - 扫描器用"""

    def __init__(self):
        self.client = LLMClient()

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
        if not self.client.api_key or self.client.api_key.startswith("sk-xxx"):
            return self._fallback(market_data, "无API Key")

        prompt = self._build_prompt(symbol, market_data)
        content = self.client.call(prompt, max_tokens=150, temperature=0.3)

        if content:
            return self._parse(content, market_data)
        return self._fallback(market_data, "调用失败")

    def _build_prompt(self, symbol, data):
        market = data.get('market', 'us')
        market_name = '美股' if market == 'us' else '港股'

        return f"""你是专业的{market_name}股票分析师。

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

    def _parse(self, content, data):
        base_score = data.get('base_score', 70)

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
                    'symbol': data.get('symbol', 'UNKNOWN'),
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
        passed = not any(x in reason for x in ['无API Key', 'API错误', '调用失败'])

        return {
            'symbol': data.get('symbol', 'UNKNOWN'),
            'base_score': base,
            'score_adjust': 0,
            'llm_reason': reason,
            'final_score': base,
            'timestamp': datetime.now().isoformat(),
            'passed': passed
        }


# ===== 便捷函数 =====

def analyze_stock(symbol, market_data):
    """便捷函数：分析单只股票（扫描器用）"""
    analyzer = LLMStockAnalyzer()
    result = analyzer.analyze(symbol, market_data)

    print(f"\n📊 LLM分析 - {symbol}")
    print(f"   基础评分: {result['base_score']}")
    print(f"   LLM调整: {result['score_adjust']:+d}")
    print(f"   最终评分: {result['final_score']}")
    print(f"   理由: {result['llm_reason']}")

    return result


def get_llm_client():
    """便捷函数：获取LLMClient实例（日报/周报用）"""
    return LLMClient()


if __name__ == '__main__':
    client = LLMClient()

    print("="*50)
    print("🧪 测试通用LLM调用...")
    result = client.call('1+1=? 只回答数字', max_tokens=10, temperature=0.1)
    print(f"结果: {result}")

    print("="*50)
    print("🧪 测试股票分析...")
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
    result_us = analyze_stock('US.AAPL', test_us)
    print(f"最终评分: {result_us['final_score']}")
    print("="*50)