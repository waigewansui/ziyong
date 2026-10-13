"""
推荐输出模块
输出：单场推荐（Markdown/JSON/CSV）+ 串关推荐（2串1 至 5串1）
串关赔率采用"概率反推"（含庄家抽水）

配置读取自 config.yaml → parlay.min_confidence / parlay.max_results / parlay.types
"""
import os
import csv
import json
import logging
from itertools import combinations
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

# ---------- 读 config.yaml ----------
_BASE_DIR = Path(__file__).resolve().parent.parent
try:
    with open(_BASE_DIR / "config.yaml", "r", encoding="utf-8") as _f:
        _CFG = yaml.safe_load(_f) or {}
    _PARLAY_CFG = _CFG.get("parlay", {})
    MIN_CONFIDENCE = float(_PARLAY_CFG.get("min_confidence", 0.55))
    MAX_RESULTS = int(_PARLAY_CFG.get("max_results", 20))
    PARLAY_TYPES = _PARLAY_CFG.get("types", ["2串1", "3串1", "4串1", "5串1"])
except Exception:
    MIN_CONFIDENCE = 0.55
    MAX_RESULTS = 20
    PARLAY_TYPES = ["2串1", "3串1", "4串1", "5串1"]

# 庄家抽水系数（从概率反推赔率）
VIG_FACTOR = 0.90

# 串关分档阈值（稳定输出，不从 config 读）
CONFIDENCE_TIERS = [
    ("稳胆", 0.55),
    ("稳健", 0.45),
    ("搏冷", 0.35),
    ("极端", 0.00),
]


# ============ 工具函数 ============
def prob_to_odds(prob: float) -> float:
    """从概率反推赔率（含庄家抽水）"""
    if prob <= 0.01:
        return 99.0
    return round(1 / prob * VIG_FACTOR, 2)


def get_tier(conf: float) -> str:
    for name, threshold in CONFIDENCE_TIERS:
        if conf >= threshold:
            return name
    return "极端"


def format_bet_item(match_id: str, play_type: str, key: str) -> str:
    """彩票终端可直接识别的投注格式"""
    if play_type in ("胜平负", "让球", "半全场"):
        return f"{match_id}{key}"              # 001胜 / 001让胜 / 001胜胜
    if play_type in ("比分", "总进球"):
        return f"{match_id}({key})"            # 001(2:1) / 001(3球)
    return f"{match_id}{key}"


# 【关键】映射 analyze.py 实际输出的字段名
# analyze.py 用 "比分概率_top" (截断后的 dict)，不是 "比分概率"
_PLAY_MAPPING = {
    "胜平负": ("胜平负推荐", "胜平负概率"),
    "让球":   ("让球推荐",   "让球概率"),
    "比分":   ("比分推荐",   "比分概率_top"),   # ← 真实 key！
    "总进球": ("总进球推荐", "总进球概率"),
    "半全场": ("半全场推荐", "半全场概率"),
}


def _pick_play(result: Dict[str, Any], play_type: str) -> Dict[str, Any]:
    """从单场结果里提取指定玩法的推荐/概率/赔率"""
    if play_type not in _PLAY_MAPPING:
        return {}
    rec_key, prob_key = _PLAY_MAPPING[play_type]
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


