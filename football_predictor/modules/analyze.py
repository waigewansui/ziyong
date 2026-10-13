"""
多维度分析模块（V2 - 一致性修复版）
核心改进：先定比分，其他维度全部从比分推导，保证 5 个维度方向一致
"""
import math
import logging
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger(__name__)

WEIGHTS = {"history": 0.40, "intel": 0.30, "odds": 0.30}


# ========== 工具函数 ==========
def _safe_float(v, default=0.0) -> float:
    if v is None:
        return default
    try:
        if isinstance(v, str):
            v = v.replace("+", "").replace(" ", "").strip()
            if v in ("", "-", "—"):
                return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _normalize(probs: Dict[str, float]) -> Dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        return {"胜": 1/3, "平": 1/3, "负": 1/3}
    return {k: round(v / total, 4) for k, v in probs.items()}


def _remove_vig(oh: float, od: float, oa: float) -> Tuple[float, float, float]:
    if oh <= 0 or od <= 0 or oa <= 0:
        return 0.0, 0.0, 0.0
    ih, idd, ia = 1/oh, 1/od, 1/oa
    t = ih + idd + ia
    return round(ih/t, 4), round(idd/t, 4), round(ia/t, 4)


def _parse_score(score) -> Tuple[int, int]:
    """兼容 '2-1' / '2:1' / '2 - 1' / [2,1]"""
    if score is None:
        return 0, 0
    if isinstance(score, (list, tuple)) and len(score) >= 2:
        return int(score[0]), int(score[1])
    s = str(score).replace(":", "-").replace(" ", "")
    parts = s.split("-")
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 0, 0
    return 0, 0


