"""
多维度分析模块 V4
新增：
- 联赛细分权重（方向4）
- 平局专项模型（方向5）
- 主客分离建模（方向6）
- 天气因子（方向7）
- 裁判因子（方向8）
- 非线性放大（偏离1/3的幅度×1.5）
"""
import math
import logging
from typing import Dict, Any, List, Tuple, Optional

from modules.team_name_resolver import get_resolver

logger = logging.getLogger(__name__)


# ========== 方向4：联赛细分权重 ==========
DEFAULT_WEIGHTS = {"history": 0.40, "intel": 0.30, "odds": 0.30}

# 联赛场均进球（用于"对手防守强度"归一化）
LEAGUE_AVG_GOALS = {
    "英超": 1.40, "西甲": 1.25, "意甲": 1.30,
    "德甲": 1.50, "法甲": 1.25,
    "欧冠": 1.35, "欧联": 1.30,
    "亚冠": 1.20, "亚冠精英": 1.20, "亚冠乙": 1.20,
    "英冠": 1.30, "日联赛杯": 1.30,
    "解放者杯": 1.15, "美职": 1.40,
    "荷甲": 1.55, "葡超": 1.25,
}
DEFAULT_LEAGUE_AVG = 1.30

LEAGUE_WEIGHTS = {
    "欧冠":   {"history": 0.20, "intel": 0.20, "odds": 0.60},
    "欧联":   {"history": 0.20, "intel": 0.20, "odds": 0.60},
    "英超":   {"history": 0.30, "intel": 0.30, "odds": 0.40},
    "西甲":   {"history": 0.30, "intel": 0.30, "odds": 0.40},
    "意甲":   {"history": 0.30, "intel": 0.30, "odds": 0.40},
    "德甲":   {"history": 0.30, "intel": 0.30, "odds": 0.40},
    "法甲":   {"history": 0.30, "intel": 0.30, "odds": 0.40},
    "亚冠":   {"history": 0.50, "intel": 0.30, "odds": 0.20},
    "亚冠精英": {"history": 0.50, "intel": 0.30, "odds": 0.20},
    "亚冠乙": {"history": 0.50, "intel": 0.30, "odds": 0.20},
    "英冠":   {"history": 0.40, "intel": 0.20, "odds": 0.40},
    "日联赛杯": {"history": 0.50, "intel": 0.30, "odds": 0.20},
    "解放者杯": {"history": 0.50, "intel": 0.20, "odds": 0.30},
    "美职":   {"history": 0.40, "intel": 0.30, "odds": 0.30},
}


def get_weights(league: str) -> Dict[str, float]:
    return LEAGUE_WEIGHTS.get(league, DEFAULT_WEIGHTS)


# ========== 通用工具 ==========
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


def _remove_vig(oh, od, oa):
    if oh <= 0 or od <= 0 or oa <= 0:
        return 0.0, 0.0, 0.0
    ih, idd, ia = 1/oh, 1/od, 1/oa
    t = ih + idd + ia
    return round(ih/t, 4), round(idd/t, 4), round(ia/t, 4)


def _parse_score(score) -> Tuple[int, int]:
    if score is None:
        return 0, 0
    if isinstance(score, (list, tuple)) and len(score) >= 2:
        try:
            return int(score[0]), int(score[1])
        except (ValueError, TypeError):
            return 0, 0
    s = str(score).replace(":", "-").replace(" ", "")
    parts = s.split("-")
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 0, 0
    return 0, 0


def _extract_team_goals(match: dict, team_name: str = "") -> int:
    """从近绩里提取该队进球（通过 resolver 中英文匹配）"""
    h, a = _parse_score(_pick(match, "score", "scoreStr", "ft_score", "比分"))

    if not team_name:
        return h if match.get("main_team") != "team_B" else a

    resolver = get_resolver()
    team_a = match.get("team_A_name", "") or match.get("home", "") or match.get("主队", "")
    team_b = match.get("team_B_name", "") or match.get("away", "") or match.get("客队", "")

    if resolver.matches(team_name, team_a):
        return h
    if resolver.matches(team_name, team_b):
        return a

    return h if match.get("main_team") != "team_B" else a


