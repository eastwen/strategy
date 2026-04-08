#!/bin/bash
# 触发AI优化检查（在交易后调用）

cd /home/admin/.openclaw/workspace-stock

# 后台运行优化检查（不阻塞交易）
nohup python3 realtime-ai-optimizer.py > /dev/null 2>&1 &
