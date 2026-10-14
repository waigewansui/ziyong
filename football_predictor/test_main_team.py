"""dump 懂球帝近绩的真实字段结构"""
import logging
import json
logging.basicConfig(level=logging.INFO)

from modules.fetch_intel import dongqiudi_analysis

# 用罗马 vs 皇马 的 match_id
analysis = dongqiudi_analysis("54577200")

recent = analysis.get("recent_record", {}) or {}

print("=" * 70)
print("recent_record 顶层 keys:", list(recent.keys()))
print("=" * 70)

for side in ["team_A", "team_B"]:
    matches = recent.get(side, [])
    if not isinstance(matches, list):
        print(f"\n❌ {side} 不是 list: {type(matches)}")
        continue

    print(f"\n{'='*70}")
    print(f"{side} — 共 {len(matches)} 场")
    print("=" * 70)

    for i, m in enumerate(matches[:3]):
        print(f"\n--- 第 {i+1} 场 ---")
        for key, val in m.items():
            if isinstance(val, str) and len(val) > 50:
                val = val[:50] + "..."
            print(f"  {key}: {val}")
