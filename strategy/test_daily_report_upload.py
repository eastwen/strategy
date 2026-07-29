"""Regression tests for safe Feishu daily-report uploads."""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    'daily_report_to_feishu', ROOT / 'daily-report-to-feishu.py'
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class DailyReportUploadTest(unittest.TestCase):
    @patch.object(subprocess, 'run')
    def test_markdown_is_passed_without_shell_expansion(self, run):
        content = '| 初始资金 | $1,000,000.00 |\n| 总资产 | $998,428.41 |'
        run.return_value = Mock(
            stdout=json.dumps({'ok': True, 'data': {'doc_url': 'https://example.test'}}),
            stderr='',
            returncode=0,
        )

        result = REPORT.create_feishu_doc('测试日报', content)

        self.assertEqual(result, 'https://example.test')
        args = run.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertEqual(args[args.index('--markdown') + 1], content)
        self.assertNotIn('shell', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
