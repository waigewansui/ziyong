"""
推荐输出模块（V3 - 凯利公式版）

核心功能：
1. 单场推荐：MD / JSON / CSV
2. 串关推荐：2串1 至 5串1，分档（稳胆/稳健/搏冷/极端）
3. 凯利公式：单场给出建议投入金额
4. 真实赔率优先：胜平负用 intel.odds 的真实欧赔

凯利风控：
- 半凯利（f*/2）
- 单注上限：本金 2%
- 小幅负期望（-10% 内）：保守 1%
- 严重负期望：跳过
- 串关：按分档固定金额（不用凯利）
"""
import os
import json
import csv
import logging
from itertools import combinations
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


# ============ 常量配置 ============
VIG_FACTOR = 0.90
KELLY_FRACTION = 0.5
MAX_SINGLE_PCT = 0.02
MAX_POOL_PCT = 0.20
MIN_STAKE = 2.0
MIN_EDGE = -0.10

CONFIDENCE_TIERS = [
    ("稳胆", 0.55),
    ("稳健", 0.45),
    ("搏冷", 0.35),
    ("极端", 0.00),
]

TIER_STAKE = {
    "稳胆": 10,
    "稳健": 6,
    "搏冷": 4,
    "极端": 2,
}


# ============ 工具函数 ============
def prob_to_odds(prob: float) -> float:
    if prob <= 0.01:
        return 99.0
    return round(1 / prob * VIG_FACTOR, 2)


def get_tier(conf: float) -> str:
    for name, threshold in CONFIDENCE_TIERS:
        if conf >= threshold:
            return name
    return "极端"


def format_bet_item(match_id: str, play_type: str, key: str) -> str:
    if play_type in ("胜平负", "让球", "半全场"):
        return f"{match_id}{key}"
    if play_type in ("比分", "总进球"):
        return f"{match_id}({key})"
    return f"{match_id}{key}"


def _stringify(v) -> str:
    if isinstance(v, dict):
        return "; ".join(f"{k}={val}" for k, val in v.items())
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v) if v is not None else ""


# ============ 凯利公式 ============
def kelly_stake(prob: float, odds: float, bankroll: float,
                fraction: float = KELLY_FRACTION) -> Dict[str, Any]:
    """
    凯利公式（edge 版）
    edge = prob × odds - 1
    - edge >= 0：标准凯利
    - MIN_EDGE <= edge < 0：保守 1%
    - edge < MIN_EDGE：跳过
    """
    if odds <= 1.0 or not (0 < prob < 1) or bankroll <= 0:
        return {
            "f_full": 0.0, "f_half": 0.0,
            "stake_raw": 0.0, "stake_capped": 0.0, "stake_final": 0.0,
            "should_bet": False, "edge": 0.0,
            "reason": "参数无效",
        }

    edge = prob * odds - 1.0
    b = odds - 1.0

    if edge >= 0:
        f_full = (b * prob - (1 - prob)) / b
        f_half = f_full * fraction
        reason = f"正凯利 f*={f_full:.4f}"
    elif edge > MIN_EDGE:
        f_full = 0.0
        f_half = 0.01
        reason = f"小幅负期望 edge={edge:.4f}，保守 1%"
    else:
        return {
            "f_full": 0.0, "f_half": 0.0,
            "stake_raw": 0.0, "stake_capped": 0.0, "stake_final": 0.0,
            "should_bet": False, "edge": round(edge, 4),
            "reason": f"严重负期望 edge={edge:.4f}，跳过",
        }

    stake_raw = bankroll * f_half
    stake_capped = min(stake_raw, bankroll * MAX_SINGLE_PCT)
    stake_final = max(MIN_STAKE, round(stake_capped / 2) * 2)

    return {
        "f_full": round(f_full, 4),
        "f_half": round(f_half, 4),
        "stake_raw": round(stake_raw, 2),
        "stake_capped": round(stake_capped, 2),
        "stake_final": stake_final,
        "should_bet": True,
        "edge": round(edge, 4),
        "reason": reason,
    }