# ============ 单场推荐输出 ============
def save_markdown(results: List[Dict], filepath: str):
    """保存单场推荐 Markdown"""
    lines = [
        "# 足球竞猜推荐\n",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"共 {len(results)} 场\n",
        "\n## 单场推荐\n",
        "| 场次 | 对阵 | 胜平负 | 概率 | 让球 | 比分 | 总进球 | 半全场 | 置信度 | 分档 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        wdl = r.get("胜平负概率", {}) or {}
        top_prob = max(wdl.values()) if wdl else 0
        lines.append(
            f"| {r.get('场次编号','')} | {r.get('对阵','')} | "
            f"{r.get('胜平负推荐','')} | {top_prob:.2%} | "
            f"{r.get('让球推荐','')} | {r.get('比分推荐','')} | "
            f"{r.get('总进球推荐','')} | {r.get('半全场推荐','')} | "
            f"{float(r.get('置信度',0)):.2%} | {get_tier(float(r.get('置信度',0)))} |"
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Markdown 已保存: {filepath}")


def save_json(results: List[Dict], filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"JSON 已保存: {filepath}")


def save_csv(results: List[Dict], filepath: str):
    fields = ["场次编号", "对阵", "胜平负推荐", "让球推荐",
              "比分推荐", "总进球推荐", "半全场推荐", "置信度", "数据源"]
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {k: r.get(k, "") for k in fields}
            # 置信度格式化成百分比
            if row.get("置信度"):
                try:
                    row["置信度"] = f"{float(row['置信度']):.2%}"
                except Exception:
                    pass
            writer.writerow(row)
    logger.info(f"CSV 已保存: {filepath}")


# ============ 串关生成 ============
def _parse_parlay_ns() -> List[int]:
    """从 config.yaml 的 types 解析出 N 列表"""
    ns = []
    for t in PARLAY_TYPES:
        if "串" in t:
            try:
                ns.append(int(t.replace("串1", "").replace("串", "")))
            except ValueError:
                pass
    if not ns:
        ns = [2, 3, 4, 5]
    return sorted(set(ns))


def generate_parlays(results: List[Dict],
                     play_type: str = "胜平负",
                     min_confidence: float = None,
                     max_results: int = None) -> List[Dict]:
    """生成指定玩法的串关推荐"""
    if min_confidence is None:
        min_confidence = MIN_CONFIDENCE
    if max_results is None:
        max_results = MAX_RESULTS

    candidates = [r for r in results
                  if float(r.get("置信度", 0)) >= min_confidence]
    if len(candidates) < 2:
        logger.info(f"[{play_type}] 高置信度场次不足2场 ({len(candidates)}), 跳过")
        return []

    picked = []
    for r in candidates:
        item = _pick_play(r, play_type)
        if item and item["pick"] and item["prob"] > 0:
            picked.append(item)

    if len(picked) < 2:
        return []

    parlays = []
    parlay_ns = _parse_parlay_ns()
    for n in parlay_ns:
        if n > len(picked):
            continue
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
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4),
                                -x["平均置信度"]))
    return parlays[:max_results]


def generate_mixed_parlays(results: List[Dict],
                            min_confidence: float = 0.45,
                            max_results: int = None) -> List[Dict]:
    """混合串关：每场从5个玩法中选概率最高的那个"""
    if max_results is None:
        max_results = MAX_RESULTS

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
            # 比分/总进球 概率天然低，权重降级
            weight = 0.7 if pt in ("比分", "总进球") else 1.0
            score = item["prob"] * weight
            if best is None or score > best.get("_score", 0):
                item["_score"] = score
                best = item
        if best:
            picked.append(best)

    if len(picked) < 2:
        return []

    parlays = []
    parlay_ns = _parse_parlay_ns()
    for n in parlay_ns:
        if n > len(picked):
            continue
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
    parlays.sort(key=lambda x: (tier_order.get(x["分档"], 4),
                                -x["平均置信度"]))
    return parlays[:max_results]


