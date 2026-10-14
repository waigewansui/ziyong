"""检查懂球帝近绩的 score 字段"""
import logging
logging.basicConfig(level=logging.INFO)

from modules.fetch_intel import get_intel

intel = get_intel('LASK林茨', '利物浦', '欧冠', match_id='54577317')

print("=" * 60)
print("主队近绩:")
for m in (intel.get('recent', {}).get('home', []) or []):
    print(f"  日期={m.get('date')} | 比分={m.get('score')} | 结果={m.get('result')} | 对手={m.get('opponent')}")

print()
print("客队近绩:")
for m in (intel.get('recent', {}).get('away', []) or []):
    print(f"  日期={m.get('date')} | 比分={m.get('score')} | 结果={m.get('result')} | 对手={m.get('opponent')}")

# 直接用 fetch_history 看
print()
print("=" * 60)
print("用 fetch_history 看原始数据:")
from modules.fetch_history import get_history
history = get_history('LASK林茨', '利物浦')
print(f"home_recent 条数: {len(history.get('home_recent', []) or [])}")
for m in (history.get('home_recent', []) or [])[:5]:
    print(f"  {m}")
print(f"away_recent 条数: {len(history.get('away_recent', []) or [])}")
for m in (history.get('away_recent', []) or [])[:5]:
    print(f"  {m}")
