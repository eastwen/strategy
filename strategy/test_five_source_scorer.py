#!/usr/bin/env python3
import unittest
from unittest.mock import Mock, patch

from feishu_pusher import FeishuPusher
from llm_stock_analyzer import (
    LLMStockAnalyzer,
    _futu_titles_similar,
    fetch_futu_digest,
    format_digest_block,
)
from four_source_scorer import (
    _announce_futu,
    _aggregate_community_evidence,
    _aggregate_deduped_news,
    _aggregate_institution_evidence,
    _aggregate_official_evidence,
    _event_strength,
    _futu_query_aliases,
    _is_futu_query_relevant,
    _is_company_relevant,
    _ratio_event_strength,
    _score_capital_metrics,
    _score_event_records,
    score_all,
)


def article_source(source, title, sentiment=0.5):
    return {
        'available': True,
        'raw': {
            'source': source,
            'articles': [{'title': title, 'sentiment': sentiment}],
        },
    }


class FiveSourceScoringTest(unittest.TestCase):
    def test_futu_rewritten_title_dedupe(self):
        self.assertTrue(_futu_titles_similar(
            'KeyBanc将美光科技的目标价调整至$1,750，此前为$1,600，维持超配评级',
            'KeyBanc：将美光科技(MU.O)目标价从1,600美元上调至1,750美元。',
        ))

    def test_event_type_not_keyword_count_controls_strength(self):
        concise = _event_strength('Company receives new order')
        noisy = _event_strength(
            'Company receives new order as growth, profit and demand improve'
        )

        self.assertEqual(concise['positive_event_type'], 'contract_order')
        self.assertEqual(concise['positive_strength'], 0.45)
        self.assertEqual(noisy['positive_strength'], concise['positive_strength'])

    def test_negative_actions_do_not_reuse_historical_positive_words(self):
        cases = (
            ('Company loses major contract', 'major_contract'),
            ('Company says new contract cancelled', 'contract_order'),
            ('Company says merger agreement terminated', 'corporate_transaction'),
            ('Broker downgrades stock from buy rating to hold', 'analyst_rating'),
        )

        for title, event_type in cases:
            with self.subTest(title=title):
                result = _event_strength(title)
                self.assertEqual(result['positive_strength'], 0)
                self.assertGreater(result['negative_strength'], 0)
                self.assertEqual(result['negative_event_type'], event_type)

        upgrade = _event_strength('Broker upgrades stock from sell rating to buy')
        self.assertGreater(upgrade['positive_strength'], 0)
        self.assertEqual(upgrade['negative_strength'], 0)

    def test_rumor_is_discounted_but_clarification_is_not(self):
        rumor = _event_strength('Company reportedly wins major contract')
        clarification = _event_strength('Company denies bankruptcy rumor')

        self.assertEqual(rumor['positive_event_type'], 'major_contract')
        self.assertEqual(rumor['positive_strength'], 0.4)
        self.assertEqual(rumor['certainty_multiplier'], 0.4)
        self.assertEqual(clarification['positive_event_type'], 'clarification')
        self.assertEqual(clarification['positive_strength'], 0.25)
        self.assertEqual(clarification['negative_strength'], 0)
        self.assertEqual(clarification['certainty_multiplier'], 1.0)

    def test_structured_ratio_uses_fixed_event_tiers(self):
        self.assertEqual(_ratio_event_strength(0.20), 1.0)
        self.assertEqual(_ratio_event_strength(-0.09), 0.75)
        self.assertEqual(_ratio_event_strength(0.04), 0.45)
        self.assertEqual(_ratio_event_strength(-0.02), 0.25)
        self.assertEqual(_ratio_event_strength(0.005), 0.0)

    def test_event_pool_combines_every_distinct_deduped_event(self):
        records = [
            {'title': 'Company maintains buy rating', 'source': 'a'},
            {'title': 'Broker upgrades stock', 'source': 'b'},
            {'title': 'Company wins contract', 'source': 'c'},
            {'title': 'Company wins contract!', 'source': 'd'},
        ]
        result = _score_event_records(
            records, 25, '国际资讯', '合并去重资讯 24h', combine_all_events=True
        )
        official_style = _aggregate_official_evidence([{
            'available': True,
            'raw': {'source': 'test', 'articles': records},
        }], 20)

        # 三条独立事件均参与；相似标题的重复订单只保留一条。
        self.assertEqual(result['score'], 22)
        self.assertEqual(len(result['raw']['positive_event_types']), 3)
        # 官方公告和国际资讯都使用全事件聚合，但各自按满分计算。
        self.assertEqual(official_style['score'], 18)

    @patch('llm_stock_analyzer.requests.get')
    def test_futu_digest_is_deduped_and_left_for_current_llm(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            'code': 0,
            'data': [
                {
                    'title': '<em>NVIDIA</em> wins major AI contract',
                    'url': 'https://example.test/1',
                },
                {
                    'title': 'NVIDIA wins major AI contract!',
                    'url': 'https://example.test/duplicate',
                },
                {
                    'title': 'NVIDIA launches new platform',
                    'url': 'https://example.test/2',
                },
            ],
        }
        get.return_value = response

        digest = fetch_futu_digest('US.NVDA', 'us', size=10)

        self.assertEqual(digest['direction'], 'pending_llm')
        self.assertEqual(len(digest['signals']), 2)
        self.assertNotIn('<em>', digest['signals'][0])
        self.assertIn('合并重复报道后保留2个事件', digest['conclusion'])
        self.assertIn('https://example.test/1', format_digest_block(digest))

    @patch('llm_stock_analyzer.requests.get')
    def test_futu_short_ticker_filters_false_matches_but_keeps_aliases(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            'code': 0,
            'data': [
                {'title': '美光科技(<em>MU</em>.O)上涨3.5%', 'url': 'https://example.test/1'},
                {'title': '美光科技发布最新产品', 'url': 'https://example.test/2'},
                {'title': 'Verano举办MÜV新店开业庆典', 'url': 'https://example.test/noise'},
            ],
        }
        get.return_value = response

        digest = fetch_futu_digest(
            'US.MU', 'us', size=10, company_name='Micron Technology Inc.'
        )

        self.assertEqual(len(digest['signals']), 2)
        self.assertTrue(all('Verano' not in title for title in digest['signals']))
        self.assertEqual(digest['filtered_out'], 1)

    def test_score_all_exposes_neutral_contract(self):
        def dimension(score, cap):
            return {
                'score': score,
                'available': True,
                'evidence': '真实证据',
                'neutral_score': cap / 2,
                'score_adjustment': score - cap / 2,
                'raw': {},
            }

        with (
            patch('four_source_scorer.score_international_news', return_value=dimension(13, 25)),
            patch('four_source_scorer.score_official_announce', return_value=dimension(10, 20)),
            patch('four_source_scorer.score_community', return_value=dimension(12, 25)),
            patch('four_source_scorer.score_institution', return_value=dimension(10, 20)),
            patch('four_source_scorer.score_capital_anomaly', return_value=dimension(5, 10)),
        ):
            result = score_all('TEST', 'us')

        self.assertEqual(result['score_total'], 50)
        self.assertEqual(result['neutral_total'], 50)
        self.assertEqual(result['score_adjustment_total'], 0)
        self.assertEqual(
            result['scoring_semantics'],
            'merged_evidence_neutral_midpoint_v2',
        )
        self.assertEqual(result['company_name'], '')

    def test_source_outage_and_duplicate_do_not_change_news_score(self):
        event = article_source(
            'source_a',
            'Company beats estimates and raises guidance',
        )
        duplicate = article_source(
            'source_b',
            'Company beats estimates and raises guidance',
        )
        unavailable = {
            'available': False,
            'score': 0,
            'raw': {'source': 'source_c'},
        }

        single = _aggregate_deduped_news([event], 25)
        combined = _aggregate_deduped_news([event, duplicate, unavailable], 25)

        self.assertEqual(single['score'], 25)
        self.assertEqual(combined['score'], single['score'])
        self.assertEqual(combined['raw']['duplicates_removed'], 1)

    def test_company_relevance_rejects_broad_feed_false_positive(self):
        self.assertTrue(_is_company_relevant(
            'Apple Stock Downgraded on iPhone Weakness',
            'AAPL',
            'Apple Inc.',
        ))
        self.assertFalse(_is_company_relevant(
            'TSMC seen riding AI boom to record profit',
            'AAPL',
            'Apple Inc.',
        ))
        self.assertTrue(_is_company_relevant(
            '苹果股票获得罕见的看跌评级',
            'AAPL',
            '',
            ['苹果', 'Apple'],
        ))

    @patch('four_source_scorer._news_futu')
    def test_official_futu_does_not_fallback_to_general_news(self, news_futu):
        news_futu.return_value = {
            'available': False,
            'score': 0,
            'raw': {'reason': '无公告'},
        }

        result = _announce_futu('AAPL', 20)

        self.assertFalse(result['available'])
        news_futu.assert_called_once_with(
            'AAPL', 20, news_type=2, hours=168, company_name=''
        )

    def test_five_source_futu_short_ticker_relevance(self):
        items = [
            {'title': '美光科技(<em>MU</em>.O)上涨3.5%'},
            {'title': '美光科技发布最新产品'},
            {'title': 'Verano举办MÜV新店开业庆典'},
        ]
        aliases = _futu_query_aliases(items, 'MU', 'Micron Technology Inc.')

        self.assertIn('美光科技', aliases)
        self.assertTrue(_is_futu_query_relevant(
            items[0]['title'], 'MU', 'Micron Technology Inc.', aliases
        ))
        self.assertTrue(_is_futu_query_relevant(
            items[1]['title'], 'MU', 'Micron Technology Inc.', aliases
        ))
        self.assertFalse(_is_futu_query_relevant(
            items[2]['title'], 'MU', 'Micron Technology Inc.', aliases
        ))

    def test_neutral_news_count_does_not_dilute_major_event(self):
        major = article_source(
            'source_a',
            'Company beats estimates and raises guidance',
        )
        neutral = {
            'available': True,
            'raw': {
                'source': 'source_b',
                'articles': [
                    {'title': f'Neutral company update {index}', 'sentiment': 0.5}
                    for index in range(40)
                ],
            },
        }

        self.assertEqual(_aggregate_deduped_news([major], 25)['score'], 25)
        self.assertEqual(_aggregate_deduped_news([major, neutral], 25)['score'], 25)

    def test_extreme_model_sentiment_alone_is_not_a_major_event(self):
        generic = article_source(
            'news_db',
            'Company publishes a routine business update',
            sentiment=1.0,
        )
        major = article_source(
            'news_db',
            'Company beats estimates and raises guidance',
            sentiment=1.0,
        )

        self.assertLess(_aggregate_deduped_news([generic], 25)['score'], 25)
        self.assertEqual(_aggregate_deduped_news([major], 25)['score'], 25)

    def test_major_negative_is_below_neutral(self):
        result = _aggregate_deduped_news([
            article_source(
                'source_a',
                'Company misses estimates and cuts guidance',
            )
        ], 25)

        self.assertEqual(result['score'], 0)
        self.assertEqual(result['neutral_score'], 12.5)
        self.assertEqual(result['score_adjustment'], -12.5)

    def test_official_events_are_merged_before_one_score(self):
        event = article_source(
            'sec',
            'Company beats estimates and raises guidance',
        )
        duplicate = article_source(
            'futu',
            'Company beats estimates and raises guidance',
        )

        single = _aggregate_official_evidence([event], 20)
        combined = _aggregate_official_evidence([event, duplicate], 20)

        self.assertEqual(single['score'], 20)
        self.assertEqual(combined['score'], single['score'])
        self.assertEqual(combined['raw']['duplicates_removed'], 1)

    def test_community_merges_records_without_source_average(self):
        bullish = {
            'available': True,
            'raw': {
                'source': 'futu_comment',
                'count': 20,
                'bull': 20,
                'bear': 0,
                'neutral': 0,
            },
        }
        bearish = {
            'available': True,
            'raw': {
                'source': 'futu_comment',
                'count': 20,
                'bull': 0,
                'bear': 20,
                'neutral': 0,
            },
        }
        unavailable = {'available': False, 'raw': {'source': 'other'}}

        self.assertEqual(
            _aggregate_community_evidence([bullish], 25)['score'],
            _aggregate_community_evidence([bullish, unavailable], 25)['score'],
        )
        self.assertGreater(
            _aggregate_community_evidence([bullish], 25)['score'],
            _aggregate_community_evidence([bearish], 25)['score'],
        )

    def test_duplicate_consensus_api_is_not_an_extra_vote(self):
        finnhub = {
            'available': True,
            'raw': {
                'source': 'finnhub_recommendation',
                'strong_buy': 10,
                'buy': 10,
                'hold': 5,
                'sell': 0,
                'strong_sell': 0,
            },
        }
        yfinance = {
            'available': True,
            'raw': {
                'source': 'yfinance',
                'rec': 'strong_buy',
                'total': 25,
            },
        }

        single = _aggregate_institution_evidence([finnhub], 20)
        combined = _aggregate_institution_evidence([finnhub, yfinance], 20)

        self.assertEqual(combined['score'], single['score'])
        self.assertTrue(combined['raw']['yfinance_consensus_ignored_as_duplicate'])

    def test_capital_score_is_symmetric(self):
        bullish = _score_capital_metrics(0.5, 3, -0.5, 10)
        bearish = _score_capital_metrics(-0.5, -3, 0.5, 10)

        self.assertEqual(bullish['score'], 10)
        self.assertEqual(bearish['score'], 0)
        self.assertEqual(bullish['score'] + bearish['score'], 10)

    def test_feishu_notification_displays_adjustment(self):
        pusher = object.__new__(FeishuPusher)
        messages = []
        pusher.send_message = lambda content: messages.append(content) or True

        pusher.send_buy_notification(
            symbol='US.TEST',
            quantity=1,
            price=100,
            amount=100,
            target_take_profit=None,
            target_stop_loss=None,
            score_total=75,
            score_news=25,
            score_announce=10,
            score_community=13,
            score_institution=20,
            score_capital=7,
            signal_type='测试',
            llm_conclusion='测试结论',
            order_id='TEST',
            timestamp='2026-07-15 00:00:00',
            score_adjustments={
                'news': 12.5,
                'announce': 0,
                'community': 0.5,
                'institution': 10,
                'capital': 2,
            },
        )

        self.assertIn('国际资讯: 25/25 (较中性+12.5)', messages[0])
        self.assertIn('官方公告: 10/20 (较中性+0.0)', messages[0])

    def test_llm_prompt_uses_neutral_semantics(self):
        analyzer = object.__new__(LLMStockAnalyzer)
        prompt = analyzer._build_prompt(
            'US.TEST',
            {
                'market': 'us',
                'base_score': 75,
                'price': 100,
                'change_pct': 1.0,
                'score_news': 25,
                'score_announce': 10,
                'score_community': 13,
                'score_institution': 20,
                'score_capital': 7,
                'neutral_news': 12.5,
                'neutral_announce': 10,
                'neutral_community': 12.5,
                'neutral_institution': 10,
                'neutral_capital': 5,
                'adjust_news': 12.5,
                'adjust_announce': 0,
                'adjust_community': 0.5,
                'adjust_institution': 10,
                'adjust_capital': 2,
                'available_news': True,
                'available_announce': True,
                'available_community': True,
                'available_institution': True,
                'available_capital': True,
                'evidence_news': '真实资讯证据',
                'recent_news': [],
            },
        )

        self.assertIn('五源约50分为中性', prompt)
        self.assertIn('资讯25/25（中性12.5，较中性+12.5）', prompt)
        self.assertIn('国际资讯: 真实资讯证据', prompt)

        legacy_prompt = analyzer._build_prompt(
            'US.TEST',
            {'market': 'us', 'price': 100, 'change_pct': 0, 'recent_news': []},
        )
        self.assertIn('资讯未覆盖', legacy_prompt)

    def test_llm_prompt_analyzes_futu_news_in_the_same_pass(self):
        analyzer = object.__new__(LLMStockAnalyzer)
        prompt = analyzer._build_prompt(
            'US.NVDA',
            {
                'market': 'us',
                'price': 100,
                'change_pct': 1.0,
                'futu_digest': {
                    'direction': 'pending_llm',
                    'conclusion': '富途事件池',
                    'signals': ['NVIDIA wins major AI contract'],
                    'evidence': ['NVIDIA wins major AI contract (https://example.test/1)'],
                },
            },
        )

        self.assertIn('富途新闻事件池（由本次LLM分析方向与影响）', prompt)
        self.assertIn('NVIDIA wins major AI contract', prompt)
        self.assertIn('不要沿用标题关键词数量作为结论', prompt)

    def test_llm_adjustment_accepts_ten_point_bounds(self):
        analyzer = object.__new__(LLMStockAnalyzer)
        data = {'symbol': 'US.TEST', 'base_score': 80}

        self.assertEqual(analyzer._parse('{"adjust":10,"reason":"重大利好确认"}', data)['final_score'], 90)
        self.assertEqual(analyzer._parse('{"adjust":-10,"reason":"重大利空确认"}', data)['final_score'], 70)
        rejected = analyzer._parse('{"adjust":11,"reason":"超出范围"}', data)
        self.assertFalse(rejected['passed'])
        self.assertEqual(rejected['score_adjust'], 0)

    @patch('llm_stock_analyzer.fetch_futu_digest')
    def test_llm_reuses_second_layer_news_without_refetching_futu(self, fetch_digest):
        analyzer = object.__new__(LLMStockAnalyzer)
        analyzer.client = Mock(api_key='configured')
        analyzer.client.call.return_value = (
            '{"adjust":2,"reason":"订单催化与技术面改善形成正向影响，但需防范波动风险"}'
        )

        result = analyzer.analyze(
            'US.NVDA',
            {
                'symbol': 'US.NVDA',
                'market': 'us',
                'base_score': 75,
                'price': 100,
                'change_pct': 1.0,
                'second_layer_news_events': [{
                    'title': 'NVIDIA wins major AI contract',
                    'positive_strength': 1.0,
                    'negative_strength': 0.0,
                    'sources': ['futu'],
                }],
            },
        )

        self.assertEqual(result['final_score'], 77)
        fetch_digest.assert_not_called()
        prompt = analyzer.client.call.call_args.args[0]
        self.assertIn('第二层国际资讯事件池（与评分同源', prompt)
        self.assertIn('NVIDIA wins major AI contract', prompt)

    @patch('llm_stock_analyzer.fetch_futu_digest')
    def test_futu_news_uses_one_normal_llm_call(self, fetch_digest):
        fetch_digest.return_value = {
            'direction': 'pending_llm',
            'conclusion': '富途事件池',
            'signals': ['NVIDIA wins major AI contract'],
            'evidence': [],
        }
        analyzer = object.__new__(LLMStockAnalyzer)
        analyzer.client = Mock(api_key='configured')
        analyzer.client.call.return_value = (
            '{"adjust":3,"reason":"订单催化与成交量确认形成正向影响，但需防范利好已部分计价"}'
        )

        result = analyzer.analyze(
            'US.NVDA',
            {
                'symbol': 'US.NVDA',
                'company_name': 'NVIDIA Corp.',
                'market': 'us',
                'base_score': 75,
                'price': 100,
                'change_pct': 1.0,
            },
        )

        self.assertEqual(result['final_score'], 78)
        self.assertEqual(analyzer.client.call.call_count, 1)
        prompt = analyzer.client.call.call_args.args[0]
        self.assertIn('NVIDIA wins major AI contract', prompt)


if __name__ == '__main__':
    unittest.main()
