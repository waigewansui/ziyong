"""
推荐输出模块（V2 - CSV 字段修复版）
"""
import os
import json
import csv
import logging
from itertools import combinations
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

VIG_FACTOR = 0.90
CONFIDENCE_TIERS = [
    ("稳胆", 0.55),
    ("稳健", 0.45),
    ("搏冷", 0.35),
    ("极端", 0.00),
]


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


def _pick_play(result: Dict, play_type: str) -> Dict[str, Any]:
    mapping = {
        "胜平负": ("胜平负推荐", "胜平负概率"),
        "让球":   ("让球推荐",   "让球概率"),
        "比分":   ("比分推荐",   "比分概率"),
        "总进球": ("总进球推荐", "总进球概率"),
        "半全场": ("半全场推荐", "半全场概率"),
    }
    if play_type not in mapping:
        return {}
    rec_key, prob_key = mapping[play_type]
    pick = result.get(rec_key, "")
    prob_map = result.get(prob_key, {}) or {}
    prob = float(prob_map.get(pick, 0.0))

    return {
        "match_id": result.get("场次编号", ""),
        "match": result.get("对阵", ""),
        "play_type": play_type,
        "pick": pick,
        "prob": prob,
        "odds": prob_to_odds(prob),
        "confidence": float(result.get("置信度", 0.0)),
    }


def _stringify(v) -> str:
    """dict / list 转成字符串，用于 CSV"""
    if isinstance(v, dict):
        return "; ".join(f"{k}={val}" for k, val in v.items())
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v) if v is not None else ""


# ============ 单场输出 ============
def save_markdown(results: List[Dict], filepath: str):
    lines = [
        "# 足球竞猜推荐\n",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"共 {len(results)} 场\n",
        "\n## 单场推荐\n",
        "| 场次 | 对阵 | 胜平负 | 概率 | 让球 | 比分 | 总进球 | 半全场 | 置信度 | 分档 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        wdl = r.get("胜平负概率", {})
        top_prob = max(wdl.values()) if wdl else 0
        lines.append(
            f"| {r.get('场次编号','')} | {r.get('对阵','')} | "
            f"{r.get('胜平负推荐','')} | {top_prob:.2%} | "
            f"{r.get('让球推荐','')} | {r.get('比分推荐','')} | "
            f"{r.get('总进球推荐','')} | {r.get('半全场推荐','')} | "
            f"{r.get('置信度',0):.2%} | {get_tier(r.get('置信度',0))} |"
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Markdown 已保存: {filepath}")


def save_json(results: List[Dict], filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已保存: {filepath}")


def save_csv(results: List[Dict], filepath: str):
    """CSV 输出：dict 字段序列化为字符串"""
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


# ============ 串关 ============
def generate_parlays(results, play_type="胜平负", min_confidence=0.35,
                     max_n=5, max_results=50) -> List[Dict]:
    candidates = [r for r in results
                  if float(r.get("置信度", 0)) >= min_confidence]
    if len(candidates) < 2:
        logger.warning(f"[{play_type}] 高置信度场次不足2场，跳过")
        return []

    picked = []
    for r in candidates:
        item = _pick_play(r, play_type)
        if item and item["pick"] and item["prob"] > 0:
            picked.append(item)

    if len(picked) < 2:
        return []

    parlays = []
    for n in range(2, min(max_n + 1, len(picked) + 1)):
        for combo in combinations(picked, n):
            odds_product = 1.0
            prob_product = 1.0
            for c in combo:
                odds_product *= c["odds"]
                prob_product *= c["prob"]
            avg_conf = sum(c["confidence"] for c in combo) / n

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
                "投入": 2,
                "满中收益": round(odds_product * 2, 2),
                "分档": get_tier(avg_conf),
            })

    tier_order = {"稳胆": 0, "稳健": 1, "搏冷": 2, "极端": 3}
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4), -x["平均置信度"]))
    return parlays[:max_results]


def generate_mixed_parlays(results, min_confidence=0.35,
                            max_n=5, max_results=20) -> List[Dict]:
    candidates = [r for r in results
                  if float(r.get("置信度", 0)) >= min_confidence]
    if len(candidates) < 2:
        return []

    play_types = ["胜平负", "让球", "比分", "总进球", "半全场"]
    picked = []
    for r in candidates:
        best = None
        for pt in play_types:
            item = _pick_play(r, pt)
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
    for n in range(2, min(max_n + 1, len(picked) + 1)):
        for combo in combinations(picked, n):
            odds_product = 1.0
            prob_product = 1.0
            for c in combo:
                odds_product *= c["odds"]
                prob_product *= c["prob"]
            avg_conf = sum(c["confidence"] for c in combo) / n

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
                "投入": 2,
                "满中收益": round(odds_product * 2, 2),
                "分档": get_tier(avg_conf),
            })

    tier_order = {"稳胆": 0, "稳健": 1, "搏冷": 2, "极端": 3}
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4), -x["平均置信度"]))
    return parlays[:max_results]


def save_parlays(parlays: List[Dict], filepath: str, title: str = "串关推荐"):
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
def output_all(results, output_dir="output", play_types=None,
               min_confidence=0.30) -> Dict[str, Any]:
    """注意：min_confidence 从 0.35 降到 0.30，让串关更容易生成"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    save_markdown(results, os.path.join(output_dir, f"recommend_{ts}.md"))
    save_json(results, os.path.join(output_dir, f"recommend_{ts}.json"))
    save_csv(results, os.path.join(output_dir, f"recommend_{ts}.csv"))

    if play_types is None:
        play_types = ["胜平负", "让球", "比分", "总进球", "半全场"]

    summary = {"单场数": len(results), "串关": {}}

    for pt in play_types:
        parlays = generate_parlays(results, play_type=pt, min_confidence=min_confidence)
        if parlays:
            save_parlays(parlays, os.path.join(output_dir, f"parlay_{pt}_{ts}.md"),
                         title=f"{pt}串关推荐")
            save_json(parlays, os.path.join(output_dir, f"parlay_{pt}_{ts}.json"))
            summary["串关"][pt] = len(parlays)

    mixed = generate_mixed_parlays(results, min_confidence=min_confidence)
    if mixed:
        save_parlays(mixed, os.path.join(output_dir, f"parlay_mixed_{ts}.md"),
                     title="混合串关推荐")
        save_json(mixed, os.path.join(output_dir, f"parlay_mixed_{ts}.json"))
        summary["串关"]["混合"] = len(mixed)

    logger.info(f"全部输出完成: {summary}")
    return summary