# ============ 单场推荐提取 ============
def _pick_play(result: Dict, play_type: str,
               bankroll: float = 1000.0) -> Dict[str, Any]:
    """
    从单场结果提取玩法数据
    ✅ 5 玩法都用真实赔率（体彩 / 懂球帝）
    """
    mapping = {
        "胜平负": ("胜平负推荐", "胜平负概率", "真实赔率"),
        "让球":   ("让球推荐",   "让球概率",   "真实赔率_让球"),
        "比分":   ("比分推荐",   "比分概率",   "真实赔率_比分"),
        "总进球": ("总进球推荐", "总进球概率", "真实赔率_总进球"),
        "半全场": ("半全场推荐", "半全场概率", "真实赔率_半全场"),
    }
    if play_type not in mapping:
        return {}
    rec_key, prob_key, odds_key = mapping[play_type]
    pick = result.get(rec_key, "")
    prob_map = result.get(prob_key, {}) or {}
    prob = float(prob_map.get(pick, 0.0))

    # ✅ 从对应玩法的真实赔率里取
    real_odds = result.get(odds_key, {}) or {}
    if real_odds.get(pick):
        odds = round(float(real_odds[pick]), 2)
        odds_source = "real"
    else:
        odds = prob_to_odds(prob)
        odds_source = "inferred"

    # 凯利建议（5 玩法全用）
    kelly = kelly_stake(prob, odds, bankroll)

    return {
        "match_id": result.get("场次编号", ""),
        "match": result.get("对阵", ""),
        "play_type": play_type,
        "pick": pick,
        "prob": prob,
        "odds": odds,
        "odds_source": odds_source,
        "confidence": float(result.get("置信度", 0.0)),
        "kelly": kelly,
    }


# ============ 单场输出 ============
def save_markdown(results: List[Dict], filepath: str,
                  bankroll: float = 1000.0):
    lines = [
        "# 足球竞猜推荐\n",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"本金：{bankroll:.0f} 元 | 共 {len(results)} 场\n",
        "\n## 单场推荐\n",
        "| 场次 | 对阵 | 胜平负 | 概率 | 赔率 | 赔率来源 | 建议投入 | 让球 | 比分 | 总进球 | 半全场 | 置信度 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        wdl = r.get("胜平负概率", {}) or {}
        top_prob = max(wdl.values()) if wdl else 0
        real_odds = r.get("真实赔率", {}) or {}
        pick = r.get("胜平负推荐", "")
        odds = real_odds.get(pick, 0)

        if odds:
            k = kelly_stake(top_prob, odds, bankroll)
            stake_str = f"{k['stake_final']:.0f}元" if k['stake_final'] > 0 else "不投"
            source_str = "真实"
        else:
            stake_str = "—"
            source_str = "—"

        lines.append(
            f"| {r.get('场次编号','')} | {r.get('对阵','')} | "
            f"{pick} | {top_prob:.2%} | {odds} | {source_str} | {stake_str} | "
            f"{r.get('让球推荐','')} | {r.get('比分推荐','')} | "
            f"{r.get('总进球推荐','')} | {r.get('半全场推荐','')} | "
            f"{r.get('置信度',0):.2%} |"
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Markdown 已保存: {filepath}")


def save_json(results: List[Dict], filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已保存: {filepath}")


def save_csv(results: List[Dict], filepath: str):
    if not results:
        return
    fields = [
        "场次编号", "联赛", "比赛时间", "对阵",
        "胜平负推荐", "让球推荐", "比分推荐",
        "总进球推荐", "半全场推荐", "置信度", "数据源",
    ]
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {k: _stringify(r.get(k, "")) for k in fields}
            writer.writerow(row)
    logger.info(f"CSV 已保存: {filepath}")


# ============ 串关生成 ============
def generate_parlays(results: List[Dict], play_type: str = "胜平负",
                     min_confidence: float = 0.45,
                     max_n: int = 5, max_results: int = 20,
                     bankroll: float = 1000.0) -> List[Dict]:
    candidates = [r for r in results
                  if float(r.get("置信度", 0)) >= min_confidence]
    if len(candidates) < 2:
        logger.warning(f"[{play_type}] 高置信度场次不足2场，跳过")
        return []

    picked = []
    for r in candidates:
        item = _pick_play(r, play_type, bankroll=bankroll)
        if item and item["pick"] and item["prob"] > 0:
            picked.append(item)

    if len(picked) < 2:
        return []

    parlays = []
    seen_combos = set()
    for n in range(2, min(max_n + 1, len(picked) + 1)):
        for combo in combinations(picked, n):
            key = frozenset(c["match_id"] for c in combo)
            if key in seen_combos:
                continue
            seen_combos.add(key)
            odds_product = 1.0
            prob_product = 1.0
            for c in combo:
                odds_product *= c["odds"]
                prob_product *= c["prob"]
            avg_conf = sum(c["confidence"] for c in combo) / n
            tier = get_tier(avg_conf)
            stake = TIER_STAKE.get(tier, 2)

            parlays.append({
                "串关方式": f"{n}串1",
                "玩法": play_type,
                "场次数": n,
                "场次列表": [c["match_id"] for c in combo],
                "投注内容": [format_bet_item(c["match_id"], play_type, c["pick"])
                            for c in combo],
                "推荐列表": [c["pick"] for c in combo],
                "估算赔率": round(odds_product, 2),
                "理论命中率": round(prob_product, 4),
                "平均置信度": round(avg_conf, 4),
                "投入": stake,
                "满中收益": round(odds_product * stake, 2),
                "分档": tier,
            })

    tier_order = {"稳胆": 0, "稳健": 1, "搏冷": 2, "极端": 3}
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4), -x["平均置信度"]))
    return parlays[:max_results]


