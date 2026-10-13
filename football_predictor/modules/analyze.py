"""
多维度分析模块
消费 fetch_history (DataFrame) + fetch_intel (dict) 的真实输出。
策略：intel dict 主源（懂球帝已解析好），history DataFrame 降级。

权重从 config.yaml 读取：history 0.40 / intel 0.30 / odds 0.30
输出：胜平负 / 让球胜平负 / 比分 / 总进球 / 半全场 / 置信度
"""
import math
import logging
from pathlib import Path
from typing import Dict, Any, Tuple

import yaml

logger = logging.getLogger(__name__)

# ---------- 读 config.yaml ----------
_BASE_DIR = Path(__file__).resolve().parent.parent
try:
    with open(_BASE_DIR / "config.yaml", "r", encoding="utf-8") as _f:
        _CFG = yaml.safe_load(_f) or {}
    WEIGHTS = _CFG.get("weights", {"history": 0.40, "intel": 0.30, "odds": 0.30})
except Exception:
    WEIGHTS = {"history": 0.40, "intel": 0.30, "odds": 0.30}


# ========== 通用工具 ==========
def _safe_float(v, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        s = str(v).replace("+", "").replace(" ", "").replace("%", "").strip()
        if s in ("", "-", "—", "None", "nan"):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _normalize(probs: Dict[str, float]) -> Dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        return {"胜": 1 / 3, "平": 1 / 3, "负": 1 / 3}
    return {k: round(v / total, 4) for k, v in probs.items()}


def _remove_vig(oh: float, od: float, oa: float) -> Tuple[float, float, float]:
    """赔率去水"""
    if oh <= 0 or od <= 0 or oa <= 0:
        return 0.0, 0.0, 0.0
    ih, idd, ia = 1 / oh, 1 / od, 1 / oa
    t = ih + idd + ia
    return round(ih / t, 4), round(idd / t, 4), round(ia / t, 4)


def _extract_result(m) -> str:
    """兼容 win/负/W/3/draw/平/1/lose/负/0 → 统一英文"""
    if isinstance(m, dict):
        r = m.get("result", m.get("color", ""))
    elif hasattr(m, 'get'):  # DataFrame row (Series)
        r = m.get("结果", m.get("result", ""))
    else:
        return ""
    if r is None:
        return ""
    s = str(r).strip().lower()
    if s in ("win", "w", "胜", "3"):
        return "win"
    if s in ("draw", "d", "平", "1"):
        return "draw"
    if s in ("lose", "loss", "l", "负", "0"):
        return "lose"
    return ""


def _parse_score(score) -> Tuple[int, int]:
    """兼容 '2-1' / '2:1' / '2 - 1'"""
    if score is None:
        return 0, 0
    s = str(score).replace(":", "-").replace(" ", "")
    parts = s.split("-")
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 0, 0


def poisson_probability(lam: float, k: int) -> float:
    if lam <= 0:
        return 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _df_to_records(df) -> list:
    """DataFrame → list[dict]，空的返回 []"""
    if df is None or not hasattr(df, 'empty'):
        return []
    if df.empty:
        return []
    return df.to_dict("records")


# ============================================================
# 维度 1：历史战绩（40%）
# intel.h2h dict 优先 → history DataFrame 降级
# intel.recent dict 优先 → history DataFrame 降级
# ============================================================
def calc_history_prob(history: Dict[str, Any],
                      intel: Dict[str, Any]) -> Dict[str, float]:
    """历史维度胜平负概率"""

    # ---------- 1.1 H2H 胜率 ----------
    h2h_total = 0
    h2h_home_win = h2h_draw = h2h_away_win = 0.33

    # 优先 intel.h2h dict（已解析好）
    ih2h = intel.get("h2h", {}) or {}
    if ih2h.get("total", 0) and ih2h.get("total", 0) > 0:
        h2h_total = ih2h["total"]
        h2h_home_win = ih2h.get("home_win", 0) / h2h_total
        h2h_draw = ih2h.get("draw", 0) / h2h_total
        h2h_away_win = ih2h.get("away_win", 0) / h2h_total
    else:
        # 降级：history.h2h DataFrame
        h2h_records = _df_to_records(history.get("h2h"))
        if h2h_records:
            w = d = l = 0
            for m in h2h_records:
                r = _extract_result(m)
                if r == "win":
                    w += 1
                elif r == "draw":
                    d += 1
                elif r == "lose":
                    l += 1
            n = max(1, w + d + l)
            h2h_total = n
            h2h_home_win = w / n
            h2h_draw = d / n
            h2h_away_win = l / n

    # ---------- 1.2 主队近期胜率 ----------
    home_rate = _recent_win_rate(
        intel.get("recent", {}).get("home", []),  # intel dict list
        history.get("home_recent"),                  # history DataFrame
    )
    # ---------- 1.3 客队近期胜率（反转为主队视角） ----------
    away_rate_rev = _recent_win_rate_reversed(
        intel.get("recent", {}).get("away", []),
        history.get("away_recent"),
    )

    # ---------- 加权融合 ----------
    win = h2h_home_win * 0.40 + home_rate[0] * 0.30 + away_rate_rev[0] * 0.30
    draw = h2h_draw * 0.40 + home_rate[1] * 0.30 + away_rate_rev[1] * 0.30
    lose = h2h_away_win * 0.40 + home_rate[2] * 0.30 + away_rate_rev[2] * 0.30

    return _normalize({"胜": win, "平": draw, "负": lose})


def _recent_win_rate(intel_list: list, history_df) -> Tuple[float, float, float]:
    """主队视角的近期胜率 (win, draw, lose)"""
    # 优先 intel dict list
    if intel_list:
        w = d = l = 0
        for m in intel_list:
            r = _extract_result(m)
            if r == "win":
                w += 1
            elif r == "draw":
                d += 1
            elif r == "lose":
                l += 1
        n = max(1, w + d + l)
        return w / n, d / n, l / n

    # 降级 history DataFrame
    records = _df_to_records(history_df)
    if records:
        w = d = l = 0
        for m in records:
            r = _extract_result(m)
            if r == "win":
                w += 1
            elif r == "draw":
                d += 1
            elif r == "lose":
                l += 1
        n = max(1, w + d + l)
        return w / n, d / n, l / n

    return 0.33, 0.33, 0.34


def _recent_win_rate_reversed(intel_list: list, history_df) -> Tuple[float, float, float]:
    """客队近期胜率 → 反转为主队视角"""
    if intel_list:
        w = d = l = 0
        for m in intel_list:
            r = _extract_result(m)
            if r == "win":        # 客队赢 → 主队输
                l += 1
            elif r == "draw":
                d += 1
            elif r == "lose":     # 客队输 → 主队赢
                w += 1
        n = max(1, w + d + l)
        return w / n, d / n, l / n

    records = _df_to_records(history_df)
    if records:
        w = d = l = 0
        for m in records:
            r = _extract_result(m)
            if r == "win":
                l += 1
            elif r == "draw":
                d += 1
            elif r == "lose":
                w += 1
        n = max(1, w + d + l)
        return w / n, d / n, l / n

    return 0.33, 0.33, 0.34


# ============================================================
# 维度 2：情报（30%）—— 排名差 + 积分差 + 伤停差
# ============================================================
def calc_intel_prob(intel: Dict[str, Any]) -> Dict[str, float]:
    """情报维度胜平负概率"""
    ranking = intel.get("ranking", {}) or {}
    home_rank = _safe_float(ranking.get("home_rank"))
    away_rank = _safe_float(ranking.get("away_rank"))
    home_points = _safe_float(ranking.get("home_points"))
    away_points = _safe_float(ranking.get("away_points"))

    sideline = intel.get("sideline", {}) or {}
    home_inj = len(sideline.get("home", []) or [])
    away_inj = len(sideline.get("away", []) or [])

    # 排名分（排名数字越小越好，所以 away_rank - home_rank 越大，主队越占优）
    rank_score = 0.0
    if home_rank > 0 and away_rank > 0:
        rank_score = max(-1.0, min(1.0, (away_rank - home_rank) / 20.0))

    # 积分分
    point_score = 0.0
    if home_points > 0 or away_points > 0:
        point_score = max(-1.0, min(1.0, (home_points - away_points) / 30.0))

    # 伤停分
    injury_score = max(-1.0, min(1.0, (away_inj - home_inj) / 5.0))

    # 杯赛全零 → 退化为中性
    if rank_score == 0 and point_score == 0 and injury_score == 0:
        return {"胜": 0.33, "平": 0.33, "负": 0.34}

    total_score = rank_score * 0.5 + point_score * 0.3 + injury_score * 0.2
    home_win = 0.40 + total_score * 0.30
    away_win = 0.40 - total_score * 0.30
    return _normalize({"胜": home_win, "平": 0.20, "负": away_win})


# ============================================================
# 维度 3：赔率（30%）—— 去水即时盘 + 趋势调整
# intel.odds.avg.now = {"home":"1.54","draw":"4.29","away":"5.26"}  ✅ 已验证
# ============================================================
def calc_odds_prob(intel: Dict[str, Any]) -> Dict[str, float]:
    """赔率维度胜平负概率"""
    odds = intel.get("odds", {}) or {}

    # 路径 1：avg.summary（已验证正确）
    avg = odds.get("avg", {}) or {}
    now = avg.get("now", {}) or {}
    oh = _safe_float(now.get("home"))
    od = _safe_float(now.get("draw"))
    oa = _safe_float(now.get("away"))

    # 路径 2：euro_books[0].now 降级
    if oh <= 0:
        books = odds.get("euro_books", []) or []
        if books and isinstance(books[0], dict):
            now2 = books[0].get("now", {}) or {}
            oh = _safe_float(now2.get("homeWin", now2.get("home")))
            od = _safe_float(now2.get("draw"))
            oa = _safe_float(now2.get("awayWin", now2.get("away")))

    # 路径 3：avg.begin 还不行就放弃
    if oh <= 0:
        return {"胜": 0.33, "平": 0.33, "负": 0.34}

    p_h, p_d, p_a = _remove_vig(oh, od, oa)

    # 赔率趋势微调（handicap_trend 已经在 fetch_intel.calc_handicap_trend 里算好了）
    trend = intel.get("handicap_trend", {}) or {}
    direction = trend.get("direction", "")
    if direction == "主胜降赔":
        p_h = min(0.85, p_h * 1.05)
    elif direction == "主胜升赔":
        p_h = max(0.10, p_h * 0.95)

    return _normalize({"胜": p_h, "平": p_d, "负": p_a})


# ============================================================
# 加权融合
# ============================================================
def fuse_probabilities(hist_prob: Dict, intel_prob: Dict, odds_prob: Dict) -> Dict:
    w = WEIGHTS
    win = hist_prob["胜"] * w["history"] + intel_prob["胜"] * w["intel"] + odds_prob["胜"] * w["odds"]
    draw = hist_prob["平"] * w["history"] + intel_prob["平"] * w["intel"] + odds_prob["平"] * w["odds"]
    lose = hist_prob["负"] * w["history"] + intel_prob["负"] * w["intel"] + odds_prob["负"] * w["odds"]

    d = {"胜": round(win, 4), "平": round(draw, 4), "负": round(lose, 4)}
    return {
        "胜": d["胜"], "平": d["平"], "负": d["负"],
        "推荐": max(d, key=d.get),   # 修复了之前 broken 的 max() lambda
    }


# ============================================================
# 让球胜平负
# ============================================================
def calc_handicap(wdl: Dict, handicap: float) -> Dict:
    h, d, a = wdl["胜"], wdl["平"], wdl["负"]
    if handicap < 0:
        # 主队让球（-1/-2）：让胜需要净胜 2+
        return {
            "让胜": round(h * 0.50, 4),
            "让平": round(h * 0.30 + d * 0.20, 4),
            "让负": round(h * 0.20 + d * 0.80 + a, 4),
        }
    elif handicap > 0:
        # 主队受让（+1）：平局也算让胜
        return {
            "让胜": round(h + d * 0.50, 4),
            "让平": round(d * 0.30 + a * 0.30, 4),
            "让负": round(a * 0.70, 4),
        }
    return {"让胜": h, "让平": d, "让负": a}


# ============================================================
# 比分预测（泊松分布）
# 进球均值从 intel.recent 的真实比分反推
# ============================================================
def _calc_avg_goals_per_team(matches: list) -> float:
    """从近期比赛 list 算单队场均进球"""
    if not matches:
        return 1.2
    total_self = 0
    n = 0
    for m in matches:
        score = m.get("score", "") if isinstance(m, dict) else m.get("比分", "")
        h, a = _parse_score(score)
        if h == 0 and a == 0:
            continue
        is_home = m.get("is_home", True) if isinstance(m, dict) else True
        self_score = h if is_home else a
        # 简单假设：这场比赛双方进球数各算一半
        # 更准确的做法需要知道 self 是主队还是客队
        total_self += self_score
        n += 1
    if n == 0:
        return 1.2
    return max(0.5, total_self / n)


def calc_score(history: Dict, intel: Dict) -> Dict[str, float]:
    """泊松比分分布"""
    # intel.recent 优先
    home_intel = intel.get("recent", {}).get("home", []) or []
    away_intel = intel.get("recent", {}).get("away", []) or []

    # 降级 history DataFrame
    home_hist = _df_to_records(history.get("home_recent"))
    away_hist = _df_to_records(history.get("away_recent"))

    # intel dict 里已经有 is_home 字段，直接用
    if home_intel:
        home_lam = _calc_avg_goals_per_team(home_intel)
    else:
        # history DataFrame 里用 '对手' / '比分'，假设都是自方视角
        if home_hist:
            total = 0
            for m in home_hist:
                h, a = _parse_score(m.get("比分", ""))
                total += h  # DataFrame 里 比分 是 主队-客队，但主队列是自方
            home_lam = max(0.5, total / len(home_hist))
        else:
            home_lam = 1.4

    if away_intel:
        away_lam = _calc_avg_goals_per_team(away_intel)
    else:
        if away_hist:
            total = 0
            for m in away_hist:
                h, a = _parse_score(m.get("比分", ""))
                total += a  # history DataFrame 里客队视角的话，对方进球在客队位置
            away_lam = max(0.5, total / len(away_hist))
        else:
            away_lam = 1.1

    # 泊松联合分布
    result = {}
    for h in range(7):
        for a in range(7):
            p = poisson_probability(home_lam, h) * poisson_probability(away_lam, a)
            if p > 0.001:
                result[f"{h}:{a}"] = round(p, 4)

    total = sum(result.values())
    if total > 0:
        result = {k: round(v / total, 4) for k, v in result.items()}
    # 按概率排序
    result = dict(sorted(result.items(), key=lambda x: -x[1]))
    return result


# ============================================================
# 总进球（泊松）
# ============================================================
def calc_total_goals(history: Dict, intel: Dict) -> Dict[str, float]:
    home_intel = intel.get("recent", {}).get("home", []) or []
    away_intel = intel.get("recent", {}).get("away", []) or []

    def _avg_total(matches):
        if not matches:
            return 2.5
        total = 0
        n = 0
        for m in matches:
            score = m.get("score", "") if isinstance(m, dict) else m.get("比分", "")
            h, a = _parse_score(score)
            if h == 0 and a == 0:
                continue
            total += h + a
            n += 1
        return max(0.5, total / max(1, n))

    if home_intel and away_intel:
        lam = (_avg_total(home_intel) + _avg_total(away_intel)) / 2
    else:
        home_hist = _df_to_records(history.get("home_recent"))
        away_hist = _df_to_records(history.get("away_recent"))
        lam = 2.5  # fallback

    return {f"{k}球": round(poisson_probability(lam, k), 4) for k in range(9)}


# ============================================================
# 半全场（经验分布）
# ============================================================
def calc_half_full(wdl: Dict) -> Dict[str, float]:
    h, d, a = wdl["胜"], wdl["平"], wdl["负"]
    # 基于统计经验：最终胜者在半场领先的概率 55%
    return _normalize({
        "胜胜": h * 0.55,
        "平胜": h * 0.30,
        "负胜": h * 0.15,
        "平平": d * 0.55,
        "平负": a * 0.30,
        "负负": a * 0.55,
    })


# ============================================================
# 置信度 = max(wdl) × 0.6 + top_score × 0.4
# ============================================================
def calc_confidence(wdl: Dict, top_score_prob: float) -> float:
    max_wdl = max(wdl["胜"], wdl["平"], wdl["负"])
    return round(max_wdl * 0.6 + top_score_prob * 0.4, 4)


# ============================================================
# 主入口
# ============================================================
def analyze_match(match: Dict[str, Any],
                  history: Dict[str, Any],
                  intel: Dict[str, Any]) -> Dict[str, Any]:
    """
    综合分析单场比赛。
    match:  {"场次编号", "主队", "客队", "联赛", "让球"}
    history: fetch_history.get_history() → {h2h: DataFrame, home_recent: DataFrame, away_recent: DataFrame}
    intel:  fetch_intel.get_intel() → dict（已解析好的 H2H/recent/ranking/odds/sideline）
    """
    home = match.get("主队", "")
    away = match.get("客队", "")
    handicap = _safe_float(match.get("让球", 0))

    # 三源概率
    hist_prob = calc_history_prob(history, intel)
    intel_prob = calc_intel_prob(intel)
    odds_prob = calc_odds_prob(intel)

    # 融合
    wdl = fuse_probabilities(hist_prob, intel_prob, odds_prob)

    # 衍生预测
    handicap_prob = calc_handicap(wdl, handicap)
    score_prob = calc_score(history, intel)
    total_prob = calc_total_goals(history, intel)
    hf_prob = calc_half_full(wdl)

    # Top1 推荐
    top_score = max(score_prob.items(), key=lambda x: x[1]) if score_prob else ("0:0", 0.0)
    top_total = max(total_prob.items(), key=lambda x: x[1])
    top_hf = max(hf_prob.items(), key=lambda x: x[1])
    top_handicap = max(handicap_prob.items(), key=lambda x: x[1])

    confidence = calc_confidence(wdl, top_score[1])

    logger.info(
        f"分析完成: {home} vs {away} | "
        f"胜{wdl['胜']:.2%} 平{wdl['平']:.2%} 负{wdl['负']:.2%} | "
        f"推荐={wdl['推荐']} | 置信度={confidence:.2%}"
    )

    return {
        "场次编号": match.get("场次编号", ""),
        "对阵": f"{home} vs {away}",
        "联赛": match.get("联赛", ""),
        "让球": handicap,
        "胜平负推荐": wdl["推荐"],
        "胜平负概率": {"胜": wdl["胜"], "平": wdl["平"], "负": wdl["负"]},
        "让球推荐": top_handicap[0],
        "让球概率": handicap_prob,
        "比分推荐": top_score[0],
        "比分概率_top": dict(list(score_prob.items())[:5]),
        "总进球推荐": top_total[0],
        "总进球概率": total_prob,
        "半全场推荐": top_hf[0],
        "半全场概率": hf_prob,
        "置信度": confidence,
        "维度分解": {
            "历史(40%)": hist_prob,
            "情报(30%)": intel_prob,
            "赔率(30%)": odds_prob,
        },
        "数据源": intel.get("source", "none"),
    }


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    import json

    # ---- 测试 1: E2E 亚特兰大 vs 威尼斯（intel 全有数据） ----
    print("\n" + "=" * 70)
    print("测试 1: 亚特兰大 vs 威尼斯 (意甲, match_id=54470920)")
    print("=" * 70)
    from modules.fetch_history import get_history
    from modules.fetch_intel import get_intel

    m1 = {"场次编号": "001", "主队": "亚特兰大", "客队": "威尼斯",
          "联赛": "意甲", "让球": -1}
    h1 = get_history("亚特兰大", "威尼斯")
    i1 = get_intel("亚特兰大", "威尼斯", "意甲", match_id="54470920")
    r1 = analyze_match(m1, h1, i1)
    print(json.dumps(r1, ensure_ascii=False, indent=2))
    s1 = r1["胜平负概率"]["胜"] + r1["胜平负概率"]["平"] + r1["胜平负概率"]["负"]
    print(f"\n概率和校验: {s1:.4f} (应为 1.0)")

    # ---- 测试 2: E2E 马竞 vs 曼联 (欧冠, 杯赛无积分榜) ----
    print("\n" + "=" * 70)
    print("测试 2: 马竞 vs 曼联 (欧冠, match_id=54577210)")
    print("=" * 70)
    m2 = {"场次编号": "011", "主队": "马德里竞技", "客队": "曼联",
          "联赛": "欧冠", "让球": 0}
    h2 = get_history("马德里竞技", "曼联")
    i2 = get_intel("马德里竞技", "曼联", "欧冠", match_id="54577210")
    r2 = analyze_match(m2, h2, i2)
    print(json.dumps(r2, ensure_ascii=False, indent=2))
    s2 = r2["胜平负概率"]["胜"] + r2["胜平负概率"]["平"] + r2["胜平负概率"]["负"]
    print(f"\n概率和校验: {s2:.4f} (应为 1.0)")
