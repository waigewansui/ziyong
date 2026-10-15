"""
累计性能追踪 — 汇总历史结算，计算各玩法命中率 + 凯利模拟 ROI
"""
import os
import json
import logging
from glob import glob
from typing import Dict, Any

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "results"
)

PERF_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "performance.json"
)


def _load_all_results() -> list:
    all_settlements = []
    for path in sorted(glob(os.path.join(RESULTS_DIR, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                date_str = os.path.basename(path).replace(".json", "")
                for s in json.load(f):
                    s["_date"] = date_str
                    all_settlements.append(s)
        except Exception:
            continue
    return all_settlements


def compute_performance() -> Dict[str, Any]:
    settlements = _load_all_results()
    if not settlements:
        return {
            "总场次": 0,
            "各玩法": {},
            "凯利模拟": {
                "初始本金": 1000,
                "最终余额": 1000,
                "净盈亏": 0,
                "ROI": 0,
                "下注次数": 0,
                "命中次数": 0,
                "命中率": 0,
            },
        }

    plays = ["胜平负", "让球", "比分", "总进球", "半全场"]
    stats = {}
    for play in plays:
        valid = [s for s in settlements if s["命中"].get(play) is not None]
        hits = [s for s in valid if s["命中"][play]]
        stats[play] = {
            "有效场次": len(valid),
            "命中": len(hits),
            "命中率": round(len(hits) / len(valid), 4) if valid else 0,
        }

    # 凯利模拟（基于胜平负预测）
    bankroll = 1000.0
    bet_count = 0
    win_count = 0
    total_stake = 0.0

    for s in settlements:
        pick = s["预测"].get("胜平负", "")
        hit = s["命中"].get("胜平负")
        if not pick or hit is None:
            continue

        odds_map = s.get("真实赔率", {}) or {}
        try:
            odds = float(odds_map.get(pick, 0))
        except (ValueError, TypeError):
            odds = 0
        if odds <= 0:
            continue

        # 简化凯利：f* = (bp - q) / b  →  b=odds-1, p=置信度, q=1-p
        prob = float(s.get("置信度", 0.5))
        b = odds - 1.0
        f_star = (b * prob - (1 - prob)) / b if b > 0 else 0
        f_star = max(0, min(0.05, f_star))  # 最多 5% 资金

        stake = round(bankroll * f_star, 2)
        if stake <= 0:
            continue

        bet_count += 1
        total_stake += stake
        bankroll -= stake

        if hit:
            win_count += 1
            bankroll += stake * odds

    net = round(bankroll - 1000, 2)
    roi = round(net / 1000, 4)

    result = {
        "总场次": len(settlements),
        "各玩法": stats,
        "凯利模拟": {
            "初始本金": 1000,
            "最终余额": round(bankroll, 2),
            "净盈亏": net,
            "ROI": roi,
            "下注次数": bet_count,
            "命中次数": win_count,
            "命中率": round(win_count / bet_count, 4) if bet_count > 0 else 0,
            "累计投注": round(total_stake, 2),
        },
    }

    with open(PERF_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    k = result["凯利模拟"]
    logger.info(f"📈 累计性能: {result['总场次']} 场 | "
                f"胜平负命中率 {stats.get('胜平负', {}).get('命中率', 0):.2%} | "
                f"凯利 ROI {k['ROI']:.2%} ({k['净盈亏']})")

    return result


def load_performance() -> Dict:
    if not os.path.exists(PERF_PATH):
        return compute_performance()
    try:
        with open(PERF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return compute_performance()
