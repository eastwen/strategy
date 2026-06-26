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
import sqlite3
from datetime import datetime

# 想加更多备用，直接往 LLM_FALLBACKS 里 append 就行。
LLM_BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2" #https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY  = "238e6a193f9882a03075385ac86676e2:YmRkN2E0YjQ1NGNjMDA0NzdlNjE3NmU0"  #sk-30c44cbba5eb43f2bf0a5c9a05d79d11
LLM_MODEL    = "xopqwen36v35b"                # 主模型（2026-06-16: 原主模型 qwen3.6-plus-2026-04-02 免费额度耗尽，换到不带快照日期的稳定版）
LLM_FALLBACKS = [                          # 备用模型（按顺序尝试，越靠前优先级越高）
    "xopqwen35v35b",         # 原主模型，现作为备用 (额度恢复后也能用)
    "xophunyuan7bmt",
    "xop35qwen2b",
    "xop3qwen1b7",
    "qwen3.6-35b-a3b",
    "qwen3.5-plus-2026-04-20",
    "glm-5.1",                         # 智谱 GLM
    "kimi-k2.6",                       # 月之暗面 Kimi
]
# ==========================

# 兼容旧代码：保留 LLM_FALLBACK 作为第一个备用的别名
LLM_FALLBACK = LLM_FALLBACKS[0] if LLM_FALLBACKS else None

# 新闻库路径
NEWS_DB_PATH = '/home/admin/.openclaw/workspace-stock/data/news/news.db'


def fetch_recent_news(symbol: str, hours: int = 24, limit: int = 8):
    """拉取该股最近 N 小时的新闻标题 + 关键词情绪。

    返回: list[ {title, sentiment, source, hours_ago} ]，最多 limit 条；库不可用或无记录返回 [].
    股票代码带前缀会被去掉 (US.AAPL -> AAPL, HK.00700 -> 00700)。
    """
    if not symbol:
        return []
    raw = symbol.split('.')[-1] if '.' in symbol else symbol
    try:
        conn = sqlite3.connect(NEWS_DB_PATH, timeout=2)
        cur = conn.cursor()
        cur.execute("""
            SELECT n.title, n.sentiment, n.source,
                   ROUND((julianday('now') - julianday(n.timestamp)) * 24, 1) AS hours_ago
            FROM stock_mentions sm
            JOIN news n ON n.id = sm.news_id
            WHERE sm.symbol = ? AND n.timestamp > datetime('now', ?)
            ORDER BY n.timestamp DESC
            LIMIT ?
        """, (raw, f'-{hours} hours', limit))
        rows = cur.fetchall()
        conn.close()
        out = []
        for title, sent, src, ha in rows:
            out.append({
                'title': (title or '')[:120],
                'sentiment': float(sent) if sent is not None else 0.5,
                'source': src or '',
                'hours_ago': ha if ha is not None else 0.0,
            })
        return out
    except Exception:
        return []


def format_news_block(news_items):
    """把新闻列表格式化为 prompt 能读的多行文本，每条带情绪表情 + 距今时间。"""
    if not news_items:
        return '无近期相关新闻'
    lines = []
    for n in news_items:
        s = n.get('sentiment', 0.5)
        emoji = '📈' if s > 0.6 else '📉' if s < 0.4 else '📊'
        ha = n.get('hours_ago', 0.0)
        ha_str = f'{ha:.0f}h前' if ha and ha >= 1 else '刚刚'
        lines.append(f"  {emoji} [{ha_str}] {n['title']}")
    return '\n'.join(lines)


# ===== 换模型只改这里 =====
# 主模型 + 备用模型链。主模型挂了按顺序往下试，直到有一个返回成功。



