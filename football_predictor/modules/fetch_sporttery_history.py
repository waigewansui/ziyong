"""
体彩官网历史赛果抓取 — 官方 getUniformMatchResultV1 接口
接口来源：浏览器 Network 面板抓取的真实请求
JSON 结构：value.matchInfoList[].subMatchList[]
"""
import os
import json
import time
import random
import logging
import requests
from datetime import datetime, timedelta
import calendar

logger = logging.getLogger(__name__)

API_URL = "https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry"

HEADERS = {
    "authority": "webapi.sporttery.cn",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/87.0.4280.88 Safari/537.36"),
    "origin": "https://www.lottery.gov.cn",
    "referer": "https://www.lottery.gov.cn/",
    "accept-language": "zh-CN,zh;q=0.9,zh-TW;q=0.8",
}

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "sporttery_history"
)

# 只抓需要的玩法，减小响应体
POOL_CODES = "had,hhad"  # 胜平负 + 让球胜平负（按需可加 crs,ttg,hafu）


def _extract_match(sm: dict, date_str: str) -> dict:
    """
    从 matchResult 单条提取字段
    
    实际 JSON 结构（扁平字段，不是嵌套 had/hhad）:
      sm["h"]=主胜赔率 sm["d"]=平赔率 sm["a"]=客胜赔率
      sm["goalLine"]=让球数 sm["winFlag"]=H/D/A (赛果)
      sm["matchResultStatus"]="2" (已结算)
      无 fullScore/halfScore — 只有胜平负赛果
    """
    win_flag = sm.get("winFlag", "")
    result_map = {"H": "胜", "D": "平", "A": "负"}

    return {
        "日期": sm.get("matchDate", date_str),
        "场次编号": sm.get("matchNumStr", ""),
        "联赛": sm.get("leagueNameAbbr", "") or sm.get("leagueName", ""),
        "主队": sm.get("allHomeTeam", "") or sm.get("homeTeam", ""),
        "客队": sm.get("allAwayTeam", "") or sm.get("awayTeam", ""),
        "让球": str(sm.get("goalLine", "") or ""),
        "胜平负结果": result_map.get(win_flag, ""),
        "胜赔": sm.get("h", ""),
        "平赔": sm.get("d", ""),
        "负赔": sm.get("a", ""),
        "matchResultStatus": sm.get("matchResultStatus", ""),
        "poolStatus": sm.get("poolStatus", ""),
    }


def fetch_range(date_from: str, date_to: str,
                max_pages: int = 30) -> list[dict]:
    """抓指定日期范围的赛果（自动翻页）"""
    all_matches = []
    page_no = 1
    prev_match_nums = []

    while page_no <= max_pages:
        params = {
            "matchBeginDate": date_from,
            "matchEndDate": date_to,
            "leagueId": "",
            "pageSize": 30,
            "pageNo": page_no,
            "isFix": 0,
            "matchPage": page_no,
            "pcOrWap": 1,
        }
        try:
            time.sleep(random.uniform(0.8, 1.5))
            resp = requests.get(API_URL, params=params,
                                headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"第 {page_no} 页请求失败: {e}")
            break

        # 从 value.matchResult[] 提取（扁平结构，单页所有比赛直接在一个 list 里）
        value = data.get("value", {}) or {}
        match_list = value.get("matchResult") or []

        page_count = 0
        page_match_nums = []
        for sm in match_list:
            all_matches.append(_extract_match(sm, date_from))
            page_match_nums.append(sm.get("matchNumStr", ""))
            page_count += 1

        logger.info(f"  P{page_no}: {page_count} 场")

        # 翻页判断
        if page_count < 30:
            break

        # 如果连续两页返回完全相同的场次列表（API 不翻页），说明到底了
        if page_no >= 2 and set(page_match_nums) == set(prev_match_nums or []):
            logger.info(f"  API 不再翻页（连续重复），提前结束")
            break
        prev_match_nums = page_match_nums

        page_no += 1

    return all_matches


def fetch_one_year(months_back: int = 12) -> list[dict]:
    """按月分批抓一年"""
    end = datetime.now()
    all_matches = []

    for i in range(months_back):
        ref = end - timedelta(days=30 * i)
        first = ref.replace(day=1)
        last = ref.replace(
            day=calendar.monthrange(ref.year, ref.month)[1])
        d1 = first.strftime("%Y-%m-%d")
        d2 = last.strftime("%Y-%m-%d")

        logger.info(f"[{i+1}/{months_back}] {d1} ~ {d2}")
        try:
            matches = fetch_range(d1, d2)
            all_matches.extend(matches)
            logger.info(f"  本月 {len(matches)} 场，累计 {len(all_matches)}")
        except Exception as e:
            logger.warning(f"  本月失败: {e}")

        time.sleep(random.uniform(2.0, 4.0))

    # 去重
    seen, uniq = set(), []
    for m in all_matches:
        key = (m.get("日期"), m.get("场次编号"))
        if key not in seen:
            seen.add(key)
            uniq.append(m)

    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(
        CACHE_DIR,
        f"history_{end.strftime('%Y-%m-%d')}_1year.json"
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(uniq, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 保存 {len(uniq)} 场 → {path}")
    return uniq


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    fetch_one_year(months_back=12)
