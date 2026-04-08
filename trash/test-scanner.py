#!/usr/bin/env python3
"""测试智能扫描器"""

import sys
import importlib.util

print("开始测试...", flush=True)

# 手动加载模块
spec = importlib.util.spec_from_file_location("smart_scanner_v2", "/home/admin/.openclaw/workspace-arashi/smart-scanner-v2.py")
module = importlib.util.module_from_spec(spec)

# 需要先设置路径
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi')

spec.loader.exec_module(module)

print("创建调度器...", flush=True)
scheduler = module.SmartSchedulerV2()

print(f"港股: {len(scheduler.hk_stocks)}只", flush=True)
print(f"美股: {len(scheduler.us_stocks)}只", flush=True)

print("\n测试交易日判断:", flush=True)
should_hk, reason_hk = scheduler.should_scan('hk')
should_us, reason_us = scheduler.should_scan('us')

print(f"港股: {should_hk} ({reason_hk})", flush=True)
print(f"美股: {should_us} ({reason_us})", flush=True)

print("\n测试完成！", flush=True)