class LLMClient:
    """LLM通用客户端 - 所有LLM调用统一走这里"""

    def __init__(self):
        self.base_url        = LLM_BASE_URL
        self.model           = LLM_MODEL
        self.fallback_models = list(LLM_FALLBACKS)
        self.fallback_model  = self.fallback_models[0] if self.fallback_models else None  # 兼容旧字段
        self.api_key         = LLM_API_KEY

        if not self.api_key or self.api_key.startswith("sk-xxx"):
            print("⚠️ LLM API Key 未配置，请修改文件顶部 LLM_API_KEY")

    def _try_one(self, use_model, prompt, max_tokens, temperature):
        """调用单个模型一次。成功返回 (True, content)，失败返回 (False, 错误描述)。

        2026-06-25 east 修复：
        - deepseek-v4-pro 等推理模型会把回答放在 reasoning_content，正式 content 为空；
          推理模型默认 max_tokens 被 reasoning 吃光时 content 会空串。
        - 现在：拿不到 content 时回退到 reasoning_content 的最后一行；并强制把推理模型的
          max_tokens 抬到 800 以上，保证 content 有预算输出。
        """
        is_reasoning = 'deepseek' in (use_model or '').lower() or 'r1' in (use_model or '').lower() or 'reasoner' in (use_model or '').lower()
        if is_reasoning and max_tokens < 800:
            max_tokens = 800
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
                timeout=90
            )
            if resp.status_code == 200:
                msg = resp.json()['choices'][0]['message']
                content = (msg.get('content') or '').strip()
                if not content:
                    # 推理模型：从 reasoning_content 末尾抽答案
                    reasoning = (msg.get('reasoning_content') or '').strip()
                    if reasoning:
                        last = [ln for ln in reasoning.splitlines() if ln.strip()]
                        content = last[-1].strip() if last else ''
                if not content:
                    return False, 'content/reasoning 均为空'
                return True, content
            return False, f"HTTP {resp.status_code} - {resp.text[:100]}"
        except Exception as e:
            return False, f"异常: {e}"

    def call(self, prompt, max_tokens=500, temperature=0.3, model=None):
        """通用LLM调用，主模型失败按 LLM_FALLBACKS 顺序自动降级

        Args:
            prompt: 提示词
            max_tokens: 最大token数
            temperature: 温度
            model: 指定模型；指定后不再 fallback
        Returns:
            str: LLM回复内容，全部失败返回None
        """
        if not self.api_key or self.api_key.startswith("sk-xxx"):
            return None

        # 指定单一模型：只试这一个，不降级
        if model:
            ok, result = self._try_one(model, prompt, max_tokens, temperature)
            if ok:
                return result
            print(f"⚠️ LLM调用失败 [{model}]: {result}")
            return None

        # 主模型 + 备用链，按顺序尝试
        candidates = [self.model] + [m for m in self.fallback_models if m and m != self.model]
        for idx, use_model in enumerate(candidates):
            ok, result = self._try_one(use_model, prompt, max_tokens, temperature)
            if ok:
                if idx > 0:
                    print(f"✅ 降级到备用模型成功: {use_model}")
                return result
            if idx < len(candidates) - 1:
                next_model = candidates[idx + 1]
                print(f"⚠️ {use_model} 失败({result})，尝试备用 {next_model}")
            else:
                print(f"⚠️ LLM全部模型调用失败，最后一次 [{use_model}]: {result}")
        return None

    # ===== 日报/周报用的LLM功能 =====

    def get_market_prediction(self, market, vix_val, index_data, sentiment_full=None):
        """使用LLM生成未来3日市场预判

        Args:
            market: 'hk' 或 'us'
            vix_val: VIX/VHSI数值（向后兼容）
            index_data: 指数数据dict {name: {price, change_pct}}
            sentiment_full: 2026-06-18 east 修复——多源综合情绪评分字典
                            港股: {sentiment_score, vhsi, capital_flow, bull_bear_ratio, ...}
                            美股: {sentiment_score, vix, fear_greed, option_ratio, spx_change, ...}
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

        # 2026-06-18 east 修复：多源情绪上下文（取代单一 VIX/VHSI）
        sentiment_block = f"- 恐慌波动指数: {vix_val:.1f}\n"
        sentiment_block += f"- 波动状态: {'恐慌' if vix_val > 25 else '正常' if vix_val > 20 else '平静'}\n"
        if sentiment_full:
            score = sentiment_full.get('sentiment_score', 50)
            label = sentiment_full.get('sentiment_label', 'N/A')
            sentiment_block += f"- 多源综合情绪评分: {score:.0f}/100 ({label})\n"
            if market == 'hk':
                cf = sentiment_full.get('capital_flow')
                if cf is not None:
                    sentiment_block += f"- 恒指权重股资金净流: {cf:+.2f}亿港元 ({sentiment_full.get('flow_sentiment', 'N/A')})\n"
                wr = sentiment_full.get('bull_bear_ratio')
                if wr is not None:
                    sentiment_block += f"- 牛熊证多空成交额比: {wr:.3f} ({sentiment_full.get('warrant_sentiment', 'N/A')})\n"
            else:
                fg = sentiment_full.get('fear_greed')
                if fg is not None:
                    sentiment_block += f"- CNN恐慌贪婪指数: {fg:.1f} ({sentiment_full.get('fg_sentiment', 'N/A')})\n"
                pcr = sentiment_full.get('option_ratio')
                if pcr is not None:
                    sentiment_block += f"- 期权 Put/Call 比例: {pcr:.3f} ({sentiment_full.get('pcr_sentiment', 'N/A')})\n"
                spx_chg = sentiment_full.get('spx_change')
                if spx_chg is not None:
                    sentiment_block += f"- S&P 500 当日涨跌: {spx_chg:+.2f}%\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时多源数据预测未来3个交易日的市场走势。

当前市场指数：
{index_context}
当前多源情绪信号：
{sentiment_block}
请结合多源信号给出未来3个交易日的预测（不要只看波动率！），格式如下：
T+1日|情绪预判|概率|市场走势
T+2日|情绪预判|概率|市场走势
T+3日|情绪预判|概率|市场走势

每行一个交易日，用|分隔。情绪预判用：乐观/中性偏多/中性/中性偏空/悲观。概率用百分比。市场走势用简短描述（不超过10字）。
注意：如果多源信号出现背离（如 VIX 低但 Put/Call 高 / 资金流大幅流出 / CNN 恐惧），请侧重价格与资金走向。

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

    def get_market_analysis(self, market, index_data, vix_val, sentiment_full=None):
        """使用LLM解读市场走势

        Args:
            market: 'hk' 或 'us'
            index_data: 指数数据dict {name: {price, change_pct}}
            vix_val: VIX/VHSI数值（向后兼容）
            sentiment_full: 2026-06-18 east 修复——多源综合情绪评分字典
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

        # 2026-06-18 east 修复：多源情绪上下文
        sentiment_lines = f"- 恐慌波动指数: {vix_val:.1f}\n"
        if sentiment_full:
            score = sentiment_full.get('sentiment_score', 50)
            label = sentiment_full.get('sentiment_label', 'N/A')
            sentiment_lines += f"- 多源综合情绪: {score:.0f}/100 ({label})\n"
            if market == 'hk':
                cf = sentiment_full.get('capital_flow')
                if cf is not None:
                    sentiment_lines += f"- 权重股资金净流: {cf:+.2f}亿 ({sentiment_full.get('flow_sentiment', 'N/A')})\n"
                wr = sentiment_full.get('bull_bear_ratio')
                if wr is not None:
                    sentiment_lines += f"- 牛熊证多空比: {wr:.3f} ({sentiment_full.get('warrant_sentiment', 'N/A')})\n"
            else:
                fg = sentiment_full.get('fear_greed')
                if fg is not None:
                    sentiment_lines += f"- CNN恐慌贪婪: {fg:.1f} ({sentiment_full.get('fg_sentiment', 'N/A')})\n"
                pcr = sentiment_full.get('option_ratio')
                if pcr is not None:
                    sentiment_lines += f"- 期权 P/C: {pcr:.3f} ({sentiment_full.get('pcr_sentiment', 'N/A')})\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时多源数据解读今日市场走势。

