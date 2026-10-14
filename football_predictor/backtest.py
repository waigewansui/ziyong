"""
回测框架 V1

功能：
1. 从 CSV 加载历史比赛（含真实结果）
2. 逐期跑模型，记录推荐
3. 对比推荐 vs 实际，计算命中率
4. 模拟凯利下注盈亏
5. 生成回测报告

历史 CSV 格式（UTF-8 编码）：
    日期,场次编号,联赛,主队,客队,让球,
    胜平负结果,比分,总进球,半全场结果
    2026-09-01,001,英超,曼联,利物浦,-1,负,0:1,1球,平负
    ...

用法：
    python backtest.py --csv history.csv
    python backtest.py --mock          # 用内置假数据测试
"""
import os
import sys
import csv
import json
import glob
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from modules.fetch_intel import get_intel
from modules.analyze import analyze_match
from modules.output import kelly_stake, get_tier


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backtest")


# ============ 1. 加载历史数据 ============
def load_history_csv(path: str) -> List[Dict[str, Any]]:
    """从 CSV 加载历史比赛"""
    records = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "日期": row.get("日期", "").strip(),
                "场次编号": row.get("场次编号", "").strip(),
                "联赛": row.get("联赛", "").strip(),
                "主队": row.get("主队", "").strip(),
                "客队": row.get("客队", "").strip(),
                "让球": row.get("让球", "0").strip(),
                "真实胜平负": row.get("胜平负结果", "").strip(),
                "真实比分": row.get("比分", "").strip(),
                "真实总进球": row.get("总进球", "").strip(),
                "真实半全场": row.get("半全场结果", "").strip(),
            })
    logger.info(f"加载历史记录: {len(records)} 条")
    return records


def load_mock_history() -> List[Dict[str, Any]]:
    """内置假数据（用于框架测试）"""
    return [
        {
            "日期": "2026-09-01", "场次编号": "001", "联赛": "意甲",
            "主队": "亚特兰大", "客队": "威尼斯", "让球": "-1",
            "真实胜平负": "胜", "真实比分": "2:0",
            "真实总进球": "2球", "真实半全场": "平胜",
        },
        {
            "日期": "2026-09-02", "场次编号": "002", "联赛": "英超",
            "主队": "曼城", "客队": "阿森纳", "让球": "-1",
            "真实胜平负": "平", "真实比分": "1:1",
            "真实总进球": "2球", "真实半全场": "平平",
        },
        {
            "日期": "2026-09-03", "场次编号": "003", "联赛": "西甲",
            "主队": "皇马", "客队": "巴萨", "让球": "0",
            "真实胜平负": "负", "真实比分": "1:2",
            "真实总进球": "3球", "真实半全场": "平负",
        },
    ]


# ============ 2. 跑单场模型 ============
def run_model(record: Dict[str, Any],
              match_id: str = None,
              fd_token: str = "") -> Dict[str, Any]:
    """对单场历史记录跑模型（不含真实结果）"""
    match = {
        "场次编号": record.get("场次编号", ""),
        "联赛": record.get("联赛", ""),
        "比赛时间": record.get("日期", ""),
        "主队": record.get("主队", ""),
        "客队": record.get("客队", ""),
        "让球": record.get("让球", "0"),
    }
    try:
        intel = get_intel(match["主队"], match["客队"], match["联赛"],
                          match_id=match_id, football_data_token=fd_token)
        history = {"h2h": {}, "home_recent": [], "away_recent": []}

        # 从 intel 补齐（和 main.py 一致）
        if intel:
            recent = intel.get("recent", {}) or {}
            if recent.get("home"):
                history["home_recent"] = recent["home"]
            if recent.get("away"):
                history["away_recent"] = recent["away"]
            if intel.get("h2h"):
                history["h2h"] = intel["h2h"]

        result = analyze_match(match, history, intel)
        return result
    except Exception as e:
        logger.error(f"  模型运行失败 {record.get('主队')} vs {record.get('客队')}: {e}")
        return {}