def _is_home_match(match: dict, team_name: str = "") -> bool:
    """判断该队在这场是否为主队（通过 resolver 中英文匹配）"""
    if not team_name:
        return match.get("main_team", "") != "team_B"

    resolver = get_resolver()
    team_a = match.get("team_A_name", "") or match.get("home", "") or match.get("主队", "")
    team_b = match.get("team_B_name", "") or match.get("away", "") or match.get("客队", "")

    if resolver.matches(team_name, team_a):
        return True
    if resolver.matches(team_name, team_b):
        return False

    return match.get("main_team", "") != "team_B"


def _extract_team_goals_and_conceded(match: dict, team_name: str = "") -> Tuple[int, int]:
    """从近绩里提取"该队进球"和"该队失球"（支持中英文匹配）"""
    h, a = _parse_score(_pick(match, "score", "scoreStr", "ft_score", "比分"))

    if not team_name:
        if match.get("main_team") == "team_B":
            return a, h
        return h, a

    resolver = get_resolver()
    team_a = match.get("team_A_name", "") or match.get("home", "") or match.get("主队", "")
    team_b = match.get("team_B_name", "") or match.get("away", "") or match.get("客队", "")

    if resolver.matches(team_name, team_a):
        return h, a   # 该队在 A 位置，进球=h、失球=a
    if resolver.matches(team_name, team_b):
        return a, h   # 该队在 B 位置，进球=a、失球=h

    if match.get("main_team") == "team_B":
        return a, h
    return h, a


def _pick(d, *keys, default=None):
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


# ========== 维度1：历史战绩（方向6：主客分离） ==========
def calc_history_prob(history: Dict, home: str, away: str) -> Dict[str, float]:
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

    home_rate = _recent_rate(history.get("home_recent", []), want="home")
    away_rate = _recent_rate(history.get("away_recent", []), want="away_reversed")

    win = h2h_win * 0.40 + home_rate[0] * 0.35 + away_rate[0] * 0.25
    draw = h2h_draw * 0.40 + home_rate[1] * 0.30 + away_rate[1] * 0.30
    lose = h2h_lose * 0.40 + home_rate[2] * 0.35 + away_rate[2] * 0.25

    return _normalize({"胜": win, "平": draw, "负": lose})


def _h2h_from_team(h2h, home):
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


def _recent_rate(matches, want="home"):
    if matches is None:
        return 0.33, 0.33, 0.34
    if hasattr(matches, "empty") and matches.empty:
        return 0.33, 0.33, 0.34
    if hasattr(matches, "iterrows"):
        matches = [row.to_dict() for _, row in matches.iterrows()]
    if not matches:
        return 0.33, 0.33, 0.34

    w = d = l = 0
    for m in matches:
        r = _extract_result(m)
        if want == "away_reversed":
            if r == "win":
                l += 1
            elif r == "draw":
                d += 1
            elif r == "lose":
                w += 1
        else:
            if r == "win":
                w += 1
            elif r == "draw":
                d += 1
            elif r == "lose":
                l += 1
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
def calc_intel_prob(intel: Dict, home: str, away: str, league: str = "") -> Dict[str, float]:
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

    has_ranking = (rank_score != 0) or (point_score != 0)
    has_injury = injury_score != 0

    if not has_ranking and not has_injury:
        return {"胜": 0.33, "平": 0.33, "负": 0.34}

    if not has_ranking and has_injury:
        home_win = 0.45 + injury_score * 0.15
        away_win = 0.35 - injury_score * 0.15
        return _normalize({"胜": home_win, "平": 0.20, "负": away_win})

    if not has_ranking:
        return {"胜": 0.42, "平": 0.24, "负": 0.34}

    total_score = rank_score * 0.5 + point_score * 0.3 + injury_score * 0.2
    home_win = 0.40 + total_score * 0.30
    away_win = 0.40 - total_score * 0.30
    return _normalize({"胜": home_win, "平": 0.20, "负": away_win})