今日{market_name}指数表现：
{index_lines}
今日多源情绪信号：
{sentiment_lines}
请用2-3句话解读今日{market_name}市场走势，要点：
1. 整体趋势判断（上涨/下跌/震荡）+ 多源信号是否一致
2. 板块或风格特征（如有）
3. 对短期（1-3日）的展望

如果多源信号出现背离（VIX 低但 P/C 高 / 资金流出 / 恐惧），请明确指出。

直接回复分析内容，不要加标题。"""

        return self.call(prompt, max_tokens=300, temperature=0.4)

    def _format_enriched_positions(self, positions, max_n=8):
        """把 enrich 过的持仓渲染为 prompt 能读的多行文本
        兼容老格式（只有 symbol+pnl_pct）与新格式（含新闻/情绪/技术）。
        """
        if not positions:
            return '  无持仓'
        lines = []
        for p in positions[:max_n]:
            sym = p.get('symbol', '')
            pnl = p.get('pnl_pct', 0)
            head = f"  - {sym}: 浮盈{pnl:+.2f}%"
            extras = []
            d = p.get('days_held')
            if d is not None:
                extras.append(f"持有{d}天")
            rsi = p.get('rsi')
            if rsi is not None:
                try:
                    extras.append(f"RSI{float(rsi):.0f}")
                except Exception:
                    pass
            atr = p.get('atr')
            if atr is not None:
                try:
                    extras.append(f"ATR{float(atr):.2f}")
                except Exception:
                    pass
            ns = p.get('news_sentiment_24h')
            cnt = p.get('news_count_24h', 0)
            if cnt and cnt > 0 and ns is not None:
                emoji = '📈' if ns > 0.6 else '📉' if ns < 0.4 else '📊'
                extras.append(f"24h情绪 {emoji}{ns:.2f}({cnt}条)")
            if extras:
                head += ", " + ", ".join(extras)
            lines.append(head)
            top_news = p.get('top_news') or []
            shown = 0
            for n in top_news:
                s = n.get('sentiment', 0.5)
                if s > 0.6 or s < 0.4:
                    em = '📈' if s > 0.6 else '📉'
                    title = (n.get('title') or '')[:80]
                    lines.append(f"      {em} {title}")
                    shown += 1
                    if shown >= 2:
                        break
        return '\n'.join(lines)

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

        pos_list = self._format_enriched_positions(positions, max_n=8)

        prompt = f"""你是专业的风险管理分析师。请根据以下实时数据给出风险分析，重点关注“个股新闻利空”和“技术面走坏”的仓位。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请给出2-3条风险提示，优先提及：
