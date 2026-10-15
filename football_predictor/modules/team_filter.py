"""球队/联赛过滤 — 只跑关心的比赛"""
from typing import List, Dict, Set


def filter_results(results: List[Dict],
                   teams: Set[str] = None,
                   leagues: Set[str] = None,
                   only_cold: bool = False) -> List[Dict]:
    """
    teams: 关注的队名（中文），命中主队或客队即保留
    leagues: 关注的联赛
    only_cold: 只看冷门
    """
    out = []
    for r in results:
        if only_cold and not r.get("冷门"):
            continue
        if leagues and r.get("联赛", "") not in leagues:
            continue
        if teams:
            vs = r.get("对阵", "")
            hit = any(t in vs for t in teams)
            if not hit:
                continue
        out.append(r)
    return out


# 预置热门队（供 UI 多选默认值）
POPULAR_TEAMS = [
    "曼联", "曼城", "利物浦", "阿森纳", "切尔西", "热刺",
    "皇马", "巴萨", "马竞",
    "国米", "AC米兰", "尤文",
    "拜仁", "多特",
    "巴黎",
]