# ========== 维度3：赔率 ==========
def calc_odds_prob(intel: Dict) -> Dict[str, float]:
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


# ========== 融合（方向5：平局专项 + 非线性放大） ==========
def fuse_probabilities(hp, ip, op, league: str = "", history: Dict = None) -> Dict:
    w = get_weights(league)
    win = hp["胜"]*w["history"] + ip["胜"]*w["intel"] + op["胜"]*w["odds"]
    draw = hp["平"]*w["history"] + ip["平"]*w["intel"] + op["平"]*w["odds"]
    lose = hp["负"]*w["history"] + ip["负"]*w["intel"] + op["负"]*w["odds"]

    # 方向5：平局专项加厚
    draw_boost = _detect_draw_signal(hp, ip, op, history)
    if draw_boost:
        draw *= 1.35
        logger.info(f"  ⚖️ 检测到平局信号，平局概率 +35%")

    # ✅ 非线性放大：把偏离 1/3 的幅度放大 1.5 倍
    AMPLIFY = 1.5
    def amplify(p):
        diff = p - 1/3
        return max(0.05, min(0.90, 1/3 + diff * AMPLIFY))

    win = amplify(win)
    draw = amplify(draw)
    lose = amplify(lose)

    # 归一化
    total = win + draw + lose
    win, draw, lose = win/total, draw/total, lose/total

    d = {"胜": win, "平": draw, "负": lose}
    return {
        "胜": round(win, 4), "平": round(draw, 4), "负": round(lose, 4),
        "推荐": max(d, key=d.get),
    }


def _detect_draw_signal(hp, ip, op, history) -> bool:
    """平局信号检测（方向5）：满足 ≥ 3 条"""
    score = 0
    if hp["平"] > 0.28 and ip["平"] > 0.28 and op["平"] > 0.28:
        score += 1
    if op.get("平", 0) >= max(op.get("胜", 0), op.get("负", 0)):
        score += 1
    if history:
        h2h = history.get("h2h", {}) or {}
        total = h2h.get("total", 0)
        if total > 0:
            draw_rate = h2h.get("draw", 0) / total
            if draw_rate > 0.30:
                score += 1
    if abs(op["胜"] - op["负"]) < 0.10:
        score += 1
    return score >= 3


# ========== 让球 ==========
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


# ========== 让球推断 ==========
def _extract_handicap_from_intel(intel: dict) -> float:
    odds = intel.get("odds", {}) or {}
    avg = odds.get("avg", {}) or {}
    now_euro = avg.get("now", {}) or {}
    h = _safe_float(_pick(now_euro, "homeWin", "home", "h"))
    a = _safe_float(_pick(now_euro, "awayWin", "away", "a"))
    if h > 0 and a > 0:
        return -1.0 if h < a else 1.0
    return -1.0


# ========== 真实赔率提取 ==========
def _extract_real_odds(intel: dict) -> Dict[str, float]:
    odds = intel.get("odds", {}) or {}
    avg = odds.get("avg", {}) or {}
    now = avg.get("now", {}) or {}
    return {
        "胜": _safe_float(_pick(now, "homeWin", "home", "h")),
        "平": _safe_float(_pick(now, "draw", "d")),
        "负": _safe_float(_pick(now, "awayWin", "away", "a")),
    }