# ============ 3. 对比推荐与真实 ============
def compare_result(result: Dict, record: Dict) -> Dict[str, Any]:
    """对比单场推荐与实际结果"""
    cmp = {
        "场次编号": record.get("场次编号", ""),
        "对阵": f"{record.get('主队')} vs {record.get('客队')}",
        "日期": record.get("日期", ""),
        "模型推荐": {},
        "真实赔率": {},
        "模型概率": 0.5,
        "真实结果": {
            "胜平负": record.get("真实胜平负", ""),
            "比分": record.get("真实比分", ""),
            "总进球": record.get("真实总进球", ""),
            "半全场": record.get("真实半全场", ""),
        },
        "命中": {},
    }

    if not result:
        return cmp

    # 胜平负
    wdl_pick = result.get("胜平负推荐", "")
    wdl_real = record.get("真实胜平负", "")
    cmp["模型推荐"]["胜平负"] = wdl_pick
    cmp["命中"]["胜平负"] = (wdl_pick == wdl_real) if wdl_real else None

    # 真实赔率 + 模型概率
    cmp["真实赔率"] = result.get("真实赔率", {}) or {}
    cmp["模型概率"] = result.get("胜平负概率", {}).get(wdl_pick, 0.5)

    # 让球
    hd_pick = result.get("让球推荐", "")
    handicap = float(record.get("让球", 0) or 0)
    real_score = record.get("真实比分", "")
    hd_real = _derive_real_handicap(real_score, handicap)
    cmp["模型推荐"]["让球"] = hd_pick
    cmp["命中"]["让球"] = (hd_pick == hd_real) if hd_real else None

    # 比分
    sc_pick = result.get("比分推荐", "")
    sc_real = record.get("真实比分", "")
    cmp["模型推荐"]["比分"] = sc_pick
    cmp["命中"]["比分"] = (sc_pick == sc_real) if sc_real else None

    # 总进球
    tg_pick = result.get("总进球推荐", "")
    tg_real = record.get("真实总进球", "")
    cmp["模型推荐"]["总进球"] = tg_pick
    cmp["命中"]["总进球"] = (tg_pick == tg_real) if tg_real else None

    # 半全场
    hf_pick = result.get("半全场推荐", "")
    hf_real = record.get("真实半全场", "")
    cmp["模型推荐"]["半全场"] = hf_pick
    cmp["命中"]["半全场"] = (hf_pick == hf_real) if hf_real else None

    return cmp


def _derive_real_handicap(score_str: str, handicap: float) -> str:
    """从真实比分推导让球结果"""
    if not score_str or ":" not in score_str:
        return ""
    try:
        h, a = map(int, score_str.replace("-", ":").split(":"))
    except Exception:
        return ""
    diff = h - a
    adjusted = diff + handicap
    if adjusted > 0:
        return "让胜"
    elif adjusted == 0:
        return "让平"
    else:
        return "让负"


# ============ 4. 凯利盈亏模拟 ============
def simulate_kelly(cmp_list: List[Dict], bankroll: float = 1000.0) -> Dict[str, Any]:
    """模拟凯利下注的累计盈亏"""
    balance = bankroll
    total_stake = 0.0
    total_return = 0.0
    bet_count = 0
    win_count = 0

    for cmp in cmp_list:
        wdl_pick = cmp["模型推荐"].get("胜平负", "")
        wdl_hit = cmp["命中"].get("胜平负")
        if not wdl_pick or wdl_hit is None:
            continue

        # 用真实赔率
        real_odds = cmp.get("真实赔率", {}) or {}
        odds = float(real_odds.get(wdl_pick, 1.8))
        prob = float(cmp.get("模型概率", 0.5))
        k = kelly_stake(prob, odds, balance)
        stake = k["stake_final"]

        if stake <= 0:
            continue

        bet_count += 1
        total_stake += stake
        balance -= stake

        if wdl_hit:
            win_count += 1
            ret = stake * odds
            balance += ret
            total_return += ret

    return {
        "初始本金": bankroll,
        "最终余额": round(balance, 2),
        "净盈亏": round(balance - bankroll, 2),
        "下注次数": bet_count,
        "命中次数": win_count,
        "下注总额": round(total_stake, 2),
        "回收总额": round(total_return, 2),
        "ROI": round((balance - bankroll) / bankroll, 4) if bankroll > 0 else 0,
        "命中率": round(win_count / bet_count, 4) if bet_count > 0 else 0,
    }


# ============ 5. 汇总统计 ============
def summarize(cmp_list: List[Dict]) -> Dict[str, Any]:
    """汇总各玩法命中率"""
    stats = {
        "总场次": len(cmp_list),
        "各玩法": {},
    }
    for play in ["胜平负", "让球", "比分", "总进球", "半全场"]:
        valid = [c for c in cmp_list if c["命中"].get(play) is not None]
        hits = [c for c in valid if c["命中"].get(play)]
        stats["各玩法"][play] = {
            "有效场次": len(valid),
            "命中": len(hits),
            "命中率": round(len(hits) / len(valid), 4) if valid else 0,
        }
    return stats


