"""
预测记录器 — 保存每日预测快照，供赛后结算
"""
import os
import json
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

PREDICTIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "predictions"
)


def save_predictions(results: List[Dict], date_str: str = None) -> str:
    """保存每日预测快照"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)

    path = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")

    snapshot = []
    for r in results:
        snapshot.append({
            "场次编号": r.get("场次编号", ""),
            "联赛": r.get("联赛", ""),
            "对阵": r.get("对阵", ""),
            "比赛时间": r.get("比赛时间", ""),
            "让球": r.get("让球", ""),
            "胜平负推荐": r.get("胜平负推荐", ""),
            "胜平负概率": r.get("胜平负概率", {}),
            "让球推荐": r.get("让球推荐", ""),
            "让球概率": r.get("让球概率", {}),
            "比分推荐": r.get("比分推荐", ""),
            "总进球推荐": r.get("总进球推荐", ""),
            "半全场推荐": r.get("半全场推荐", ""),
            "置信度": r.get("置信度", 0),
            "真实赔率": r.get("真实赔率", {}),
            "真实赔率_让球": r.get("真实赔率_让球", {}),
            "真实赔率_比分": r.get("真实赔率_比分", {}),
            "真实赔率_总进球": r.get("真实赔率_总进球", {}),
            "真实赔率_半全场": r.get("真实赔率_半全场", {}),
            "数据源": r.get("数据源", "none"),
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info(f"📝 预测快照已保存: {path} ({len(snapshot)} 场)")
    return path


def load_predictions(date_str: str) -> List[Dict]:
    """读取指定日期的预测快照"""
    path = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取预测快照失败: {e}")
        return []
