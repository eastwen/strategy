import json
import unittest
from unittest.mock import patch

from llm_stock_analyzer import LLMClient


class Response:
    status_code = 200
    text = ''

    def json(self):
        return {'choices': [{'message': {
            'content': '',
            'reasoning_content': '分析过程\n{"passed":true,"adjust":6}\n结束',
        }}]}


class LLMReasoningTest(unittest.TestCase):
    def test_dots_budget_and_complete_json(self):
        client = LLMClient()
        client.api_key = 'test-key'
        with patch('llm_stock_analyzer.requests.post', return_value=Response()) as post:
            ok, content = client._try_one('dots3-note-prev', 'test', 200, 0.3)
        self.assertTrue(ok)
        self.assertEqual(json.loads(content)['adjust'], 6)
        self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 800)

    def test_regular_model_keeps_budget(self):
        client = LLMClient()
        client.api_key = 'test-key'
        with patch('llm_stock_analyzer.requests.post', return_value=Response()) as post:
            client._try_one('regular-chat-model', 'test', 200, 0.3)
        self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 200)


if __name__ == '__main__':
    unittest.main()
