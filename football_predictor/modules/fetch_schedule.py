"""
赛程获取模块
支持：中国体彩网 / 本地文件 / 手动输入
"""
import os
import re
import time
import random
import logging
import pandas as pd
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

SPORTTERY_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"

WEEKDAY_MAP = {
    0: "周一", 1: "周二", 2: "周三", 3: "周四",
    4: "周五", 5: "周六", 6: "周日",
}


def get_today_weekday() -> str:
    """获取今天是周几（中文）"""
    return WEEKDAY_MAP[datetime.now().weekday()]


def fetch_from_sporttery(date: str = None) -> pd.DataFrame:
    """从中国体彩网获取当日赛程"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.sporttery.cn/",
    }
    params = {
        "matchBeginDate": date,
        "matchEndDate": date,
        "pageNo": 1,
        "pageSize": 100,
    }

    for attempt in range(3):
        try:
            delay = random.uniform(1.0, 3.0)
            logger.info(f"体彩网请求 ({attempt+1}/3)，延时 {delay:.1f}s ...")
            time.sleep(delay)
            resp = requests.get(SPORTTERY_URL, params=params,
                                headers=headers, timeout=15)
            resp.raise_for_status()
            df = _parse_sporttery(resp.json())
            logger.info(f"体彩网抓取成功，共 {len(df)} 场")
            return df
        except Exception as e:
            logger.warning(f"体彩网抓取失败 ({attempt+1}/3): {e}")

    logger.error("体彩网抓取失败（已重试 3 次）")
    return pd.DataFrame()


def _parse_sporttery(data: dict) -> pd.DataFrame:
    """解析体彩网返回数据"""
    rows = []
    try:
        match_list = data.get("value", {}).get("matchInfoList", [])
        for match in match_list:
            for m in match.get("subMatchList", []):
                rows.append({
                    "场次编号": m.get("matchNumStr", ""),
                    "联赛": m.get("leagueAbbName", ""),
                    "比赛时间": (
                        m.get("matchDate", "") + " " + m.get("matchTime", "")
                    ).strip(),
                    "主队": m.get("homeTeamAbbName", ""),
                    "客队": m.get("awayTeamAbbName", ""),
                    "让球": m.get("hhad", {}).get("goalLine", ""),
                    "胜": m.get("had", {}).get("h", ""),
                    "平": m.get("had", {}).get("d", ""),
                    "负": m.get("had", {}).get("a", ""),
                    "让球胜": m.get("hhad", {}).get("h", ""),
                    "让球平": m.get("hhad", {}).get("d", ""),
                    "让球负": m.get("hhad", {}).get("a", ""),
                })
    except Exception as e:
        logger.error(f"解析体彩数据失败: {e}")
    return pd.DataFrame(rows)


def fetch_from_file(filepath: str) -> pd.DataFrame:
    """从本地文件读取赛程"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        return pd.read_csv(filepath)
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(filepath)
    elif ext == ".json":
        return pd.read_json(filepath)
    elif ext == ".txt":
        return _parse_txt(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def _parse_line(line: str) -> dict | None:
    """
    解析单行文本赛程，容忍日期时间中的空格。
    支持格式示例：
      001 英超 2026-10-18 20:00 曼联 利物浦
      001, 英超, 2026-10-18 20:00, 曼联, 利物浦
    """
    # 先把中文逗号替换成空格，统一分隔符
    line = line.replace("，", " ")
    # 用正则提取 YYYY-MM-DD HH:MM 或 HH:MM:SS 模式
    dt_match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)", line)
    if dt_match:
        datetime_str = dt_match.group(1)
        # 把日期时间整体替换成一个占位符，避免其中的空格被切分
        line_wo_dt = line.replace(datetime_str, "|DT|")
    else:
        datetime_str = ""
        line_wo_dt = line

    parts = re.split(r"[\s,]+", line_wo_dt.strip())
    parts = [p for p in parts if p]  # 去空
    # 把占位符放回
    for i, p in enumerate(parts):
        if p == "|DT|":
            parts[i] = datetime_str

    # 最少需要：编号 / 联赛 / 比赛时间 / 主队 / 客队
    if len(parts) < 5:
        return None

    return {
        "场次编号": parts[0],
        "联赛": parts[1],
        "比赛时间": parts[2],
        "主队": parts[3],
        "客队": parts[4],
    }


