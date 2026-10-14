"""
裁判数据模块
数据源：懂球帝 match analysis（如果有）+ 本地缓存
"""
import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# 裁判数据库（本地维护，可按赛季更新）
REFEREE_DB = {
    # 英超
    "Michael Oliver": {"avg_cards": 4.2, "avg_pens": 0.28, "strict": "严"},
    "Anthony Taylor": {"avg_cards": 3.8, "avg_pens": 0.22, "strict": "中"},
    # 西甲
    "Jesus Gil Manzano": {"avg_cards": 5.5, "avg_pens": 0.35, "strict": "严"},
    # 意甲
    "Daniele Orsato": {"avg_cards": 4.0, "avg_pens": 0.30, "strict": "中"},
    # 德甲
    "Felix Brych": {"avg_cards": 3.5, "avg_pens": 0.20, "strict": "中"},
    # 欧冠
    "Szymon Marciniak": {"avg_cards": 4.5, "avg_pens": 0.25, "strict": "中"},
}


def fetch_referee(match_id: str, intel: dict) -> Dict[str, Any]:
    """
    从 intel 里提取裁判，然后查数据库
    """
    if not intel:
        return {"available": False}

    # 尝试从 intel.info 里找裁判字段
    info = intel.get("info", {}) or {}
    referee_name = (
        info.get("referee") or
        info.get("referee_name") or
        ""
    )

    if not referee_name:
        return {"available": False, "name": ""}

    # 查数据库
    profile = REFEREE_DB.get(referee_name, {
        "avg_cards": 4.0,
        "avg_pens": 0.25,
        "strict": "中",
    })

    result = {
        "available": True,
        "name": referee_name,
        **profile,
        "impact": "",
    }

    # 影响分析
    if profile["avg_cards"] >= 5.0:
        result["impact"] = "严哨→红牌/点球多"
        result["goal_factor"] = 1.10
    elif profile["avg_cards"] <= 3.5:
        result["impact"] = "宽哨→比赛流畅"
        result["goal_factor"] = 0.95
    else:
        result["goal_factor"] = 1.0

    logger.info(f"  🟨 裁判 {referee_name}: {result['impact']}")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    print(json.dumps(fetch_referee("test", {"info": {"referee": "Michael Oliver"}}),
                     ensure_ascii=False, indent=2))
