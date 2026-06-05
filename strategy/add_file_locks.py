#!/usr/bin/env python3

import re

# 读取原文件
with open('auto-trader.py', 'r') as f:
    content = f.read()

# 为所有写入操作添加文件锁
# 匹配模式：with open(self.open_positions_file, 'w') as f:\n                json.dump
pattern = r'(with open\(self\.open_positions_file, \'w\'\) as f:\n\s+)(json\.dump\(.*?\))'

def add_fcntl(match):
    indent = match.group(1)
    json_dump = match.group(2)
    return f'import fcntl\n{indent}fcntl.flock(f.fileno(), fcntl.LOCK_EX)\n        {json_dump}'

# 执行替换
new_content = re.sub(pattern, add_fcntl, content)

# 写回文件
with open('auto-trader.py', 'w') as f:
    f.write(new_content)

print("✅ 文件锁已成功添加到所有写入操作")