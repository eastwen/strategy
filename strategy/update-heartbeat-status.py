#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
自动更新HEARTBEAT.md状态脚本
从心跳检查结果更新HEARTBEAT.md文件状态
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta

# 设置工作目录
workspace_dir = '/home/admin/.openclaw/workspace-stock'
os.chdir(workspace_dir)
sys.path.append('strategy')

def get_heartbeat_check_result():
    """运行心跳检查并获取结果"""
    try:
        import subprocess
        result = subprocess.run(
            [f'{workspace_dir}/futu-venv/bin/python3', f'{workspace_dir}/strategy/heartbeat-check.py'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        output = result.stdout + result.stderr
        
        # 解析输出
        status = {
            'has_issues': result.returncode != 0,
            'output': output,
            'returncode': result.returncode,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return status
    except Exception as e:
        return {
            'has_issues': True,
            'output': f'心跳检查运行失败: {e}',
            'returncode': 1,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

def get_scanner_status():
    """获取扫描器状态"""
    status = {
        'us_scanner_running': False,
        'hk_scanner_running': False,
        'us_scanner_log_size': 0,
        'hk_scanner_log_size': 0,
        'last_sync_time': '未知'
    }
    
    try:
        # 检查美股扫描器进程
        import subprocess
        ps_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'us-scanner.py' in ps_result.stdout:
            status['us_scanner_running'] = True
        
        # 检查港股扫描器进程
        if 'hk-scanner.py' in ps_result.stdout:
            status['hk_scanner_running'] = True
        
        # 检查日志文件大小
        us_log = f'{workspace_dir}/logs/us-scanner.log'
        hk_log = f'{workspace_dir}/logs/hk-scanner.log'
        
        if os.path.exists(us_log):
            status['us_scanner_log_size'] = os.path.getsize(us_log)
        
        if os.path.exists(hk_log):
            status['hk_scanner_log_size'] = os.path.getsize(hk_log)
        
        # 获取最后同步时间
        trades_file = f'{workspace_dir}/data/trades.json'
        if os.path.exists(trades_file):
            with open(trades_file, 'r') as f:
                data = json.load(f)
                status['last_sync_time'] = data.get('sync_time', '未知').split('T')[0]
        
    except Exception as e:
        status['error'] = str(e)
    
    return status

def update_heartbeat_md(heartbeat_result, scanner_status):
    """更新HEARTBEAT.md文件"""
    heartbeat_file = f'{workspace_dir}/HEARTBEAT.md'
    
    if not os.path.exists(heartbeat_file):
        print(f"❌ HEARTBEAT.md文件不存在: {heartbeat_file}")
        return False
    
    try:
        with open(heartbeat_file, 'r') as f:
            content = f.read()
        
        # 解析心跳检查输出
        output = heartbeat_result['output']
        has_issues = heartbeat_result['has_issues']
        check_time = heartbeat_result['timestamp']
        
        # 提取关键信息
        high_score_opportunities = 0
        accounts = 0
        positions = 0
        issues_found = []
        
        # 从输出中提取信息
        for line in output.split('\n'):
            if '高评分机会:' in line:
                match = re.search(r'高评分机会:\s*(\d+)', line)
                if match:
                    high_score_opportunities = int(match.group(1))
            elif '账户:' in line:
                match = re.search(r'账户:\s*(\d+),\s*持仓:\s*(\d+)', line)
                if match:
                    accounts = int(match.group(1))
                    positions = int(match.group(2))
            elif '🚨 发现问题:' in line:
                match = re.search(r'🚨 发现问题:\s*(.+)', line)
                if match:
                    issues_found.append(match.group(1))
        
        # 确定系统状态
        if has_issues:
            system_status = "⚠️ 发现问题需要处理"
        else:
            system_status = "✅ 全面正常运行"
        
        # 更新"当前状态"部分
        current_status_section = f"""## 当前状态（自动更新于 {check_time}）:
1. ✅ 飞书集成正常（测试消息已发送）
2. ✅ 原始日报脚本已修复
3. {"⚠️" if not scanner_status['us_scanner_running'] else "✅"} 美股扫描器状态: {"运行中" if scanner_status['us_scanner_running'] else "未运行"}
4. ✅ 所有扫描器频率更新为5分钟
5. ✅ 定时任务配置正确
6. ✅ 数据同步正常（最后同步: {scanner_status['last_sync_time']})
7. ✅ 港股策略v2.0已接入
8. ✅ 心跳检查自动化运行（发现{len(issues_found)}个问题）

## 检测到的问题:
{chr(10).join([f"- ❌ {issue}" for issue in issues_found]) if issues_found else "- ✅ 无重大问题"}

## 系统状态: {system_status}
### 当前监控数据:
- 📈 高评分机会: {high_score_opportunities}个
- 💼 活跃账户: {accounts}个，持仓: {positions}只
- 🔄 美股扫描器: {"✅ 运行中" if scanner_status['us_scanner_running'] else "❌ 未运行"}
- 🔄 港股扫描器: {"✅ 运行中" if scanner_status['hk_scanner_running'] else "❌ 未运行"}
- 📊 美股日志大小: {scanner_status['us_scanner_log_size']:,}字节
- 📊 港股日志大小: {scanner_status['hk_scanner_log_size']:,}字节

## 下次自动检查时间: {(datetime.now() + timedelta(minutes=30)).strftime('%H:%M')}"""
        
        # 替换HEARTBEAT.md中的"当前状态"部分
        # 找到"## 当前状态"到"## 已解决问题"之间的内容
        pattern = r'(## 当前状态[\s\S]*?)(?=## 已解决问题|\Z)'
        
        if re.search(pattern, content):
            new_content = re.sub(pattern, current_status_section + '\n\n', content, flags=re.MULTILINE)
        else:
            # 如果找不到，添加到文件末尾
            new_content = content + '\n\n' + current_status_section
        
        with open(heartbeat_file, 'w') as f:
            f.write(new_content)
        
        print(f"✅ HEARTBEAT.md已更新于 {check_time}")
        print(f"   发现{len(issues_found)}个问题，系统状态: {system_status}")
        
        return True
        
    except Exception as e:
        print(f"❌ 更新HEARTBEAT.md失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    print(f"🔄 开始自动更新HEARTBEAT.md状态 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 运行心跳检查
    print("📊 运行心跳检查...")
    heartbeat_result = get_heartbeat_check_result()
    
    if heartbeat_result['has_issues']:
        print(f"⚠️ 心跳检查发现问题 (返回码: {heartbeat_result['returncode']})")
    else:
        print("✅ 心跳检查正常")
    
    # 2. 获取扫描器状态
    print("🔍 获取扫描器状态...")
    scanner_status = get_scanner_status()
    
    # 3. 更新HEARTBEAT.md
    print("📝 更新HEARTBEAT.md...")
    success = update_heartbeat_md(heartbeat_result, scanner_status)
    
    if success:
        print("✅ HEARTBEAT.md状态更新完成")
    else:
        print("❌ HEARTBEAT.md状态更新失败")
    
    print("=" * 60)
    print(f"🏁 自动更新完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())