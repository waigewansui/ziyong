"""
赛后结算 — 拉真实比分，对比预测，计算命中率
"""
import os
import json
import time
import random
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "results"
)

DONGQIUDI_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
}


def _parse_score(score_str: str):
    """ '2:1' / '2-1' → (2, 1) """
    if not score_str:
        return None, None
    try:
        parts = str(score_str).replace("-", ":").split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None


def fetch_real_result(match_id: str, home: str, away: str) -> Optional[Dict]:
    """
    拉取真实比分
    优先 match_id → 其次队名搜索
    """
    # 方法 1：match_id 直拉
    if match_id and str(match_id).isdigit():
        try:
            url = f"https://api.dongqiudi.com/mobile/match/analysis/{match_id}"
            time.sleep(random.uniform(0.3, 0.6))
            r = requests.get(url, headers=DONGQIUDI_MOBILE_HEADERS, timeout=8)
            if r.status_code == 200:
                info = r.json().get("info", {})
                score = info.get("score") or info.get("final_score")
                if score:
                    h, a = _parse_score(score)
                    if h is not None:
                        return {"home_score": h, "away_score": a,
                                "score_str": score, "source": "match_id"}
        except Exception:
            pass

    # 方法 2：懂球帝搜索（主队关键词）
    try:
        time.sleep(random.uniform(0.3, 0.6))
        r = requests.get(
            "http://api.dongqiudi.com/search",
            params={"keywords": home, "type": "all", "page": 1},
            headers=DONGQIUDI_MOBILE_HEADERS,
            timeout=8,
        )
        if r.status_code == 200:
            for item in (r.json().get("matches", {}).get("data", []) or []):
                if item.get("status") in ("Finished", "finished", "FT", "结束"):
                    score = item.get("score", "")
                    h, a = _parse_score(score)
                    if h is not None:
                        return {"home_score": h, "away_score": a,
                                "score_str": score, "source": "search"}
    except Exception:
        pass

    return None


def _classify_wdl(hs: int, aws: int) -> str:
    return "胜" if hs > aws else ("平" if hs == aws else "负")


def _classify_handicap(hs: int, aws: int, hc: float) -> str:
    diff = (hs - aws) + hc
    if diff > 0:
        return "让胜"
    elif diff == 0:
        return "让平"
    return "让负"


def settle_one(pred: Dict, real: Dict, handicap: float = 0.0) -> Dict:
    """结算单场"""
    hs, aws = real["home_score"], real["away_score"]
    total = hs + aws

    actual = {
        "胜平负": _classify_wdl(hs, aws),
        "让球": _classify_handicap(hs, aws, handicap),
        "比分": f"{hs}:{aws}",
        "总进球": f"{total}球",
        "半全场": "",  # 无半场比分时跳过
    }

    hits = {}
    for play in ["胜平负", "让球", "比分", "总进球", "半全场"]:
        pred_pick = pred.get(f"{play}推荐", "")
        hits[play] = (pred_pick == actual[play]) if pred_pick and actual[play] else None

    return {
        "场次编号": pred.get("场次编号", ""),
        "对阵": pred.get("对阵", ""),
        "预测": {
            "胜平负": pred.get("胜平负推荐", ""),
            "让球": pred.get("让球推荐", ""),
            "比分": pred.get("比分推荐", ""),
            "总进球": pred.get("总进球推荐", ""),
            "半全场": pred.get("半全场推荐", ""),
        },
        "实际": actual,
        "命中": hits,
        "置信度": pred.get("置信度", 0),
        "真实赔率": pred.get("真实赔率", {}),
    }


def settle_batch(date_str: str) -> Dict:
    """批量结算某日所有预测"""
    from modules.prediction_recorder import load_predictions

    preds = load_predictions(date_str)
    if not preds:
        logger.warning(f"未找到 {date_str} 的预测快照")
        return {}

    logger.info(f"🔍 开始结算 {date_str}：{len(preds)} 场")
    settlements = []

    for pred in preds:
        match_str = pred.get("对阵", "")
        if " vs " not in match_str:
            continue
        home, away = match_str.split(" vs ", 1)

        # ✅ 优先从快照读真实让球盘口
        handicap = 0.0
        raw_handicap = pred.get("让球", "")
        if raw_handicap:
            try:
                handicap = float(str(raw_handicap).replace("+", "").strip())
            except (ValueError, TypeError):
                handicap = 0.0

        # 兜底：快照没有让球字段时，从赔率反推
        if handicap == 0.0:
            real_odds = pred.get("真实赔率", {}) or {}
            try:
                h_odds = float(real_odds.get("胜", 0))
                a_odds = float(real_odds.get("负", 0))
                if h_odds > 0 and a_odds > 0:
                    handicap = -1.0 if h_odds < a_odds else 1.0
            except Exception:
                pass

        real = fetch_real_result(pred.get("场次编号", ""), home, away)
        if not real:
            logger.warning(f"  ⚠️ {match_str} 未能获取真实比分")
            continue

        stl = settle_one(pred, real, handicap)
        settlements.append(stl)

        wdl = stl["命中"]["胜平负"]
        logger.info(f"  ✓ {match_str} → {real['score_str']} | "
                    f"胜平负{'✅' if wdl else '❌' if wdl is False else '—'}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settlements, f, ensure_ascii=False, indent=2)

    # 当天总结
    if settlements:
        wdl_hits = sum(1 for s in settlements if s["命中"].get("胜平负") is True)
        wdl_valid = sum(1 for s in settlements if s["命中"].get("胜平负") is not None)
        logger.info(f"📊 {date_str} 结算完成: {wdl_hits}/{wdl_valid} = "
                    f"{wdl_hits/wdl_valid:.2%}" if wdl_valid else "📊 结算完成")

    return {"date": date_str, "settlements": settlements, "path": path}
