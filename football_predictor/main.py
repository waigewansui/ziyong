#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
football_predictor 主入口
足球赛事分析与预测工具

完整流水线：
  1. load_config() → 读 config.yaml
  2. get_schedule() → 体彩赛程 / 手动输入
  3. 对每场循环：get_history() + get_intel() + analyze_match()
  4. output_all() → 单场推荐 + 串关推荐

用法：
  python main.py                  # 用体彩当日赛程
  python main.py --date 2026-10-14
  python main.py --manual "001 意甲 2026-10-13 亚特兰大 威尼斯\n002 欧冠 2026-10-13 马竞 曼联"
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent

log = logging.getLogger("main")


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base，dict 递归、非 dict 直接替换"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config() -> dict:
    """加载配置：config.yaml + config.local.yaml（若存在则覆盖）"""
    cfg_path = BASE_DIR / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    local_path = BASE_DIR / "config.local.yaml"
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            local_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, local_cfg)
        log.info("已合并 config.local.yaml")

    return cfg


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    log = logging.getLogger("main")

    # ---------- 参数 ----------
    parser = argparse.ArgumentParser(description="足球竞猜分析")
    parser.add_argument("--date", help="比赛日期 YYYY-MM-DD")
    parser.add_argument("--manual", help="手动输入赛程文本 (\\n 分隔)")
    parser.add_argument("--file", help="本地赛程文件 (.csv/.xlsx/.txt)")
    parser.add_argument("--match-ids",
                        help="懂球帝 match_id 列表, 逗号分隔 (与 schedule 行数一一对应)")
    args = parser.parse_args()

    # ---------- 载入模块 ----------
    from modules.fetch_schedule import get_schedule
    from modules.fetch_history import get_history
    from modules.fetch_intel import get_intel
    from modules.analyze import analyze_match
    from modules.output import output_all

    # ---------- 配置 ----------
    cfg = load_config()
    fd_token = cfg.get("football_data_token", "")
    output_dir = str(BASE_DIR / cfg.get("output", {}).get("dir", "output"))
    min_conf = cfg.get("parlay", {}).get("min_confidence", 0.55)
    max_res = cfg.get("parlay", {}).get("max_results", 20)

    print("=" * 60)
    print("  Football Predictor - 足球赛事分析与预测")
    print("=" * 60)
    print(f"输出目录: {output_dir}")
    print(f"串关阈值: 置信度 ≥ {min_conf:.0%}, 最多 {max_res} 注")

    # ---------- 1. 赛程 ----------
    print("\n[1/4] 获取赛程...")
    schedule = get_schedule(
        date=args.date,
        filepath=args.file,
        manual_text=args.manual,
    )
    if schedule.empty:
        log.error("未获取到任何赛程，退出")
        sys.exit(1)
    print(f"  → 共 {len(schedule)} 场")

    # 懂球帝 match_id 映射（可选）
    match_ids = []
    if args.match_ids:
        match_ids = [m.strip() for m in args.match_ids.split(",") if m.strip()]

    # ---------- 2-3. 逐场分析 ----------
    print(f"\n[2/4] 逐场分析 (history + intel + analyze)...")
    results = []
    total = len(schedule)

    for idx, (_, row) in enumerate(schedule.iterrows()):
        home = row.get("主队", "")
        away = row.get("客队", "")
        league = row.get("联赛", "")
        match = row.to_dict()

        print(f"\n  [{idx+1}/{total}] {home} vs {away} ({league})")

        # match_id 可选传入（加速 + 避免自动搜索失败）
        mid = match_ids[idx] if idx < len(match_ids) else None

        try:
            t0 = time.time()
            history = get_history(home, away, football_data_token=fd_token)
            intel = get_intel(home, away, league,
                              match_id=mid,
                              football_data_token=fd_token)
            r = analyze_match(match, history, intel)
            elapsed = time.time() - t0
            print(f"    → {r['胜平负推荐']} "
                  f"({r['胜平负概率']['胜']:.0%}/{r['胜平负概率']['平']:.0%}/{r['胜平负概率']['负']:.0%}) "
                  f"置信度={r['置信度']:.2%}  [{elapsed:.1f}s]")
            results.append(r)
        except Exception as e:
            log.error(f"    → 分析失败: {e}", exc_info=True)
            continue

    if not results:
        log.error("全部场次分析失败")
        sys.exit(1)

    # ---------- 4. 输出 ----------
    print(f"\n[3/4] 生成输出文件...")
    summary = output_all(results, output_dir=output_dir)
    print(f"  → {summary}")

    print(f"\n[4/4] 完成！输出文件在: {output_dir}/")
    print("=" * 60)

    # ---------- 控制台预览 ----------
    print("\n📊 单场推荐预览：")
    print("-" * 70)
    print(f"{'场次':<6} {'对阵':<28} {'胜平负':<14} {'置信度':<8} {'数据源'}")
    print("-" * 70)
    for r in results:
        wdl = r.get("胜平负概率", {})
        top_p = max(wdl.values()) if wdl else 0
        print(
            f"{r.get('场次编号',''):<6} "
            f"{r.get('对阵',''):<28} "
            f"{r.get('胜平负推荐','')}({top_p:.0%}){'':<8} "
            f"{r.get('置信度',0):.2%}   "
            f"{r.get('数据源','')}"
        )


if __name__ == "__main__":
    main()