# ============ 6. 生成报告 ============
def save_report(cmp_list: List[Dict], summary: Dict, kelly: Dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_path = os.path.join(output_dir, f"backtest_{ts}.md")
    json_path = os.path.join(output_dir, f"backtest_{ts}.json")

    # Markdown 报告
    lines = [
        "# 回测报告\n",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"\n## 一、整体统计\n",
        f"- 总场次：{summary['总场次']}",
        f"- 有效场次（有真实结果）：{sum(s['有效场次'] for s in summary['各玩法'].values()) // 5}",
        "\n## 二、各玩法命中率\n",
        "| 玩法 | 有效场次 | 命中 | 命中率 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for play, s in summary["各玩法"].items():
        lines.append(f"| {play} | {s['有效场次']} | {s['命中']} | {s['命中率']:.2%} |")

    lines.extend([
        "\n## 三、凯利盈亏模拟\n",
        f"- 初始本金：{kelly['初始本金']} 元",
        f"- 最终余额：{kelly['最终余额']} 元",
        f"- 净盈亏：{kelly['净盈亏']} 元",
        f"- ROI：{kelly['ROI']:.2%}",
        f"- 下注次数：{kelly['下注次数']}",
        f"- 命中次数：{kelly['命中次数']}",
        f"- 命中率：{kelly['命中率']:.2%}",
        "\n## 四、逐场对比\n",
        "| 场次 | 日期 | 对阵 | 胜平负 | 让球 | 比分 | 总进球 | 半全场 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for c in cmp_list:
        hits = c["命中"]
        def mark(play):
            r = hits.get(play)
            return "✅" if r else ("❌" if r is False else "—")
        lines.append(
            f"| {c['场次编号']} | {c['日期']} | {c['对阵']} | "
            f"{c['模型推荐'].get('胜平负','')}{mark('胜平负')} | "
            f"{c['模型推荐'].get('让球','')}{mark('让球')} | "
            f"{c['模型推荐'].get('比分','')}{mark('比分')} | "
            f"{c['模型推荐'].get('总进球','')}{mark('总进球')} | "
            f"{c['模型推荐'].get('半全场','')}{mark('半全场')} |"
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"报告已保存: {md_path}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"cmp_list": cmp_list, "summary": summary, "kelly": kelly},
                  f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已保存: {json_path}")

    return md_path


# ============ 主流程 ============
def main():
    parser = argparse.ArgumentParser(description="回测框架")
    parser.add_argument("--csv", type=str, default=None,
                        help="历史数据 CSV 路径")
    parser.add_argument("--mock", action="store_true",
                        help="使用内置假数据")
    parser.add_argument("--bankroll", type=float, default=1000.0,
                        help="凯利本金")
    parser.add_argument("--output", type=str, default="output/backtest",
                        help="报告输出目录")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("回测框架启动")
    logger.info("=" * 60)

    # 1. 加载数据
    if args.mock:
        records = load_mock_history()
    elif args.csv:
        records = load_history_csv(args.csv)
    else:
        logger.error("请指定 --csv 或 --mock")
        sys.exit(1)

    if not records:
        logger.error("历史数据为空")
        sys.exit(1)

    # 2. 逐场跑模型
    logger.info(f"开始回测 {len(records)} 场...")
    cmp_list = []
    for i, rec in enumerate(records, 1):
        logger.info(f"[{i}/{len(records)}] {rec['主队']} vs {rec['客队']}")
        result = run_model(rec)
        cmp = compare_result(result, rec)
        cmp_list.append(cmp)

    # 3. 汇总
    summary = summarize(cmp_list)
    kelly = simulate_kelly(cmp_list, bankroll=args.bankroll)

    # 4. 报告
    md_path = save_report(cmp_list, summary, kelly, args.output)

    # 5. 控制台输出
    logger.info("")
    logger.info("=" * 60)
    logger.info("回测汇总")
    logger.info("=" * 60)
    for play, s in summary["各玩法"].items():
        logger.info(f"  {play}: {s['命中']}/{s['有效场次']} = {s['命中率']:.2%}")
    logger.info(f"  凯利盈亏: {kelly['净盈亏']} 元 (ROI {kelly['ROI']:.2%})")
    logger.info(f"  报告: {md_path}")


if __name__ == "__main__":
    main()