- 某只持仓股 24h 情绪 ≤ 0.4（利空股）或出现明显负面新闻标题
- 某只持仓 RSI 过高/过低 或 价格偏离 MA 走坏
- 集中度/系统性/流动性三大风险

每条格式：风险等级|风险类型|具体描述|建议动作
- 风险等级用：🔴高/🟠中/🟡低
- 风险类型用：系统性/个股事件/集中度/流动性
- 描述必须提到具体股票代码或指标数据，不要空话
- 动作不超过15字

一行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=400, temperature=0.3)

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

        pos_list = self._format_enriched_positions(positions, max_n=8)

        prompt = f"""你是专业的交易策略顾问。请根据以下实时数据给出针对性操作建议，必须结合具体持仓股的新闻情绪和技术状况，有名有姓地说。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请给出3条操作建议，优先覆盖：
- 针对出现利空新闻或技术走坏的持仓股给"减仓/收紧止损"建议
- 针对情绪>0.6且技术面健康的持仓股给"持有/滑升止盈"建议
- 总仓位/现金调度，或某股超限制的调仓动作

每条格式：建议类型|具体建议
- 建议类型用：仓位管理/止损止盈/开仓机会/风险规避
- 具体建议必须提及股票代码或明确价格/比例，不超过25字

一行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=400, temperature=0.3)


    def get_combined_assessment(self, market_data):
        """一次调用同时生成"风险评估"和"操作建议"，让两块逻辑在 thinking 模型一次思考中保持一致。

        Returns:
            dict: {'risk_text': str, 'action_text': str}；失败返回两个都 None。
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix', 20)
        vhsi       = market_data.get('vhsi', 25)
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = self._format_enriched_positions(positions, max_n=8)

        prompt = f"""你是专业的风险管理与交易策略顾问。请基于下面的实时数据同时输出"风险评估"和"操作建议"，两部分必须逻辑一致——如果某股在 RISK 部分被识别为利空，ACTION 中不能给他"持有/加仓"建议；所有描述必须有名有姓提到具体股票代码或指标数据。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请严格按下面两段格式输出，不要任何多余文字：

###RISK###
风险等级|风险类型|具体描述|建议动作
风险等级|风险类型|具体描述|建议动作
（3~4条，优先报警：24h情绪≤0.4的持仓股 / 出现负面新闻标题的股 / RSI过高过低或价格偏离MA / 集中度/流动性风险。风险等级用🔴高/🟠中/🟡低；风险类型用 系统性/个股事件/集中度/流动性；动作≤15字）

###ACTION###
建议类型|具体建议
建议类型|具体建议
建议类型|具体建议
（3~4条，优先覆盖：针对 RISK 中点名的利空股给"减仓/收紧止损"；对情绪>0.6且技术面健康的股给"持有/滑升止盈"；总仓位/现金调度。建议类型用 仓位管理/止损止盈/开仓机会/风险规避；具体建议必须提股票代码或明确价格/比例，≤25字）
"""

        content = self.call(prompt, max_tokens=700, temperature=0.3)
        if not content:
            return {'risk_text': None, 'action_text': None}

        risk_text, action_text = self._split_combined(content)
        return {'risk_text': risk_text, 'action_text': action_text}

    @staticmethod
    def _split_combined(content):
        """从 ###RISK### / ###ACTION### 标签里切两段；标签缺失则整段当 risk。"""
        if not content:
            return None, None
        # 标准化
        text = content.replace('\r\n', '\n').strip()
        risk = action = None
        # 优先用 marker 切
        if '###ACTION###' in text:
            head, action = text.rsplit('###ACTION###', 1)
            if '###RISK###' in head:
                risk = head.split('###RISK###', 1)[1]
            else:
                risk = head
        elif '###RISK###' in text:
            risk = text.split('###RISK###', 1)[1]
        else:
            # 没标签，全当 risk 让上层 fallback
            risk = text
        risk = (risk or '').strip()
        action = (action or '').strip()
        return risk, action



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

        # 拉取该股最近 24h 新闻（最多 8 条）一起丢给 LLM
        recent_news = fetch_recent_news(symbol, hours=24, limit=8)
        market_data = dict(market_data)  # 避免修改调用方原始 dict
        market_data['recent_news'] = recent_news

        prompt = self._build_prompt(symbol, market_data)
        # 新闻带进来后token增加，max_tokens 抬到 800（推理模型 reasoning 占用大）
        content = self.client.call(prompt, max_tokens=800, temperature=0.3)

        if content:
            return self._parse(content, market_data)
        return self._fallback(market_data, "调用失败")

    def _build_prompt(self, symbol, data):
        market = data.get('market', 'us')
        market_name = '美股' if market == 'us' else '港股'

        recent_news = data.get('recent_news') or []
        news_block = format_news_block(recent_news)
        news_count = len(recent_news)

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
新闻情绪均值: {data.get('sentiment', 'N/A')}