def _pick(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return default


def poisson_probability(lam: float, k: int) -> float:
    if lam <= 0:
        return 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


# ========== 维度1：历史战绩 ==========
def calc_history_prob(history: Dict[str, Any], home: str, away: str) -> Dict[str, float]:
    h2h = history.get("h2h", {}) or {}
    pct = h2h.get("percent", {}) or {}
    if pct:
        win_pct = _safe_float(str(pct.get("win", "0")).replace("%", "")) / 100.0
        draw_pct = _safe_float(str(pct.get("draw", "0")).replace("%", "")) / 100.0
        lose_pct = _safe_float(str(pct.get("lose", "0")).replace("%", "")) / 100.0
        if win_pct + draw_pct + lose_pct > 0.5:
            h2h_win, h2h_draw, h2h_lose = win_pct, draw_pct, lose_pct
        else:
            h2h_win, h2h_draw, h2h_lose = _h2h_from_team(h2h, home)
    else:
        h2h_win, h2h_draw, h2h_lose = _h2h_from_team(h2h, home)

    home_rate = _recent_rate(history.get("home_recent", []))
    away_rate_reversed = _recent_rate_reversed(history.get("away_recent", []))

    win = h2h_win * 0.40 + home_rate[0] * 0.30 + away_rate_reversed[0] * 0.30
    draw = h2h_draw * 0.40 + home_rate[1] * 0.30 + away_rate_reversed[1] * 0.30
    lose = h2h_lose * 0.40 + home_rate[2] * 0.30 + away_rate_reversed[2] * 0.30

    return _normalize({"胜": win, "平": draw, "负": lose})


def _h2h_from_team(h2h: dict, home: str) -> Tuple[float, float, float]:
    team_a = h2h.get("team_A", {}) or {}
    team_b = h2h.get("team_B", {}) or {}
    a_name = _pick(team_a, "name", "team_name", default="")
    b_name = _pick(team_b, "name", "team_name", default="")

    if home and a_name and home in a_name:
        me = team_a
    elif home and b_name and home in b_name:
        me = team_b
    else:
        me = team_a

    my_win = _safe_float(_pick(me, "win", "win_count"))
    my_draw = _safe_float(_pick(me, "draw", "draw_count"))
    my_lose = _safe_float(_pick(me, "lose", "lose_count", "loss"))
    total = my_win + my_draw + my_lose

    if total <= 0:
        return 0.33, 0.33, 0.34
    return my_win / total, my_draw / total, my_lose / total


def _recent_rate(matches: List[dict]) -> Tuple[float, float, float]:
    if not matches:
        return 0.33, 0.33, 0.34
    w = d = l = 0
    for m in matches:
        r = _extract_result(m)
        if r == "win":
            w += 1
        elif r == "draw":
            d += 1
        elif r == "lose":
            l += 1
    n = max(1, w + d + l)
    return w / n, d / n, l / n


def _recent_rate_reversed(matches: List[dict]) -> Tuple[float, float, float]:
    if not matches:
        return 0.33, 0.33, 0.34
    w = d = l = 0
    for m in matches:
        r = _extract_result(m)
        if r == "win":
            l += 1
        elif r == "draw":
            d += 1
        elif r == "lose":
            w += 1
    n = max(1, w + d + l)
    return w / n, d / n, l / n


def _extract_result(m: dict) -> str:
    if not isinstance(m, dict):
        return ""
    r = _pick(m, "result", "color", "outcome", default="")
    if isinstance(r, str):
        r = r.lower().strip()
        if r in ("win", "w", "胜", "3"):
            return "win"
        if r in ("draw", "d", "平", "1"):
            return "draw"
        if r in ("lose", "loss", "l", "负", "0"):
            return "lose"
    return ""


# ========== 维度2：情报 ==========
def calc_intel_prob(intel: Dict[str, Any], home: str, away: str) -> Dict[str, float]:
    ranking = intel.get("ranking", {}) or {}
    home_rank = _safe_float(ranking.get("home_rank"))
    away_rank = _safe_float(ranking.get("away_rank"))
    home_points = _safe_float(ranking.get("home_points"))
    away_points = _safe_float(ranking.get("away_points"))

    sideline = intel.get("sideline", {}) or {}
    home_inj = len(sideline.get("home", []) or [])
    away_inj = len(sideline.get("away", []) or [])

    if home_rank > 0 and away_rank > 0:
        rank_score = max(-1.0, min(1.0, (away_rank - home_rank) / 20.0))
    else:
        rank_score = 0.0

    if home_points > 0 and away_points > 0:
        point_score = max(-1.0, min(1.0, (home_points - away_points) / 30.0))
    else:
        point_score = 0.0

    injury_score = max(-1.0, min(1.0, (away_inj - home_inj) / 5.0))

    if rank_score == 0 and point_score == 0 and injury_score == 0:
        return {"胜": 0.33, "平": 0.33, "负": 0.34}

    total_score = rank_score * 0.5 + point_score * 0.3 + injury_score * 0.2
    home_win = 0.40 + total_score * 0.30
    away_win = 0.40 - total_score * 0.30
    return _normalize({"胜": home_win, "平": 0.20, "负": away_win})


# ========== 维度3：赔率 ==========
def calc_odds_prob(intel: Dict[str, Any]) -> Dict[str, float]:
    odds = intel.get("odds", {}) or {}
    euro = odds.get("euro")

    avg = odds.get("avg", {}) or {}
    now = avg.get("now", {}) or {}
    oh = _safe_float(_pick(now, "homeWin", "home", "h"))
    od = _safe_float(_pick(now, "draw", "d"))
    oa = _safe_float(_pick(now, "awayWin", "away", "a"))

    if oh <= 0 and isinstance(euro, list) and euro:
        first = euro[0] if isinstance(euro[0], dict) else {}
        now2 = first.get("now", {}) or {}
        oh = _safe_float(_pick(now2, "homeWin", "home", "h"))
        od = _safe_float(_pick(now2, "draw", "d"))
        oa = _safe_float(_pick(now2, "awayWin", "away", "a"))

    if oh <= 0:
        begin = avg.get("begin", {}) or {}
        oh = _safe_float(_pick(begin, "homeWin", "home", "h"))
        od = _safe_float(_pick(begin, "draw", "d"))
        oa = _safe_float(_pick(begin, "awayWin", "away", "a"))

    if oh <= 0 or od <= 0 or oa <= 0:
        return {"胜": 0.33, "平": 0.33, "负": 0.34}

    p_h, p_d, p_a = _remove_vig(oh, od, oa)

    trend = intel.get("handicap_trend", {}) or {}
    direction = trend.get("direction", "")
    if direction == "主胜降赔":
        p_h = min(0.85, p_h * 1.05)
    elif direction == "主胜升赔":
        p_h = max(0.10, p_h * 0.95)

    return _normalize({"胜": p_h, "平": p_d, "负": p_a})


# ========== 融合 ==========
def fuse_probabilities(hp, ip, op) -> Dict:
    w = WEIGHTS
    win = hp["胜"]*w["history"] + ip["胜"]*w["intel"] + op["胜"]*w["odds"]
    draw = hp["平"]*w["history"] + ip["平"]*w["intel"] + op["平"]*w["odds"]
    lose = hp["负"]*w["history"] + ip["负"]*w["intel"] + op["负"]*w["odds"]
    d = {"胜": win, "平": draw, "负": lose}
    return {
        "胜": round(win, 4), "平": round(draw, 4), "负": round(lose, 4),
        "推荐": max(d, key=d.get),
    }


# ========== 让球（保留概率分布，用于后续置信度） ==========
def calc_handicap(wdl: Dict, handicap: float) -> Dict:
    h, d, a = wdl["胜"], wdl["平"], wdl["负"]
    if handicap < 0:
        return {
            "让胜": round(h*0.50, 4),
            "让平": round(h*0.30 + d*0.20, 4),
            "让负": round(h*0.20 + d*0.80 + a, 4),
        }
    elif handicap > 0:
        return {
            "让胜": round(h + d*0.50, 4),
            "让平": round(d*0.30 + a*0.30, 4),
            "让负": round(a*0.70, 4),
        }
    return {"让胜": h, "让平": d, "让负": a}


# ========== 比分（带胜平负方向筛选） ==========
def calc_score(history: Dict, wdl_recommendation: str = None) -> Dict[str, float]:
    def avg(matches):
        if not matches:
            return 1.2
        total, n = 0, 0
        for m in matches:
            h, a = _parse_score(_pick(m, "score", "scoreStr", "ft_score"))
            total += h + a
            n += 1
        return max(0.5, total / max(1, n))

    home_avg = avg(history.get("home_recent", [])) / 2
    away_avg = avg(history.get("away_recent", [])) / 2

    result = {}
    for h in range(6):
        for a in range(6):
            p = poisson_probability(home_avg, h) * poisson_probability(away_avg, a)
            result[f"{h}:{a}"] = round(p, 4)

    # ✅ 根据胜平负方向筛选
    if wdl_recommendation == "胜":
        filtered = {k: v for k, v in result.items()
                    if int(k.split(":")[0]) > int(k.split(":")[1])}
    elif wdl_recommendation == "负":
        filtered = {k: v for k, v in result.items()
                    if int(k.split(":")[0]) < int(k.split(":")[1])}
    elif wdl_recommendation == "平":
        filtered = {k: v for k, v in result.items()
                    if int(k.split(":")[0]) == int(k.split(":")[1])}
    else:
        filtered = result

    total = sum(filtered.values())
    if total > 0:
        filtered = {k: round(v/total, 4) for k, v in filtered.items()}
    else:
        filtered = {"1:0": 0.30, "2:0": 0.25, "2:1": 0.20, "1:1": 0.15, "0:0": 0.10}

    return filtered


# ========== 总进球（保留概率分布） ==========
def calc_total_goals(history: Dict) -> Dict[str, float]:
    def avg(matches):
        if not matches:
            return 1.2
        total, n = 0, 0
        for m in matches:
            h, a = _parse_score(_pick(m, "score", "scoreStr", "ft_score"))
            total += h + a
            n += 1
        return max(0.5, total / max(1, n))

    lam = avg(history.get("home_recent", [])) + avg(history.get("away_recent", []))
    return {f"{k}球": round(poisson_probability(lam, k), 4) for k in range(8)}


# ========== 半全场（保留概率分布） ==========
def calc_half_full(wdl: Dict) -> Dict[str, float]:
    h, d, a = wdl["胜"], wdl["平"], wdl["负"]
    return {
        "胜胜": round(h*0.55, 4), "平胜": round(h*0.30, 4), "负胜": round(h*0.15, 4),
        "平平": round(d*0.60, 4), "平负": round(a*0.30, 4), "负负": round(a*0.55, 4),
    }


# ========== ✅ 从比分推导其他维度（保证一致性） ==========
def derive_handicap_from_score(score_str: str, handicap: float) -> str:
    """从比分推导让球结果"""
    try:
        h, a = map(int, score_str.split(":"))
    except Exception:
        return "让胜"

    diff = h - a
    adjusted = diff + handicap

    if adjusted > 0:
        return "让胜"
    elif adjusted == 0:
        return "让平"
    else:
        return "让负"


def derive_total_from_score(score_str: str) -> str:
    """从比分推导总进球"""
    try:
        h, a = map(int, score_str.split(":"))
        return f"{h+a}球"
    except Exception:
        return "2球"


def derive_half_full_from_score(score_str: str, wdl: str) -> str:
    """从比分推导半全场（简化：假设半场平局，下半场分胜负）"""
    try:
        h, a = map(int, score_str.split(":"))
    except Exception:
        return "平胜"

    if wdl == "胜":
        return "平胜" if h == 1 else "胜胜"
    elif wdl == "负":
        return "平负"
    else:
        return "平平"


# ========== 主入口 ==========
def analyze_match(match: Dict[str, Any],
                  history: Dict[str, Any],
                  intel: Dict[str, Any]) -> Dict[str, Any]:
    home = match.get("主队", "")
    away = match.get("客队", "")
    handicap = _safe_float(match.get("让球", 0))

    # 1. 三源加权算胜平负
    hp = calc_history_prob(history, home, away)
    ip = calc_intel_prob(intel, home, away)
    op = calc_odds_prob(intel)
    wdl = fuse_probabilities(hp, ip, op)

    # 2. ✅ 先算比分（带胜平负方向约束）
    score_prob = calc_score(history, wdl_recommendation=wdl["推荐"])
    top_score = max(score_prob.items(), key=lambda x: x[1])
    score_str = top_score[0]

    # 3. ✅ 其他维度全部从比分推导
    handicap_pick = derive_handicap_from_score(score_str, handicap)
    total_pick = derive_total_from_score(score_str)
    hf_pick = derive_half_full_from_score(score_str, wdl["推荐"])

    # 4. 保留概率分布（用于 confidence / 展示）
    handicap_prob = calc_handicap(wdl, handicap)
    total_prob = calc_total_goals(history)
    hf_prob = calc_half_full(wdl)

    # 5. 置信度
    max_wdl = max(wdl["胜"], wdl["平"], wdl["负"])
    confidence = round(max_wdl * 0.6 + top_score[1] * 0.4, 4)

    return {
        "场次编号": match.get("场次编号", ""),
        "联赛": match.get("联赛", ""),
        "比赛时间": match.get("比赛时间", ""),
        "对阵": f"{home} vs {away}",
        "胜平负推荐": wdl["推荐"],
        "胜平负概率": {"胜": wdl["胜"], "平": wdl["平"], "负": wdl["负"]},
        "让球推荐": handicap_pick,
        "让球概率": handicap_prob,
        "比分推荐": score_str,
        "比分概率": score_prob,
        "总进球推荐": total_pick,
        "总进球概率": total_prob,
        "半全场推荐": hf_pick,
        "半全场概率": hf_prob,
        "置信度": confidence,
        "维度分解": {"历史": hp, "情报": ip, "赔率": op},
        "数据源": intel.get("source", "none"),
    }


# ========== 测试 ==========
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    mock_history = {
        "h2h": {"total": 4, "home_win": 2, "draw": 1, "away_win": 1},
        "home_recent": [{"result": "胜", "score": "2-0"}, {"result": "平", "score": "1-1"}],
        "away_recent": [{"result": "负", "score": "0-2"}, {"result": "平", "score": "1-1"}],
    }
    mock_intel = {
        "source": "dongqiudi",
        "ranking": {"home_rank": 5, "away_rank": 10, "home_points": 55, "away_points": 40},
        "sideline": {"home": [], "away": []},
        "odds": {"avg": {"now": {"homeWin": "1.80", "draw": "3.50", "awayWin": "4.20"}}},
        "handicap_trend": {"direction": "主胜降赔"},
    }
    match = {"场次编号": "001", "主队": "曼联", "客队": "利物浦", "联赛": "英超", "让球": -1}
    r = analyze_match(match, mock_history, mock_intel)
    print(json.dumps(r, ensure_ascii=False, indent=2))