# ========== 体彩 5 玩法赔率解析 ==========
def _parse_crs_odds(crs: dict) -> Dict[str, float]:
    """解析体彩比分赔率：s01s00 → 1:0"""
    result = {}
    if not crs:
        return result
    for key, val in crs.items():
        if not key.startswith("s") or key.endswith("f"):
            continue
        if key in ("s1sh", "s1sd", "s1sa"):
            continue
        # 体彩 key 是 6 位（sXXsYY）
        if len(key) == 6 and key[3] == "s":
            try:
                h = int(key[1:3])
                a = int(key[4:6])
                result[f"{h}:{a}"] = _safe_float(val)
            except (ValueError, IndexError):
                continue
    if "s1sh" in crs:
        result["胜其他"] = _safe_float(crs["s1sh"])
    if "s1sd" in crs:
        result["平其他"] = _safe_float(crs["s1sd"])
    if "s1sa" in crs:
        result["负其他"] = _safe_float(crs["s1sa"])
    return result


def _parse_ttg_odds(ttg: dict) -> Dict[str, float]:
    result = {}
    if not ttg:
        return result
    for i in range(8):
        key = f"s{i}"
        if key in ttg:
            result[f"{i}球"] = _safe_float(ttg[key])
    return result


def _parse_hafu_odds(hafu: dict) -> Dict[str, float]:
    result = {}
    if not hafu:
        return result
    mapping = {
        "hh": "胜胜", "hd": "胜平", "ha": "胜负",
        "dh": "平胜", "dd": "平平", "da": "平负",
        "ah": "负胜", "ad": "负平", "aa": "负负",
    }
    for key, name in mapping.items():
        if key in hafu:
            result[name] = _safe_float(hafu[key])
    return result


def _parse_hhad_odds(match: dict) -> Dict[str, float]:
    return {
        "让胜": _safe_float(match.get("让球胜", 0)),
        "让平": _safe_float(match.get("让球平", 0)),
        "让负": _safe_float(match.get("让球负", 0)),
    }


# ========== 比分（V6：对手防守强度 + 混合联赛均值） ==========
def calc_score(history: Dict, home: str = "", away: str = "",
               league: str = "", wdl_recommendation: str = None,
               weather: Dict = None, referee: Dict = None) -> Dict[str, float]:
    """
    V6：λ = 进攻 × (对手防守 / 联赛均值) → 混合 → clamp
    λ_h = 主队主场进攻 × (客队客场失球 / 联赛均值) × 1.05
    λ_a = 客队客场进攻 × (主队主场失球 / 联赛均值) × 1.05
    """
    def _to_list(matches):
        if matches is None:
            return []
        if hasattr(matches, "empty") and matches.empty:
            return []
        if hasattr(matches, "iterrows"):
            return [row.to_dict() for _, row in matches.iterrows()]
        return list(matches) if matches else []

    def stats(matches, team_name, want_home: bool):
        goals, conceded = [], []
        for m in _to_list(matches):
            is_home = _is_home_match(m, team_name)
            if is_home != want_home:
                continue
            g, c = _extract_team_goals_and_conceded(m, team_name)
            goals.append(g)
            conceded.append(c)
        return goals, conceded

    def mean(lst, default):
        return sum(lst) / len(lst) if lst else default

    # 主队：主场进攻 + 主场失球
    h_goals, h_conceded = stats(history.get("home_recent", []), home, True)
    if not h_goals:
        h_goals, h_conceded = stats(history.get("home_recent", []), home, False)

    # 客队：客场进攻 + 客场失球
    a_goals, a_conceded = stats(history.get("away_recent", []), away, False)
    if not a_goals:
        a_goals, a_conceded = stats(history.get("away_recent", []), away, True)

    home_attack = mean(h_goals, 1.5)
    home_defense = mean(h_conceded, 1.2)
    away_attack = mean(a_goals, 1.2)
    away_defense = mean(a_conceded, 1.5)

    league_avg = LEAGUE_AVG_GOALS.get(league, DEFAULT_LEAGUE_AVG)

    # L1：对手防守强度交叉
    lam_h_raw = home_attack * (away_defense / league_avg) * 1.05
    lam_a_raw = away_attack * (home_defense / league_avg) * 1.05

    # L2：混合联赛均值（平滑极端值）
    lam_h = 0.75 * lam_h_raw + 0.25 * league_avg
    lam_a = 0.75 * lam_a_raw + 0.25 * league_avg

    # L3：放宽上下限
    lam_h = max(0.9, min(3.8, lam_h))
    lam_a = max(0.6, min(2.8, lam_a))

    if weather and weather.get("available"):
        f = weather.get("goal_factor", 1.0)
        lam_h *= f
        lam_a *= f
    if referee and referee.get("available"):
        f = referee.get("goal_factor", 1.0)
        lam_h *= f
        lam_a *= f

    result = {}
    for h in range(7):
        for a in range(7):
            p = poisson_probability(lam_h, h) * poisson_probability(lam_a, a)
            result[f"{h}:{a}"] = round(p, 4)

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
        filtered = {"1:0": 0.25, "2:0": 0.20, "2:1": 0.20, "1:1": 0.20, "0:0": 0.15}

    data_quality = "完整" if (h_goals and a_goals) else "部分兜底"
    filtered["__data_quality__"] = data_quality

    logger.info(
        f"  λ_h={lam_h:.2f} λ_a={lam_a:.2f} | "
        f"主攻{home_attack:.2f}/主防{home_defense:.2f} "
        f"客攻{away_attack:.2f}/客防{away_defense:.2f} "
        f"| 联赛均值{league_avg} | {data_quality}"
    )
    return filtered