最近24h相关新闻 ({news_count}条):
{news_block}

请结合技术面 + 上述新闻事件综合判断，给出：
1. 评分调整（-10到+10），按以下场景对号入座：

   🔴 减分场景（-3 到 -8）：
   - 涨幅已大但无新催化剂（已被透支）
   - 技术面无明显突破信号，横盘整理
   - 消息面利好已被市场充分定价
   - 成交量萎缩，动能减弱
   - 重大利空（诉讼/调查/召回/调低评级）请加大负分（-8 到 -10）

   🟢 加分场景（+3 到 +8）：
   - 财报超预期且市场反应不足
   - 机构集中上调目标价
   - 新业务/新订单/新政策直接受益
   - 技术突破配合成交量放大
   - 重大利好（超预期/回购/中标/获批）请加大正分（+8 到 +10）

   ⚪ 中性场景（0 到 ±2）：已涨过但仍在竞争市场、技术面中立、无明显驱动事件

2. 一句话理由（必须提及关键事件或技术信号，且与打分方向一致）。

⚠️ 判分原则：如果理由中出现“无突破/无明显/横盘/已被透支/动能减弱/涨过”等关键词，必须给负分；不要出现“理由偏弱但调整为正分”的矛盾情况。

格式：调整,理由
例如：+5,成交量放大且财报超预期
或：-7,被SEC调查且评级被下调
或：-4,涨过后技术面无突破且成交量萎缩

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


