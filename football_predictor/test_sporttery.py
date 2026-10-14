"""dump 体彩 API 返回的真实字段"""
import requests
import json
from datetime import datetime, timedelta

# 拉今天+明天，保证有比赛
today = datetime.now().strftime("%Y-%m-%d")
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

url = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
params = {
    "matchBeginDate": today,
    "matchEndDate": tomorrow,
    "pageNo": 1,
    "pageSize": 10,
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sporttery.cn/",
}

r = requests.get(url, params=params, headers=headers, timeout=15)
data = r.json()

match_list = data.get("value", {}).get("matchInfoList", [])
if not match_list:
    print("无比赛数据")
    exit()

# 遍历所有比赛，找一场有 crs/ttg/hafu 的
found = False
for m in match_list:
    for sub in m.get("subMatchList", []):
        if "crs" in sub and sub["crs"]:
            print("=" * 60)
            print(f"比赛：{sub.get('homeTeamAbbName')} vs {sub.get('awayTeamAbbName')}")
            print(f"场次：{sub.get('matchNumStr')}")
            print("=" * 60)

            for key in ["had", "hhad", "crs", "ttg", "hafu"]:
                if key in sub and sub[key]:
                    print(f"\n【{key}】:")
                    print(json.dumps(sub[key], ensure_ascii=False, indent=2))
                else:
                    print(f"\n❌ 缺字段：{key}")
            found = True
            break
    if found:
        break

if not found:
    print("所有比赛都没有 crs/ttg/hafu 字段")
    print("说明：比分/总进球/半全场赔率还没开售")
    print("\n第一场比赛的字段：")
    print(list(match_list[0]["subMatchList"][0].keys()))