# ========== 总进球（V2：与 calc_score 同逻辑） ==========
def calc_total_goals(history: Dict, home: str = "", away: str = "",
                     league: str = "", weather: Dict = None,
                     referee: Dict = None) -> Dict[str, float]:
    """V2：与 calc_score 同三层逻辑计算总进球"""
    def _to_list(matches):
        if matches is None:
            return []
        if hasattr(matches, "empty") and matches.empty:
            return []
        if hasattr(matches, "iterrows"):
            return [row.to_dict() for _, row in matches.iterrows()]
        return list(matches) if matches else []

    def stats(matches, team_name, want_home: bool):
        goals, conceded = [], []
        for m in _to_list(matches):
            if _is_home_match(m, team_name) != want_home:
                continue
            g, c = _extract_team_goals_and_conceded(m, team_name)
            goals.append(g)
            conceded.append(c)
        return goals, conceded

    def mean(lst, default):
        return sum(lst) / len(lst) if lst else default

    h_goals, h_conceded = stats(history.get("home_recent", []), home, True)
    if not h_goals:
        h_goals, h_conceded = stats(history.get("home_recent", []), home, False)

    a_goals, a_conceded = stats(history.get("away_recent", []), away, False)
    if not a_goals:
        a_goals, a_conceded = stats(history.get("away_recent", []), away, True)

    home_attack = mean(h_goals, 1.5)
    home_defense = mean(h_conceded, 1.2)
    away_attack = mean(a_goals, 1.2)
    away_defense = mean(a_conceded, 1.5)

    league_avg = LEAGUE_AVG_GOALS.get(league, DEFAULT_LEAGUE_AVG)

    lam_h_raw = home_attack * (away_defense / league_avg) * 1.05
    lam_a_raw = away_attack * (home_defense / league_avg) * 1.05

    lam_h = 0.75 * lam_h_raw + 0.25 * league_avg
    lam_a = 0.75 * lam_a_raw + 0.25 * league_avg

    lam_h = max(0.9, min(3.8, lam_h))
    lam_a = max(0.6, min(2.8, lam_a))

    if weather and weather.get("available"):
        f = weather.get("goal_factor", 1.0)
        lam_h *= f
        lam_a *= f
    if referee and referee.get("available"):
        f = referee.get("goal_factor", 1.0)
        lam_h *= f
        lam_a *= f

    lam = lam_h + lam_a
    return {f"{k}球": round(poisson_probability(lam, k), 4) for k in range(9)}


