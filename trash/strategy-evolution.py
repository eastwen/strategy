#!/usr/bin/env python3
"""
策略自我进化模块
每日复盘：统计评分准确性，调整权重参数
"""

import os
import json
from datetime import datetime, date, timedelta
from typing import Dict, List

class StrategyEvolution:
    """策略自我进化"""
    
    def __init__(self):
        self.evolution_log = "/home/admin/.openclaw/workspace-arashi/memory/evolution-log.json"
        self.weights_log = "/home/admin/.openclaw/workspace-arashi/memory/weights-history.json"
        
    def load_evolution_data(self) -> Dict:
        """加载进化数据"""
        if os.path.exists(self.evolution_log):
            with open(self.evolution_log, 'r') as f:
                return json.load(f)
        return {
            "created": datetime.now().strftime("%Y-%m-%d"),
            "version": "1.0",
            "daily_stats": [],
            "factor_performance": {
                "news": {"correct": 0, "total": 0},
                "technical": {"correct": 0, "total": 0},
                "sentiment": {"correct": 0, "total": 0}
            },
            "current_weights": {
                "hk": {"news": 0.30, "technical": 0.35, "sentiment": 0.35},
                "us": {"news": 0.35, "technical": 0.40, "sentiment": 0.25}
            }
        }
    
    def save_evolution_data(self, data: Dict):
        """保存进化数据"""
        with open(self.evolution_log, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def record_trade_result(self, market: str, scores: Dict, result: str, pnl_ratio: float):
        """
        记录交易结果
        
        Args:
            market: hk/us
            scores: {"news": 75, "technical": 80, "sentiment": 65, "total": 73}
            result: "win"/"loss"
            pnl_ratio: 盈亏比例
        """
        data = self.load_evolution_data()
        
        # 记录每日统计
        daily_stat = {
            "date": date.today().strftime("%Y-%m-%d"),
            "market": market,
            "scores": scores,
            "result": result,
            "pnl_ratio": pnl_ratio
        }
        data["daily_stats"].append(daily_stat)
        
        # 更新因子表现
        for factor in ["news", "technical", "sentiment"]:
            score = scores.get(factor, 50)
            # 高分交易成功 = 因子正确
            if score >= 70 and result == "win":
                data["factor_performance"][factor]["correct"] += 1
            elif score >= 70 and result == "loss":
                pass  # 高分但失败
            data["factor_performance"][factor]["total"] += 1
        
        self.save_evolution_data(data)
    
    def calculate_factor_accuracy(self) -> Dict:
        """计算各因子准确率"""
        data = self.load_evolution_data()
        accuracy = {}
        
        for factor, perf in data["factor_performance"].items():
            if perf["total"] > 0:
                accuracy[factor] = perf["correct"] / perf["total"]
            else:
                accuracy[factor] = 0.5  # 默认50%
        
        return accuracy
    
    def evolve_weights(self, market: str) -> Dict:
        """
        根据因子表现调整权重
        
        规则：
        - 准确率高的因子增加权重（最多+5%）
        - 准确率低的因子减少权重（最多-5%）
        - 权重总和保持100%
        """
        data = self.load_evolution_data()
        accuracy = self.calculate_factor_accuracy()
        
        current = data["current_weights"][market].copy()
        
        print(f"\n📊 {market.upper()} 策略权重进化")
        print(f"当前权重: {current}")
        print(f"因子准确率: {accuracy}")
        
        # 计算调整
        adjustments = {}
        total_adjustment = 0
        
        for factor in ["news", "technical", "sentiment"]:
            acc = accuracy[factor]
            if acc > 0.6:
                adjustment = 0.01 * min(5, int((acc - 0.5) * 10))  # 最多+5%
            elif acc < 0.4:
                adjustment = -0.01 * min(5, int((0.5 - acc) * 10))  # 最多-5%
            else:
                adjustment = 0
            adjustments[factor] = adjustment
            total_adjustment += adjustment
        
        # 归一化调整（确保总和为0）
        if total_adjustment != 0:
            for factor in adjustments:
                adjustments[factor] -= total_adjustment / 3
        
        # 应用调整
        for factor in current:
            current[factor] = round(current[factor] + adjustments[factor], 2)
            current[factor] = max(0.15, min(0.50, current[factor]))  # 限制范围
        
        # 再次归一化
        total = sum(current.values())
        for factor in current:
            current[factor] = round(current[factor] / total, 2)
        
        # 保存新权重
        data["current_weights"][market] = current
        self.save_evolution_data(data)
        
        print(f"调整后权重: {current}")
        
        return current
    
    def generate_evolution_report(self) -> str:
        """生成进化报告"""
        data = self.load_evolution_data()
        accuracy = self.calculate_factor_accuracy()
        
        report = f"""# 策略自我进化报告
日期: {datetime.now().strftime("%Y-%m-%d")}
版本: {data["version"]}

## 一、因子准确率

| 因子 | 准确率 | 交易次数 |
|------|--------|----------|
| 资讯面 | {accuracy['news']*100:.1f}% | {data['factor_performance']['news']['total']} |
| 技术面 | {accuracy['technical']*100:.1f}% | {data['factor_performance']['technical']['total']} |
| 情绪面 | {accuracy['sentiment']*100:.1f}% | {data['factor_performance']['sentiment']['total']} |

## 二、当前权重配置

### 港股
| 因子 | 权重 |
|------|------|
| 资讯面 | {data['current_weights']['hk']['news']*100:.0f}% |
| 技术面 | {data['current_weights']['hk']['technical']*100:.0f}% |
| 情绪面 | {data['current_weights']['hk']['sentiment']*100:.0f}% |

### 美股
| 因子 | 权重 |
|------|------|
| 资讯面 | {data['current_weights']['us']['news']*100:.0f}% |
| 技术面 | {data['current_weights']['us']['technical']*100:.0f}% |
| 情绪面 | {data['current_weights']['us']['sentiment']*100:.0f}% |

## 三、进化建议

"""
        
        # 根据准确率给出建议
        for factor, acc in accuracy.items():
            if acc > 0.6:
                report += f"- {factor}因子表现优秀（{acc*100:.1f}%），建议增加权重\n"
            elif acc < 0.4:
                report += f"- {factor}因子表现欠佳（{acc*100:.1f}%），建议减少权重或优化模型\n"
            else:
                report += f"- {factor}因子表现正常（{acc*100:.1f}%），维持当前配置\n"
        
        return report


if __name__ == "__main__":
    evolution = StrategyEvolution()
    
    # 测试记录交易
    evolution.record_trade_result(
        market="hk",
        scores={"news": 75, "technical": 80, "sentiment": 65, "total": 73},
        result="win",
        pnl_ratio=0.05
    )
    
    # 进化权重
    evolution.evolve_weights("hk")
    evolution.evolve_weights("us")
    
    # 生成报告
    print(evolution.generate_evolution_report())