def _normalize_newlines(text: str) -> str:
    """统一换行符：字面量 \\r\\n / \\n / 真实 \\r\\n 全部 → 真实 \\n"""
    # GitHub Actions workflow_dispatch 里的换行符会变成字面量 "\\n"（反斜杠+n）
    # 这里把三种情况都归一化成真正的 \n
    text = text.replace("\\r\\n", "\n")   # 字面量 \r\n
    text = text.replace("\\n", "\n")      # 字面量 \n
    text = text.replace("\r\n", "\n")     # 真实 Windows CRLF
    text = text.replace("\r", "\n")       # 真实旧 Mac CR
    return text


def _parse_schedule_text(text: str) -> pd.DataFrame:
    """
    统一解析赛程文本（供 fetch_from_manual 和 _parse_txt 共用）。
    容忍：空格/中文逗号/制表符分隔；日期时间里有空格；多字段 vs 少字段。

    支持格式：
      001 英超 2026-10-18 20:00 曼联 利物浦
      001,英超,2026-10-18 20:00,曼联,利物浦
      001 英超 2026-10-18 曼联 利物浦 -1
    """
    text = _normalize_newlines(text)
    rows = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # 先把中文逗号、制表符统一替换成空格
        line = re.sub(r"[，\t]+", " ", line)

        # 用正则提取 YYYY-MM-DD HH:MM(:SS)?，避免其中空格被切分
        dt_match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)", line)
        if dt_match:
            datetime_str = dt_match.group(1)
            line_wo_dt = line.replace(datetime_str, "|DT|")
        else:
            datetime_str = ""
            line_wo_dt = line

        parts = re.split(r"[\s,]+", line_wo_dt.strip())
        parts = [p for p in parts if p]
        # 占位符还原
        for i, p in enumerate(parts):
            if p == "|DT|":
                parts[i] = datetime_str

        if len(parts) < 4:
            logger.warning(f"跳过格式不匹配行: {raw_line!r}")
            continue

        # 4 列容错：缺失比赛时间（编号 / 联赛 / 主队 / 客队）
        if len(parts) == 4:
            row = {
                "场次编号": parts[0],
                "联赛": parts[1],
                "比赛时间": "",
                "主队": parts[2],
                "客队": parts[3],
            }
            rows.append(row)
            continue

        # 5+ 列：编号 / 联赛 / 时间 / 主队 / 客队 [/让球]
        row = {
            "场次编号": parts[0],
            "联赛": parts[1],
            "比赛时间": parts[2],
            "主队": parts[3],
            "客队": parts[4],
        }
        if len(parts) > 5:
            row["让球"] = parts[5]
        rows.append(row)

    logger.info(f"赛程文本解析：{len(rows)} 场")
    return pd.DataFrame(rows)


def _parse_txt(filepath: str) -> pd.DataFrame:
    """解析 txt 格式赛程（统一走 _parse_schedule_text）"""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    return _parse_schedule_text(text)


def fetch_from_manual(text: str) -> pd.DataFrame:
    """手动输入解析（兼容 GitHub Actions bash 字面量 \\n）"""
    if not text:
        return pd.DataFrame()
    return _parse_schedule_text(text)


def get_schedule(date: str = None, filepath: str = None,
                 manual_text: str = None) -> pd.DataFrame:
    """统一入口：按优先级获取赛程"""
    if manual_text:
        logger.info("使用手动输入赛程")
        return fetch_from_manual(manual_text)

    if filepath and os.path.exists(filepath):
        logger.info(f"使用本地文件: {filepath}")
        return fetch_from_file(filepath)

    logger.info("尝试从体彩官网获取赛程")
    df = fetch_from_sporttery(date)
    if not df.empty:
        return df

    logger.error("所有数据源均失败，请手动输入")
    return pd.DataFrame()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    print(f"今天是: {get_today_weekday()} ({datetime.now().strftime('%Y-%m-%d')})")
    df = get_schedule()
    if df.empty:
        print("未获取到赛程")
    else:
        print(f"\n共 {len(df)} 场比赛：")
        print(df.to_string(index=False))