# ========== 半全场 ==========
def calc_half_full(wdl: Dict) -> Dict[str, float]:
    h, d, a = wdl["胜"], wdl["平"], wdl["负"]
    return {
        "胜胜": round(h*0.55, 4), "平胜": round(h*0.30, 4), "负胜": round(h*0.15, 4),
        "平平": round(d*0.60, 4), "平负": round(a*0.30, 4), "负负": round(a*0.55, 4),
    }


# ========== 从比分推导 ==========
def derive_handicap_from_score(score_str: str, handicap: float, wdl_recommendation: str = "胜") -> str:
    try:
        h, a = map(int, score_str.split(":"))
    except Exception:
        return "让平"
    diff = h - a
    if handicap == 0:
        return "让胜" if diff >= 1 else ("让平" if diff == 0 else "让负")
    adjusted = diff + handicap
    if adjusted > 0:
        return "让胜"
    elif adjusted == 0:
        return "让平"
    return "让负"


def derive_total_from_score(score_str: str) -> str:
    try:
        h, a = map(int, score_str.split(":"))
        return f"{h+a}球"
    except Exception:
        return "2球"


def derive_half_full_from_score(score_str: str, wdl: str) -> str:
    try:
        h, a = map(int, score_str.split(":"))
    except Exception:
        return "平胜"
    if wdl == "胜":
        return "胜胜" if h >= 2 else "平胜"
    elif wdl == "负":
        return "负负" if a >= 2 else "平负"
    return "平平"


# ========== 主入口 ==========
def analyze_match(match: Dict, history: Dict, intel: Dict,
                  weather: Dict = None, referee: Dict = None) -> Dict:
    home = match.get("主队", "")
    away = match.get("客队", "")
    league = match.get("联赛", "")

    handicap = _safe_float(match.get("让球", 0))
    if handicap == 0:
        handicap = _extract_handicap_from_intel(intel)

    hp = calc_history_prob(history, home, away)
    ip = calc_intel_prob(intel, home, away, league)
    op = calc_odds_prob(intel)
    wdl = fuse_probabilities(hp, ip, op, league, history)

    score_prob = calc_score(history, home=home, away=away, league=league,
                             wdl_recommendation=wdl["推荐"],
                             weather=weather, referee=referee)
    data_quality = score_prob.pop("__data_quality__", "未知")
    top_score = max((kv for kv in score_prob.items() if kv[0].count(":") == 1),
                    key=lambda x: x[1])
    score_str = top_score[0]

    handicap_pick = derive_handicap_from_score(score_str, handicap, wdl["推荐"])
    total_pick = derive_total_from_score(score_str)
    hf_pick = derive_half_full_from_score(score_str, wdl["推荐"])

    handicap_prob = calc_handicap(wdl, handicap)
    total_prob = calc_total_goals(history, home=home, away=away, league=league,
                                   weather=weather, referee=referee)
    hf_prob = calc_half_full(wdl)

    max_wdl = max(wdl["胜"], wdl["平"], wdl["负"])
    confidence = round(max_wdl * 0.6 + top_score[1] * 0.4, 4)

    return {
        "场次编号": match.get("场次编号", ""),
        "联赛": league,
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
        "维度分解": {"历史": hp, "情报": ip, "赔率": op, "权重": get_weights(league)},
        "真实赔率": _extract_real_odds(intel),
        "真实赔率_让球": _parse_hhad_odds(match),
        "真实赔率_比分": _parse_crs_odds(match.get("赔率_比分", {})),
        "真实赔率_总进球": _parse_ttg_odds(match.get("赔率_总进球", {})),
        "真实赔率_半全场": _parse_hafu_odds(match.get("赔率_半全场", {})),
        "天气": weather or {},
        "裁判": referee or {},
        "数据源": intel.get("source", "none"),
        "数据质量": data_quality,
    }