def generate_mixed_parlays(results: List[Dict],
                           min_confidence: float = 0.45,
                           max_n: int = 5, max_results: int = 10,
                           bankroll: float = 1000.0) -> List[Dict]:
    candidates = [r for r in results
                  if float(r.get("置信度", 0)) >= min_confidence]
    if len(candidates) < 2:
        return []

    play_types = ["胜平负", "让球", "比分", "总进球", "半全场"]
    picked = []
    for r in candidates:
        best = None
        for pt in play_types:
            item = _pick_play(r, pt, bankroll=bankroll)
            if not item or not item["pick"]:
                continue
            weight = 0.7 if pt in ("比分", "总进球") else 1.0
            score = item["prob"] * weight
            if best is None or score > best["_score"]:
                item["_score"] = score
                best = item
        if best:
            picked.append(best)

    if len(picked) < 2:
        return []

    parlays = []
    seen_combos = set()
    for n in range(2, min(max_n + 1, len(picked) + 1)):
        for combo in combinations(picked, n):
            key = frozenset(c["match_id"] for c in combo)
            if key in seen_combos:
                continue
            seen_combos.add(key)
            odds_product = 1.0
            prob_product = 1.0
            for c in combo:
                odds_product *= c["odds"]
                prob_product *= c["prob"]
            avg_conf = sum(c["confidence"] for c in combo) / n
            tier = get_tier(avg_conf)
            stake = TIER_STAKE.get(tier, 2)

            parlays.append({
                "串关方式": f"{n}串1",
                "玩法": "混合",
                "场次数": n,
                "场次列表": [c["match_id"] for c in combo],
                "投注内容": [format_bet_item(c["match_id"], c["play_type"], c["pick"])
                            for c in combo],
                "玩法列表": [c["play_type"] for c in combo],
                "推荐列表": [c["pick"] for c in combo],
                "估算赔率": round(odds_product, 2),
                "理论命中率": round(prob_product, 4),
                "平均置信度": round(avg_conf, 4),
                "投入": stake,
                "满中收益": round(odds_product * stake, 2),
                "分档": tier,
            })

    tier_order = {"稳胆": 0, "稳健": 1, "搏冷": 2, "极端": 3}
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4), -x["平均置信度"]))
    return parlays[:max_results]


def save_parlays(parlays: List[Dict], filepath: str,
                 title: str = "串关推荐"):
    if not parlays:
        return
    lines = [f"# {title}\n",
             f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
             f"共 {len(parlays)} 注\n"]

    by_tier: Dict[str, List[Dict]] = {}
    for p in parlays:
        by_tier.setdefault(p["分档"], []).append(p)

    for tier in ["稳胆", "稳健", "搏冷", "极端"]:
        group = by_tier.get(tier, [])
        if not group:
            continue
        lines.append(f"\n## {tier}（{len(group)} 注）\n")
        lines.append("| 串关 | 投注内容 | 赔率 | 投入 | 收益 | 理论命中率 | 平均置信度 |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for p in group:
            bet_str = " × ".join(p["投注内容"])
            lines.append(
                f"| {p['串关方式']} | {bet_str} | {p['估算赔率']} | "
                f"{p['投入']}元 | {p['满中收益']}元 | "
                f"{p['理论命中率']:.2%} | {p['平均置信度']:.2%} |"
            )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"串关推荐已保存: {filepath}")


