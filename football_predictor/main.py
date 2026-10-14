"""
主程序 V4
新增：
- 方向1：过滤低置信度（< 40%）
- 方向2：只留模型与赔率共振的场次
- 方向7、8：天气 + 裁判
"""
import os
import sys
import logging
import argparse
import traceback
from typing import Dict, Any

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from modules.fetch_schedule import get_schedule
from modules.fetch_history import get_history
from modules.fetch_intel import get_intel
from modules.fetch_weather import fetch_weather
from modules.fetch_referee import fetch_referee
from modules.analyze import analyze_match
from modules.output import output_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def _deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "config.yaml")
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    local = os.path.join(BASE_DIR, "config.local.yaml")
    if os.path.exists(local):
        with open(local, "r", encoding="utf-8") as f:
            cfg = _deep_merge(cfg, yaml.safe_load(f) or {})
    return cfg


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=str, default=None)
    p.add_argument("--file", type=str, default=None)
    p.add_argument("--manual", type=str, default=None)
    p.add_argument("--match-ids", type=str, default=None)
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--min-confidence", type=float, default=0.40,
                   help="最低置信度过滤（默认 0.40）")
    p.add_argument("--no-filter", action="store_true",
                   help="关闭置信度和共振过滤")
    return p.parse_args()


def _apply_match_ids(schedule, ids_str):
    if not ids_str or schedule is None or schedule.empty:
        return schedule
    ids = [x.strip() for x in ids_str.split(",") if x.strip()]
    if "match_id" not in schedule.columns:
        schedule = schedule.copy()
        schedule["match_id"] = ""
    for i, mid in enumerate(ids):
        if i < len(schedule):
            schedule.at[schedule.index[i], "match_id"] = mid
    return schedule


# ========== 方向2：共振检测 ==========
def is_resonance(result) -> bool:
    """模型推荐方向 = 赔率最低方向"""
    pick = result.get("胜平负推荐", "")
    odds = result.get("真实赔率", {}) or {}
    if not odds or not all(odds.get(k) for k in ["胜", "平", "负"]):
        return True  # 没赔率数据，保留
    min_odds_pick = min(odds, key=lambda k: odds[k])
    return pick == min_odds_pick


def main():
    args = parse_args()
    logger.info("=" * 60)
    logger.info("数据查询分析系统 v4.0")
    logger.info("=" * 60)

    config = load_config(args.config)
    fd_token = config.get("football_data_token", "")

    # 步骤1：赛程
    logger.info("-" * 60)
    logger.info("步骤 1/5: 获取赛程")
    schedule = get_schedule(args.date, args.file, args.manual)
    if schedule is None or schedule.empty:
        logger.error("赛程为空，退出")
        sys.exit(1)
    schedule = _apply_match_ids(schedule, args.match_ids)
    logger.info(f"共 {len(schedule)} 场")

    # 步骤2：分析
    logger.info("-" * 60)
    logger.info("步骤 2/5: 逐场分析")
    all_results = []
    for idx, match in schedule.iterrows():
        try:
            home = match.get("主队", "")
            away = match.get("客队", "")
            league = match.get("联赛", "")
            match_id = match.get("match_id", "") or match.get("场次编号", "")

            logger.info(f"[{idx+1}/{len(schedule)}] {home} vs {away} ({league})")

            history = get_history(home, away, football_data_token=fd_token) or {}
            intel = get_intel(home, away, league, match_id=match_id,
                              football_data_token=fd_token) or {}

            # 补数据
            if intel:
                recent = intel.get("recent", {}) or {}
                def _is_empty(x):
                    if x is None:
                        return True
                    if hasattr(x, "empty") and hasattr(x, "__len__"):
                        return x.empty
                    if isinstance(x, (list, dict)):
                        return len(x) == 0
                    return False
                if recent.get("home") and _is_empty(history.get("home_recent")):
                    history["home_recent"] = recent["home"]
                if recent.get("away") and _is_empty(history.get("away_recent")):
                    history["away_recent"] = recent["away"]
                if intel.get("h2h", {}).get("total", 0) > 0 and _is_empty(history.get("h2h")):
                    history["h2h"] = intel["h2h"]

            # 方向7、8：天气 + 裁判
            weather = fetch_weather(home)
            referee = fetch_referee(match_id, intel)

            result = analyze_match(match.to_dict(), history, intel,
                                   weather=weather, referee=referee)
            all_results.append(result)

            logger.info(f"  ✓ {result['胜平负推荐']} | "
                        f"比分={result['比分推荐']} | "
                        f"置信度={result['置信度']:.2%}")
        except Exception as e:
            logger.error(f"  ✗ 失败: {e}")
            logger.debug(traceback.format_exc())

    if not all_results:
        logger.error("全部失败")
        sys.exit(1)

    # 步骤3：方向1+2 过滤
    logger.info("-" * 60)
    logger.info("步骤 3/5: 过滤低置信度 + 共振")
    original_count = len(all_results)

    if not args.no_filter:
        # 方向1：置信度过滤
        results = [r for r in all_results if r.get("置信度", 0) >= args.min_confidence]
        logger.info(f"  置信度 ≥ {args.min_confidence:.0%}: {len(results)}/{original_count} 场")

        # 方向2：共振过滤
        results = [r for r in results if is_resonance(r)]
        logger.info(f"  模型与赔率共振: {len(results)}/{original_count} 场")

        if not results:
            logger.warning("过滤后为空，跳过过滤直接用全部结果")
            results = all_results
    else:
        results = all_results
        logger.info("  过滤已关闭")

    # 步骤4：输出
    logger.info("-" * 60)
    logger.info("步骤 4/5: 生成输出")
    output_dir = config.get("output", {}).get("dir", "output")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(BASE_DIR, output_dir)
    bankroll = config.get("bankroll", 1000)
    output_all(results, output_dir=output_dir, bankroll=bankroll)

    # 步骤5：预览
    logger.info("-" * 60)
    logger.info("步骤 5/5: 预览")
    logger.info("")
    logger.info("=" * 110)
    logger.info(f"{'场次':<8} {'对阵':<28} {'胜平负':<6} {'比分':<6} {'置信度':<8} {'天气':<12} {'裁判':<8}")
    logger.info("-" * 110)
    for r in results:
        weather_desc = (r.get("天气", {}) or {}).get("description", "—")[:8]
        referee_name = (r.get("裁判", {}) or {}).get("name", "—")[:6]
        logger.info(f"{r.get('场次编号', ''):<8} "
                    f"{r.get('对阵', '')[:26]:<28} "
                    f"{r.get('胜平负推荐', ''):<6} "
                    f"{r.get('比分推荐', ''):<6} "
                    f"{r.get('置信度', 0):<8.2%} "
                    f"{weather_desc:<12} {referee_name:<8}")
    logger.info("=" * 110)
    logger.info(f"完成！原始 {original_count} 场 → 过滤后 {len(results)} 场")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"异常: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)