def save_parlays(parlays: List[Dict], filepath: str, title: str = "串关推荐"):
    """保存串关推荐 Markdown"""
    if not parlays:
        return
    lines = [
        f"# {title}\n",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"共 {len(parlays)} 注\n",
    ]

    by_tier: Dict[str, List[Dict]] = {}
    for p in parlays:
        by_tier.setdefault(p["分档"], []).append(p)

    for tier in ["稳胆", "稳健", "搏冷", "极端"]:
        group = by_tier.get(tier, [])
        if not group:
            continue
        lines.append(f"\n## {tier}（{len(group)} 注）\n")
        lines.append("| 串关 | 投注内容 | 赔率 | 投入 | 收益 | 命中率 | 平均置信度 |")
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
def output_all(results: List[Dict],
               output_dir: str = "output",
               play_types: List[str] = None) -> Dict[str, Any]:
    """
    输出所有结果（单场 + 串关）。
    配置参数从 config.yaml 读取。
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. 单场推荐
    save_markdown(results, os.path.join(output_dir, f"recommend_{ts}.md"))
    save_json(results, os.path.join(output_dir, f"recommend_{ts}.json"))
    save_csv(results, os.path.join(output_dir, f"recommend_{ts}.csv"))

    # 2. 分玩法串关
    if play_types is None:
        play_types = ["胜平负", "让球", "比分", "总进球", "半全场"]

    summary = {"单场数": len(results), "串关": {}}

    for pt in play_types:
        parlays = generate_parlays(results, play_type=pt)
        if parlays:
            save_parlays(parlays,
                         os.path.join(output_dir, f"parlay_{pt}_{ts}.md"),
                         title=f"{pt}串关推荐")
            save_json(parlays,
                      os.path.join(output_dir, f"parlay_{pt}_{ts}.json"))
            summary["串关"][pt] = len(parlays)
        else:
            logger.info(f"[{pt}] 无符合条件的串关")

    # 3. 混合串关（门槛更高）
    mixed = generate_mixed_parlays(results, min_confidence=max(MIN_CONFIDENCE, 0.45))
    if mixed:
        save_parlays(mixed,
                     os.path.join(output_dir, f"parlay_mixed_{ts}.md"),
                     title="混合串关推荐")
        save_json(mixed, os.path.join(output_dir, f"parlay_mixed_{ts}.json"))
        summary["串关"]["混合"] = len(mixed)

    logger.info(f"全部输出完成: {summary}")
    return summary


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    # 用真实 analyze.py 输出模拟（重点验证 比分概率_top 字段）
    mock_results = [
        {
            "场次编号": "002",
            "对阵": "亚特兰大 vs 威尼斯",
            "联赛": "意甲",
            "让球": -1.0,
            "胜平负推荐": "胜",
            "胜平负概率": {"胜": 0.6282, "平": 0.1572, "负": 0.2146},
            "让球推荐": "让负",
            "让球概率": {"让胜": 0.3141, "让平": 0.2199, "让负": 0.4660},
            "比分推荐": "0:0",
            "比分概率_top": {"0:0": 0.166, "0:1": 0.166, "1:0": 0.1327,
                             "1:1": 0.1327, "0:2": 0.0829},
            "总进球推荐": "2球",
            "总进球概率": {"0球": 0.06, "1球": 0.17, "2球": 0.24,
                           "3球": 0.22, "4球": 0.16},
            "半全场推荐": "胜胜",
            "半全场概率": {"胜胜": 0.3852, "平胜": 0.2101, "负胜": 0.105,
                           "平平": 0.0964, "平负": 0.0718, "负负": 0.1316},
            "置信度": 0.4433,
            "数据源": "dongqiudi",
        },
        {
            "场次编号": "011",
            "对阵": "马德里竞技 vs 曼联",
            "联赛": "欧冠",
            "让球": 0.0,
            "胜平负推荐": "胜",
            "胜平负概率": {"胜": 0.4744, "平": 0.2582, "负": 0.2674},
            "让球推荐": "让胜",
            "让球概率": {"让胜": 0.4744, "让平": 0.2582, "让负": 0.2674},
            "比分推荐": "1:0",
            "比分概率_top": {"1:0": 0.14, "2:0": 0.09, "2:1": 0.10, "0:0": 0.08},
            "总进球推荐": "2球",
            "总进球概率": {"1球": 0.25, "2球": 0.28, "3球": 0.20, "0球": 0.08},
            "半全场推荐": "胜胜",
            "半全场概率": {"胜胜": 0.28, "平胜": 0.20, "负胜": 0.12},
            "置信度": 0.3190,
            "数据源": "dongqiudi",
        },
    ]

    # 降低门槛让测试能生成串关（mock 置信度偏低）
    import modules.output as out
    out.MIN_CONFIDENCE = 0.30  # 测试时覆盖
    summary = out.output_all(mock_results,
                              output_dir=str(_BASE_DIR / "output"))
    print(f"\n=== 输出摘要 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