class LLMExitAnalyzer:
    """卖出/平仓 LLM 复盘分析器。

    输入：开仓快照 + 当前持仓快照 + 触发原因 + 技术指标快照 + 市场情绪。
    输出：动态的卖出原因（用人话讲清楚为什么亏/为什么赚 + 教训），
         作为飞书通知的"原因:"字段。
    """

    def __init__(self):
        self.client = LLMClient()

    def analyze(self, symbol, exit_data):
        """分析卖出原因

        Args:
            symbol: 股票代码
            exit_data: dict，期望字段：
                - market: us|hk
                - side: 'BUY'|'SELL'
                - stop_type: take_profit|max_loss_stop|tightened_atr_stop|...
                - entry_price, exit_price, pnl_pct
                - entry_time, exit_time, holding_days
                - entry_score, entry_reasons (开仓时的评分/理由)
                - rsi, ma20, ma50, atr, volume_ratio, macd_death_cross
                - vix, cnn_fg, sentiment, market_change_pct (市场环境)
                - raw_reason: 系统给出的原始标签('止盈'/'止损全平'/...)
        Returns:
            dict: { 'verdict': 一句话结论, 'detail': 多行复盘, 'lesson': 经验教训, 'llm_reason': 组合后供通知直接用 }
        """
        if not self.client.api_key or self.client.api_key.startswith("sk-xxx"):
            return self._exit_fallback(exit_data, "无API Key")

        prompt = self._build_exit_prompt(symbol, exit_data)
        content = self.client.call(prompt, max_tokens=400, temperature=0.3)
        if not content:
            return self._exit_fallback(exit_data, "LLM调用失败")
        return self._parse_exit(content, exit_data)

    def _build_exit_prompt(self, symbol, d):
        market_name = '美股' if d.get('market', 'us') == 'us' else '港股'
        stop_type_label = {
            'take_profit': '止盈',
            'max_loss_stop': '止损全平',
            'tightened_atr_stop': '收紧ATR止损',
            'staged_reduction': '分级减仓',
            'major_negative': '重大利空',
        }.get(d.get('stop_type', ''), d.get('raw_reason', '平仓'))

        # 2026-06-24 east 修复:
        #   - 区分入场上下文是否可用，缺失时明确告诉 LLM 不要臆测
        #   - 技术指标统一标注为「卖出时点」，避免被描述为入场量能
        entry_reasons_list = [r for r in (d.get('entry_reasons', []) or []) if r]
        entry_score = int(d.get('entry_score', 0) or 0)
        entry_ctx_ok = bool(d.get('entry_context_available')) or bool(entry_reasons_list) or entry_score > 0
        entry_reasons_text = '\n  '.join(entry_reasons_list) if entry_reasons_list else '(未记录，该持仓可能为外部同步或早期建仓老仓位)'
        entry_score_text = f"{entry_score} 分" if entry_score > 0 else '(未记录)'
        pnl_pct = d.get('pnl_pct', 0)
        is_profit = pnl_pct >= 0

        if entry_ctx_ok:
            entry_rule = '可在复盘中结合"入场评分/入场理由"判断入场是否合理。'
        else:
            entry_rule = ('⚠️ 本次未记录入场评分与入场理由（可能为外部同步/手工建仓老仓位）。'
                          '严禁臆测"入场量能偏弱/入场信号不足"等未知信息，'
                          '复盘只能基于卖出时点的技术快照、市场环境与系统止损规则。')

        def _show(v, suffix=''):
            return f"{v}{suffix}" if v is not None else 'N/A'
        rsi = d.get('exit_rsi', d.get('rsi'))
        ma20 = d.get('exit_ma20', d.get('ma20'))
        ma50 = d.get('exit_ma50', d.get('ma50'))
        atr = d.get('exit_atr', d.get('atr'))
        vol_ratio = d.get('exit_volume_ratio', d.get('volume_ratio'))
        macd_dc = d.get('exit_macd_death_cross', d.get('macd_death_cross'))
        vol_text = f"{vol_ratio}x" if vol_ratio is not None else 'N/A'

        return f"""你是一名严谨的{market_name}量化交易复盘师。请基于以下持仓数据，针对本次{stop_type_label}给出复盘分析。

标的: {symbol}（{market_name}）
触发动作: {stop_type_label}（系统原始原因: {d.get('raw_reason','')}）

== 持仓档案 ==
入场价: ${d.get('entry_price', 0):.2f}
卖出价: ${d.get('exit_price', 0):.2f}
盈亏: {pnl_pct:+.2f}%
持有天数: {d.get('holding_days', 0)} 天
入场评分: {entry_score_text}
入场理由:
  {entry_reasons_text}

== 入场上下文说明 ==
{entry_rule}

== 卖出时点技术快照（注意：下面指标是卖出时点，不是入场时点） ==
RSI: {_show(rsi)}
MA20/MA50: {_show(ma20)}/{_show(ma50)}
ATR: {_show(atr)}
成交量比率: {vol_text}
MACD死叉: {_show(macd_dc)}

== 市场环境快照 ==
VIX: {d.get('vix', 'N/A')}
CNN恐慌贪婪: {d.get('cnn_fg', 'N/A')}
大盘当日涨跌: {d.get('market_change_pct', 'N/A')}%
新闻情绪: {d.get('sentiment', 'N/A')}

复盘硬约束：
1. 只能基于上面明确给出的数据。出现 "N/A" 或 "(未记录)" 的字段，严禁猜测。
2. 上面技术指标是卖出时点的，不能被描述为"入场时量能"或"入场时MA"。
3. 若"入场上下文说明"提示记录缺失，请明确写出"入场上下文不可考"，不要虚构入场原因。
4. 禁止使用以下套话除非数据明确支持："入场量能偏弱""缺乏有效支撑""严格执行纪律""量价共振""日内短线敞口"。

请用中文按以下格式输出，每段不超过2句：
【结论】{'本次盈利的核心驱动' if is_profit else '本次亏损的核心原因'}（一句话，需引用具体数字或规则）
【复盘】结合卖出时点指标与市场环境给出原因分析（2句以内）
【教训】下次类似情况建议怎么改进策略（1句话，针对可验证的规则）

直接输出三段，不要其他多余文字。"""

    def _parse_exit(self, content, d):
        text = content.strip()
        verdict = detail = lesson = ''
        try:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith('【结论】'):
                    verdict = line.replace('【结论】', '').strip()
                elif line.startswith('【复盘】'):
                    detail = line.replace('【复盘】', '').strip()
                elif line.startswith('【教训】'):
                    lesson = line.replace('【教训】', '').strip()
        except Exception:
            pass

        if not verdict and not detail and not lesson:
            # 解析失败，原文兜底
            verdict = text[:120]

        combined = self._format_combined(d, verdict, detail, lesson)
        return {
            'verdict': verdict,
            'detail': detail,
            'lesson': lesson,
            'llm_reason': combined,
            'timestamp': datetime.now().isoformat(),
        }

    def _format_combined(self, d, verdict, detail, lesson):
        """组合成飞书通知里"原因:"字段直接展示的文字。"""
        raw = d.get('raw_reason', '平仓')
        parts = [f"🤖 {raw}"]
        if verdict:
            parts.append(f"📌 {verdict}")
        if detail:
            parts.append(f"🔍 {detail}")
        if lesson:
            parts.append(f"💡 {lesson}")
        return '\n'.join(parts)

    def _exit_fallback(self, d, reason):
        raw = d.get('raw_reason', '平仓')
        pnl = d.get('pnl_pct', 0)
        combined = f"🤖 {raw}\n📌 LLM复盘暂不可用（{reason}），盈亏 {pnl:+.2f}%"
        return {
            'verdict': '',
            'detail': '',
            'lesson': '',
            'llm_reason': combined,
            'timestamp': datetime.now().isoformat(),
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


def analyze_exit(symbol, exit_data):
    """便捷函数：分析卖出原因（auto-trader 卖出通知用）"""
    analyzer = LLMExitAnalyzer()
    result = analyzer.analyze(symbol, exit_data)
    print(f"\n🤖 LLM卖出复盘 - {symbol}")
    print(f"   结论: {result.get('verdict', '')}")
    print(f"   复盘: {result.get('detail', '')}")
    print(f"   教训: {result.get('lesson', '')}")
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