# ============ 统一入口 ============
def output_all(results: List[Dict], output_dir: str = "output",
               play_types: List[str] = None,
               min_confidence: float = 0.45,
               bankroll: float = 1000.0,
               max_daily_pct: float = 0.15) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ✅ 先算每场建议金额（写入 results dict，供上限控制 + UI 使用）
    for r in results:
        if r.get("建议金额"):
            continue
        wdl = r.get("胜平负概率", {}) or {}
        top_prob = max(wdl.values()) if wdl else 0
        if top_prob < min_confidence:
            r["建议金额"] = 0
            continue
        pick = r.get("胜平负推荐", "")
        real_odds = r.get("真实赔率", {}) or {}
        try:
            odds = float(real_odds.get(pick, 0)) or prob_to_odds(top_prob)
        except Exception:
            odds = prob_to_odds(top_prob)
        k = kelly_stake(top_prob, odds, bankroll)
        r["建议金额"] = k["stake_final"]

    # ✅ 单日总投注上限
    total_stake = sum(r.get("建议金额", 0) for r in results)
    cap = bankroll * max_daily_pct

    if total_stake > cap:
        ratio = cap / total_stake
        for r in results:
            if r.get("建议金额"):
                r["建议金额"] = round(r["建议金额"] * ratio, 1)
        logger.warning(
            f"⚠️ 单日总投注 {total_stake:.0f}元 超上限 {cap:.0f}元，"
            f"按 {ratio:.2f} 比例缩减"
        )
    else:
        logger.info(f"💰 单日总投注 {total_stake:.0f}元 / 上限 {cap:.0f}元")

    save_markdown(results, os.path.join(output_dir, f"recommend_{ts}.md"),
                  bankroll=bankroll)
    save_json(results, os.path.join(output_dir, f"recommend_{ts}.json"))
    save_csv(results, os.path.join(output_dir, f"recommend_{ts}.csv"))

    if play_types is None:
        play_types = ["胜平负", "让球", "比分", "总进球", "半全场"]

    summary = {"单场数": len(results), "bankroll": bankroll, "串关": {}}

    for pt in play_types:
        parlays = generate_parlays(results, play_type=pt,
                                   min_confidence=min_confidence,
                                   bankroll=bankroll)
        if parlays:
            save_parlays(parlays,
                         os.path.join(output_dir, f"parlay_{pt}_{ts}.md"),
                         title=f"{pt}串关推荐")
            save_json(parlays,
                      os.path.join(output_dir, f"parlay_{pt}_{ts}.json"))
            summary["串关"][pt] = len(parlays)

    mixed = generate_mixed_parlays(results, min_confidence=min_confidence,
                                   bankroll=bankroll)
    if mixed:
        save_parlays(mixed,
                     os.path.join(output_dir, f"parlay_mixed_{ts}.md"),
                     title="混合串关推荐")
        save_json(mixed, os.path.join(output_dir, f"parlay_mixed_{ts}.json"))
        summary["串关"]["混合"] = len(mixed)

    logger.info(f"全部输出完成: {summary}")
    return summary


# ============ 测试 ============
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    print("=" * 60)
    print("测试 1：kelly_stake")
    print("=" * 60)
    cases = [
        (0.628, 1.54, 1000),
        (0.475, 1.92, 1000),
        (0.70, 1.54, 1000),
        (0.30, 2.00, 1000),
        (0.85, 1.20, 1000),
    ]
    for p, o, b in cases:
        r = kelly_stake(p, o, b)
        print(f"  prob={p:.3f} odds={o} → "
              f"stake={r['stake_final']}元, edge={r['edge']}, {r['reason']}")

    print()
    print("=" * 60)
    print("测试 2：完整 output_all（mock）")
    print("=" * 60)
    mock_results = [
        {
            "场次编号": "001",
            "联赛": "意甲",
            "比赛时间": "2026-10-13 20:00",
            "对阵": "亚特兰大 vs 威尼斯",
            "胜平负推荐": "胜",
            "胜平负概率": {"胜": 0.628, "平": 0.157, "负": 0.215},
            "让球推荐": "让平",
            "让球概率": {"让胜": 0.30, "让平": 0.42, "让负": 0.28},
            "比分推荐": "1:0",
            "比分概率": {"1:0": 0.25, "2:0": 0.20},
            "总进球推荐": "1球",
            "总进球概率": {"1球": 0.35, "2球": 0.30},
            "半全场推荐": "平胜",
            "半全场概率": {"平胜": 0.30, "胜胜": 0.25},
            "置信度": 0.4817,
            "真实赔率": {"胜": 1.54, "平": 4.29, "负": 5.26},
            "数据源": "dongqiudi",
        },
        {
            "场次编号": "011",
            "联赛": "欧冠",
            "比赛时间": "2026-10-14 03:00",
            "对阵": "马竞 vs 曼联",
            "胜平负推荐": "胜",
            "胜平负概率": {"胜": 0.475, "平": 0.258, "负": 0.267},
            "让球推荐": "让平",
            "让球概率": {"让胜": 0.22, "让平": 0.38, "让负": 0.40},
            "比分推荐": "2:1",
            "比分概率": {"2:1": 0.15, "1:0": 0.14},
            "总进球推荐": "3球",
            "总进球概率": {"2球": 0.28, "3球": 0.25},
            "半全场推荐": "胜胜",
            "半全场概率": {"胜胜": 0.28, "平胜": 0.20},
            "置信度": 0.3695,
            "真实赔率": {"胜": 1.92, "平": 3.75, "负": 3.59},
            "数据源": "dongqiudi",
        },
    ]

    summary = output_all(mock_results, output_dir="output", bankroll=1000)
    print(f"输出摘要: {summary}")

    print()
    print("=" * 60)
    print("生成的 recommend_*.md 内容：")
    print("=" * 60)
    import glob
    files = sorted(glob.glob("output/recommend_*.md"))
    if files:
        with open(files[-1], "r", encoding="utf-8") as f:
            print(f.read())
