"""
足球竞猜智能推荐系统 - 主程序入口

功能：
1. 加载配置（config.yaml + config.local.yaml 深度合并）
2. 获取赛程（体彩 API / 本地文件 / 手动输入）
3. 逐场分析（历史战绩 + 情报 + 多维度加权）
4. 生成输出（MD / JSON / CSV + 串关推荐）

用法：
    python main.py                                    # 自动获取今日赛程
    python main.py --date 2026-10-13                  # 指定日期
    python main.py --file data/schedule.txt           # 从文件读赛程
    python main.py --manual "001 意甲 ...\n011 欧冠 ..."  # 手动输入
    python main.py --manual "..." --match-ids "54470920,54577210"
"""
import os
import sys
import logging
import argparse
import traceback
from typing import Dict, Any

import yaml

# ============ 路径修复（保证在任意目录下都能找到项目根） ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ============ 导入项目模块 ============
from modules.fetch_schedule import get_schedule
from modules.fetch_history import get_history
from modules.fetch_intel import get_intel
from modules.analyze import analyze_match
from modules.output import output_all


# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


# ============ 配置加载 ============
def _deep_merge(base: dict, override: dict) -> dict:
    """
    递归合并两个 dict（override 覆盖 base 的同名键）
    - dict 类型：递归合并
    - 其他类型：override 直接替换 base
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str = None) -> Dict[str, Any]:
    """
    加载配置：
    1. 先读 config.yaml
    2. 若存在 config.local.yaml，深度合并覆盖（用于本地 secrets）
    """
    if path is None:
        path = os.path.join(BASE_DIR, "config.yaml")

    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        logger.info(f"已加载配置: {path}")
    else:
        logger.warning(f"配置文件不存在: {path}，使用默认配置")

    local_path = os.path.join(BASE_DIR, "config.local.yaml")
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            local_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, local_cfg)
        logger.info(f"已合并本地配置: {local_path}")

    return cfg


# ============ 命令行参数 ============
def parse_args():
    parser = argparse.ArgumentParser(
        description="足球竞猜智能推荐系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--file", type=str, default=None,
                        help="赛程文件路径（txt/csv/json/excel）")
    parser.add_argument("--manual", type=str, default=None,
                        help="手动输入赛程（每行一场，支持字面量 \\n）")
    parser.add_argument("--match-ids", type=str, default=None,
                        help="逗号分隔的 match_id，会按顺序赋给每场比赛")
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径，默认 config.yaml")
    return parser.parse_args()


# ============ 赛程解析 ============
def _apply_match_ids(schedule, match_ids_str: str):
    """把 --match-ids 按顺序赋给赛程里的每场比赛"""
    if not match_ids_str or schedule is None or schedule.empty:
        return schedule
    ids = [x.strip() for x in match_ids_str.split(",") if x.strip()]
    if "match_id" not in schedule.columns:
        schedule = schedule.copy()
        schedule["match_id"] = ""
    for i, mid in enumerate(ids):
        if i < len(schedule):
            schedule.at[schedule.index[i], "match_id"] = mid
    return schedule


# ============ 主流程 ============
def main():
    args = parse_args()

    # ---------- 加载配置 ----------
    logger.info("=" * 60)
    logger.info("足球竞猜智能推荐系统 v1.0")
    logger.info("=" * 60)

    config = load_config(args.config)
    fd_token = config.get("football_data_token", "")
    if fd_token:
        logger.info(f"football_data_token: 已加载（{fd_token[:8]}...）")
    else:
        logger.warning("football_data_token 未配置，football-data 降级可能失效")

    # ---------- 步骤 1：获取赛程 ----------
    logger.info("-" * 60)
    logger.info("步骤 1/4: 获取赛程")
    logger.info("-" * 60)

    schedule = get_schedule(
        date=args.date,
        filepath=args.file,
        manual_text=args.manual,
    )

    if schedule is None or schedule.empty:
        logger.error("赛程为空，退出")
        sys.exit(1)

    # 应用 match_id
    schedule = _apply_match_ids(schedule, args.match_ids)

    logger.info(f"共获取 {len(schedule)} 场比赛")
    for _, row in schedule.iterrows():
        logger.info(
            f"  {row.get('场次编号', '?')} | {row.get('联赛', '?')} | "
            f"{row.get('主队', '?')} vs {row.get('客队', '?')}"
        )

    # ---------- 步骤 2：逐场分析 ----------
    logger.info("-" * 60)
    logger.info("步骤 2/4: 逐场分析")
    logger.info("-" * 60)

    results = []
    for idx, match in schedule.iterrows():
        try:
            home = match.get("主队", "")
            away = match.get("客队", "")
            league = match.get("联赛", "")
            match_id = match.get("match_id", "") or ""

            logger.info(f"[{idx + 1}/{len(schedule)}] 分析: {home} vs {away} ({league})")

            # 1. 获取历史战绩
            history = get_history(
                home, away,
                football_data_token=fd_token,
            ) or {}

            # 2. 获取情报
            intel = get_intel(
                home, away, league,
                match_id=match_id,
                football_data_token=fd_token,
            ) or {}

            # ---------- 数据补齐：intel 有数据则覆盖 history（history 已为 list[dict]，无需 DataFrame 清洗） ----------
            if intel:
                intel_recent = intel.get("recent", {}) or {}

                def _is_empty(v):
                    if v is None:
                        return True
                    if isinstance(v, (list, dict)):
                        return len(v) == 0
                    return False

                if not _is_empty(intel_recent.get("home")):
                    history["home_recent"] = intel_recent["home"]
                    logger.info(f"  ↳ 主队近绩: 使用懂球帝 {len(intel_recent['home'])} 场")
                elif not _is_empty(history.get("home_recent")):
                    logger.info(f"  ↳ 主队近绩: 使用 football-data/football-charts 数据")

                if not _is_empty(intel_recent.get("away")):
                    history["away_recent"] = intel_recent["away"]
                    logger.info(f"  ↳ 客队近绩: 使用懂球帝 {len(intel_recent['away'])} 场")
                elif not _is_empty(history.get("away_recent")):
                    logger.info(f"  ↳ 客队近绩: 使用 football-data/football-charts 数据")

                intel_h2h = intel.get("h2h", {}) or {}
                if intel_h2h.get("total", 0) > 0:
                    history["h2h"] = intel_h2h
                    logger.info(f"  ↳ H2H: 使用懂球帝 {intel_h2h.get('total', 0)} 场")
                elif not _is_empty(history.get("h2h")):
                    logger.info(f"  ↳ H2H: 使用 football-data/football-charts 数据")

            # 兜底：确保关键字段都是干净的 list/dict
            if not isinstance(history.get("home_recent"), list):
                history["home_recent"] = []
            if not isinstance(history.get("away_recent"), list):
                history["away_recent"] = []
            if not isinstance(history.get("h2h"), dict):
                history["h2h"] = {}

            # 3. 多维度分析
            result = analyze_match(match.to_dict(), history, intel)
            results.append(result)

            # 4. 日志输出推荐
            wdl_prob = result.get("胜平负概率", {})
            logger.info(
                f"  ✓ 推荐: {result['胜平负推荐']} "
                f"(胜{wdl_prob.get('胜', 0):.1%}/平{wdl_prob.get('平', 0):.1%}/负{wdl_prob.get('负', 0):.1%}) | "
                f"比分={result['比分推荐']} 让球={result['让球推荐']} "
                f"总进球={result['总进球推荐']} 半全场={result['半全场推荐']} | "
                f"置信度={result['置信度']:.2%}"
            )

        except Exception as e:
            logger.error(f"  ✗ 分析失败: {match.get('主队')} vs {match.get('客队')} - {e}")
            logger.debug(traceback.format_exc())
            continue

    if not results:
        logger.error("所有场次分析失败，退出")
        sys.exit(1)

    logger.info(f"分析完成，成功 {len(results)}/{len(schedule)} 场")

    # ---------- 步骤 3：生成输出 ----------
    logger.info("-" * 60)
    logger.info("步骤 3/4: 生成输出文件")
    logger.info("-" * 60)

    output_dir = config.get("output", {}).get("dir", "output")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(BASE_DIR, output_dir)

    try:
        bankroll = config.get("bankroll", 1000)
        min_conf = config.get("parlay", {}).get("confidence_threshold", 0.45)
        summary = output_all(results, output_dir=output_dir,
                             bankroll=bankroll, min_confidence=min_conf)
        logger.info(f"本金: {bankroll} 元, 串关最低置信度: {min_conf:.0%}")
        logger.info(f"输出摘要: {summary}")
    except Exception as e:
        logger.error(f"输出失败: {e}")
        logger.debug(traceback.format_exc())
        summary = {}

    # ---------- 步骤 4：控制台预览 ----------
    logger.info("-" * 60)
    logger.info("步骤 4/4: 控制台预览")
    logger.info("-" * 60)

    logger.info("")
    logger.info("=" * 100)
    logger.info(f"{'场次':<6} {'对阵':<30} {'胜平负':<8} {'比分':<8} {'让球':<8} {'总进球':<8} {'半全场':<8} {'置信度':<8}")
    logger.info("-" * 100)
    for r in results:
        logger.info(
            f"{r.get('场次编号', ''):<6} "
            f"{r.get('对阵', '')[:28]:<30} "
            f"{r.get('胜平负推荐', ''):<8} "
            f"{r.get('比分推荐', ''):<8} "
            f"{r.get('让球推荐', ''):<8} "
            f"{r.get('总进球推荐', ''):<8} "
            f"{r.get('半全场推荐', ''):<8} "
            f"{r.get('置信度', 0):<8.2%}"
        )
    logger.info("=" * 100)

    # 串关摘要
    if summary.get("串关"):
        logger.info("")
        logger.info("串关推荐生成情况：")
        for play_type, count in summary["串关"].items():
            logger.info(f"  - {play_type}: {count} 注")
    else:
        logger.info("")
        logger.info("本次未生成串关（置信度不足）")

    logger.info("")
    logger.info("=" * 60)
    logger.info("完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)