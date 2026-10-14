"""
投注记录 + 收益跟踪
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

BETS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "bets.json"
)


def load_bets() -> List[Dict]:
    if not os.path.exists(BETS_PATH):
        return []
    try:
        with open(BETS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_bets(bets: List[Dict]):
    os.makedirs(os.path.dirname(BETS_PATH), exist_ok=True)
    with open(BETS_PATH, "w", encoding="utf-8") as f:
        json.dump(bets, f, ensure_ascii=False, indent=2)


def add_bet(match_id: str, pick: str, stake: float,
            odds: float, note: str = "") -> Dict:
    """添加一笔投注"""
    bets = load_bets()
    bet = {
        "id": f"{match_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "match_id": match_id,
        "pick": pick,
        "stake": stake,
        "odds": odds,
        "result": "pending",   # pending / win / lose / push
        "profit": 0.0,
        "note": note,
    }
    bets.append(bet)
    save_bets(bets)
    logger.info(f"投注已记录: {match_id} {pick} {stake}元 @ {odds}")
    return bet


def settle_bet(bet_id: str, result: str):
    """结算投注（win/lose/push）"""
    bets = load_bets()
    for b in bets:
        if b["id"] == bet_id:
            b["result"] = result
            if result == "win":
                b["profit"] = round(b["stake"] * (b["odds"] - 1), 2)
            elif result == "lose":
                b["profit"] = -b["stake"]
            else:
                b["profit"] = 0.0
            save_bets(bets)
            logger.info(f"结算: {bet_id} → {result} 盈亏{b['profit']}")
            return b
    return None


def summary() -> Dict[str, Any]:
    """总体收益统计"""
    bets = load_bets()
    settled = [b for b in bets if b["result"] != "pending"]
    if not settled:
        return {"总笔数": len(bets), "已结算": 0, "总投入": 0,
                "净盈亏": 0, "ROI": 0, "命中率": 0}

    total_stake = sum(b["stake"] for b in settled)
    total_profit = sum(b["profit"] for b in settled)
    wins = sum(1 for b in settled if b["result"] == "win")

    return {
        "总笔数": len(bets),
        "已结算": len(settled),
        "总投入": round(total_stake, 2),
        "净盈亏": round(total_profit, 2),
        "ROI": round(total_profit / total_stake, 4) if total_stake > 0 else 0,
        "命中率": round(wins / len(settled), 4),
    }
