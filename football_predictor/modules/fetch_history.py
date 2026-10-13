"""
历史战绩采集模块

数据源优先级:
  1. football-data.org   (有 token, 覆盖 12 顶级联赛, 含欧冠/欧联)
  2. football-charts.com (无 key 免费兜底, 93 联赛)

统一输出结构: {"h2h": DataFrame, "home_recent": DataFrame, "away_recent": DataFrame}
"""
import logging
import random
import time
import urllib.parse
from functools import lru_cache
from datetime import datetime

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# football-data.org
# ---------------------------------------------------------------------------
FD_BASE = "https://api.football-data.org/v4"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _fd_headers(token: str = "") -> dict:
    """按 token 动态构建请求头（token 为空时 football-data 会 403，降级用 football-charts）"""
    return {
        "X-Auth-Token": token or "",
        "User-Agent": _UA,
    }


# 兼容旧引用
FD_HEADERS = _fd_headers()

# ---------------------------------------------------------------------------
# football-charts.com (降级)
# ---------------------------------------------------------------------------
FC_BASE = "https://footballcharts-backend.onrender.com/api/v1"
FC_HEADERS = {"User-Agent": FD_HEADERS["User-Agent"]}

# ---------------------------------------------------------------------------
# 队名映射表: 中文 -> (football-data team_id, football-charts 英文名, FC 联赛)
# football-data team_id: https://api.football-data.org/v4/teams?limit=N
# ---------------------------------------------------------------------------
TEAM_MAP: dict[str, tuple[int | None, str | None, str | None]] = {
    # 英超 premier
    "曼联": (66, "Manchester Utd", "premier"),
    "曼城": (65, "Manchester City", "premier"),
    "利物浦": (64, "Liverpool", "premier"),
    "阿森纳": (57, "Arsenal", "premier"),
    "切尔西": (61, "Chelsea", "premier"),
    "热刺": (73, "Tottenham", "premier"),
    "布伦特福德": (94, "Brentford", "premier"),
    "布莱顿": (103, "Brighton", "premier"),
    "西汉姆": (563, "West Ham", "premier"),
    "纽卡斯尔": (67, "Newcastle", "premier"),
    # 西甲 spain1
    "皇家马德里": (86, "Real Madrid", "spain1"),
    "皇马": (86, "Real Madrid", "spain1"),
    "巴塞罗那": (81, "Barcelona", "spain1"),
    "巴萨": (81, "Barcelona", "spain1"),
    "马德里竞技": (78, "Atl. Madrid", "spain1"),
    "马竞": (78, "Atl. Madrid", "spain1"),
    "比利亚雷亚尔": (760, "Villarreal", "spain1"),
    "比利亚雷": (760, "Villarreal", "spain1"),
    # 德甲 germany1
    "拜仁": (5, "Bayern", "germany1"),
    "拜仁慕尼黑": (5, "Bayern", "germany1"),
    "多特蒙德": (4, "Dortmund", "germany1"),
    "多特": (4, "Dortmund", "germany1"),
    "勒沃库森": (3, "Leverkusen", "germany1"),
    "RB莱比锡": (721, "Leipzig", "germany1"),
    "莱红牛": (721, "Leipzig", "germany1"),
    # 意甲 italy1
    "国际米兰": (108, "Inter", "italy1"),
    "国米": (108, "Inter", "italy1"),
    "AC米兰": (98, "Milan", "italy1"),
    "米兰": (98, "Milan", "italy1"),
    "尤文图斯": (115, "Juventus", "italy1"),
    "尤文": (115, "Juventus", "italy1"),
    "那不勒斯": (113, "Napoli", "italy1"),
    "罗马": (100, "Roma", "italy1"),
    "亚特兰大": (102, "Atalanta", "italy1"),
    # 法甲 france1
    "巴黎圣日耳曼": (524, "PSG", "france1"),
    "巴黎": (524, "PSG", "france1"),
    "朗斯": (None, "Lens", "france1"),
    # 葡超 portugal1
    "里斯本": (None, "Sporting", "portugal1"),
    "里斯本竞技": (None, "Sporting", "portugal1"),
    "本菲卡": (None, "Benfica", "portugal1"),
    # 荷甲 holland1
    "埃因霍温": (None, "PSV", "holland1"),
    # 比甲 belgium1
    "布鲁日": (None, "Club Brugge", "belgium1"),
    # 土超 turkey1
    "加拉塔萨雷": (None, "Galatasaray", "turkey1"),
    # 挪超 norway1 (足球图临时补)
    "维京": (None, "Viking", "norway1"),
}


# ---------------------------------------------------------------------------
# HTTP 通用
# ---------------------------------------------------------------------------

def _safe_get(url: str, headers: dict = None, retry: int = 3) -> requests.Response | None:
    hdrs = headers or FD_HEADERS
    last_err = None
    for i in range(retry):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers=hdrs, timeout=15)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            logger.warning(f"请求失败 ({i+1}/{retry}) {url[:80]} ... : {e}")
    logger.error(f"全部重试失败: {url[:80]}")
    return None


# ---------------------------------------------------------------------------
# football-data.org 封装
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _fetch_fd_team_matches(team_id: int, football_data_token: str = "") -> list[dict]:
    """拉 football-data.org 某队全部赛程"""
    if not football_data_token:
        logger.warning("无 football-data token, 跳过 _fetch_fd_team_matches")
        return []
    url = f"{FD_BASE}/teams/{team_id}/matches?status=FINISHED&limit=30"
    resp = _safe_get(url, headers=_fd_headers(football_data_token))
    if not resp:
        return []
    try:
        return resp.json().get("matches", [])
    except Exception as e:
        logger.error(f"football-data 解析失败: {e}")
        return []


def _fd_match_to_row(m: dict, self_team_id: int) -> dict:
    """football-data 比赛 dict → 标准行"""
    home = m.get("homeTeam", {}) or {}
    away = m.get("awayTeam", {}) or {}
    score = m.get("score", {}) or {}
    ft = score.get("fullTime") or {}
    ht = score.get("halfTime") or {}

    h_ft = ft.get("home") or 0
    a_ft = ft.get("away") or 0
    h_ht = ht.get("home") or 0
    a_ht = ht.get("away") or 0

    h_name = home.get("shortName") or home.get("name", "")
    a_name = away.get("shortName") or away.get("name", "")

    is_home = (home.get("id") == self_team_id)
    opp_name = a_name if is_home else h_name
    self_score = h_ft if is_home else a_ft
    opp_score = a_ft if is_home else h_ft

    if self_score > opp_score:
        result = "胜"
    elif self_score == opp_score:
        result = "平"
    else:
        result = "负"

    # 半全场
    if h_ht or a_ht:
        self_ht = h_ht if is_home else a_ht
        opp_ht = a_ht if is_home else h_ht
        if self_ht > opp_ht:
            hr = "胜"
        elif self_ht == opp_ht:
            hr = "平"
        else:
            hr = "负"
        hf = hr + result
    else:
        hf = ""

    league = (m.get("competition") or {}).get("name", "")

    return {
        "日期": (m.get("utcDate") or "")[:10],
        "联赛": league,
        "主队": h_name,
        "客队": a_name,
        "对手": opp_name,
        "比分": f"{h_ft}-{a_ft}",
        "半场": f"{h_ht}-{a_ht}" if (h_ht or a_ht) else "",
        "结果": result,
        "胜平负": result,
        "总进球": h_ft + a_ft,
        "半全场": hf,
    }


# ---------------------------------------------------------------------------
# football-charts.com 封装 (降级)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _fetch_fc_team_matches(team_en: str, league: str, season: str) -> list[dict]:
    url = (
        f"{FC_BASE}/leagues/{league}/results/"
        f"?season={urllib.parse.quote(season)}"
        f"&team={urllib.parse.quote(team_en)}"
    )
    resp = _safe_get(url, headers=FC_HEADERS)
    if not resp:
        return []
    try:
        return resp.json().get("matches", [])
    except Exception as e:
        logger.error(f"football-charts 解析失败: {e}")
        return []


def _fc_match_to_row(m: dict, self_team_en: str) -> dict:
    h = m.get("homeTeam", "")
    a = m.get("awayTeam", "")
    score = m.get("score", "") or ""   # e.g. "2:0"
    ht = m.get("ht_result", "") or ""  # e.g. "1:0"

    h_ft = a_ft = h_ht = a_ht = 0
    try:
        h_ft, a_ft = map(int, score.split(":"))
    except Exception:
        pass
    try:
        h_ht, a_ht = map(int, ht.split(":"))
    except Exception:
        pass

    is_home = (h == self_team_en)
    opp = a if is_home else h
    s = h_ft if is_home else a_ft
    o = a_ft if is_home else h_ft

    if s > o:
        result = "胜"
    elif s == o:
        result = "平"
    else:
        result = "负"

    if h_ht or a_ht:
        self_ht = h_ht if is_home else a_ht
        opp_ht = a_ht if is_home else h_ht
        if self_ht > opp_ht:
            hr = "胜"
        elif self_ht == opp_ht:
            hr = "平"
        else:
            hr = "负"
        hf = hr + result
    else:
        hf = ""

    return {
        "日期": m.get("date", ""),
        "主队": h,
        "客队": a,
        "对手": opp,
        "比分": score.replace(":", "-"),
        "半场": ht.replace(":", "-") if ht else "",
        "结果": result,
        "胜平负": result,
        "总进球": h_ft + a_ft,
        "半全场": hf,
    }


def _recent_seasons() -> list[str]:
    now = datetime.now()
    if now.month >= 9:
        cur = f"{now.year}-{now.year+1}"
    else:
        cur = f"{now.year-1}-{now.year}"
    prev = f"{int(cur.split('-')[0])-1}-{int(cur.split('-')[1])-1}"
    return [cur, prev]


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------

def _resolve_team(team_cn: str) -> tuple[int | None, str | None, str | None]:
    """中文队名 → (FD team_id, FC 英文名, FC 联赛 key)"""
    key = team_cn.strip()
    if key in TEAM_MAP:
        return TEAM_MAP[key]
    for k, v in TEAM_MAP.items():
        if k in key or key in k:
            return v
    return None, None, None


def fetch_recent_form(team_cn: str, n: int = 10, football_data_token: str = "") -> pd.DataFrame:
    """球队近 N 场战绩 —— football-data 优先, 降级 football-charts"""
    fd_id, fc_team, fc_league = _resolve_team(team_cn)

    # ---- 尝试 football-data ----
    if fd_id and football_data_token:
        fd_matches = _fetch_fd_team_matches(fd_id, football_data_token)
        if fd_matches:
            rows = [_fd_match_to_row(m, fd_id) for m in fd_matches[:n]]
            df = pd.DataFrame(rows)
            logger.info(f"[football-data] {team_cn} 近 {len(df)} 场 (token)")
            return df
        logger.warning(f"football-data 无 {team_cn} 数据, 降级 football-charts")

    # ---- 降级 football-charts ----
    if fc_team and fc_league:
        seasons = _recent_seasons()
        all_matches = []
        for s in seasons:
            all_matches.extend(_fetch_fc_team_matches(fc_team, fc_league, s))

        seen = set()
        uniq = []
        for m in all_matches:
            mid = m.get("id") or f"{m.get('date')}-{m.get('homeTeam')}-{m.get('awayTeam')}"
            if mid not in seen:
                seen.add(mid)
                uniq.append(m)

        uniq.sort(key=lambda x: x.get("date", ""), reverse=True)
        rows = [_fc_match_to_row(m, fc_team) for m in uniq[:n]]
        df = pd.DataFrame(rows)
        logger.info(f"[football-charts] {team_cn} 近 {len(df)} 场")
        return df

    logger.error(f"无任何数据源映射: {team_cn}")
    return pd.DataFrame()


def fetch_h2h(home_cn: str, away_cn: str, n: int = 10, football_data_token: str = "") -> pd.DataFrame:
    """两队历史交锋 (H2H)"""
    h_fd, h_fc_team, h_fc_lg = _resolve_team(home_cn)
    a_fd, a_fc_team, a_fc_lg = _resolve_team(away_cn)

    # ---- football-data 优先 ----
    if h_fd and a_fd and football_data_token:
        home_ms = _fetch_fd_team_matches(h_fd, football_data_token)
        h2h = []
        h2h_ids = set()
        for m in home_ms:
            h = (m.get("homeTeam") or {}).get("id")
            a = (m.get("awayTeam") or {}).get("id")
            mid = m.get("id")
            if mid in h2h_ids:
                continue
            if (h == h_fd and a == a_fd) or (h == a_fd and a == h_fd):
                h2h_ids.add(mid)
                h2h.append(m)
        h2h.sort(key=lambda x: x.get("utcDate", ""), reverse=True)
        if h2h:
            rows = [_fd_match_to_row(m, h_fd) for m in h2h[:n]]
            df = pd.DataFrame(rows)
            logger.info(f"[football-data] H2H {home_cn} vs {away_cn}: {len(df)} 场")
            return df
        logger.warning(f"football-data 无 H2H {home_cn} vs {away_cn}, 降级")

    # ---- football-charts 降级 ----
    if h_fc_team and a_fc_team:
        seasons = _recent_seasons()
        all_home = []
        all_away = []
        for s in seasons:
            all_home.extend(_fetch_fc_team_matches(h_fc_team, h_fc_lg, s))
            if h_fc_lg == a_fc_lg:
                all_away.extend(_fetch_fc_team_matches(a_fc_team, h_fc_lg, s))
            else:
                all_away.extend(_fetch_fc_team_matches(a_fc_team, a_fc_lg, s))

        # 用双方 results 的并集匹配
        all_matches = all_home + all_away
        h2h = []
        seen_ids = set()
        for m in all_matches:
            mid = m.get("id") or f"{m.get('date')}-{m.get('homeTeam')}-{m.get('awayTeam')}"
            if mid in seen_ids:
                continue
            h, a = m.get("homeTeam", ""), m.get("awayTeam", "")
            if (h == h_fc_team and a == a_fc_team) or (h == a_fc_team and a == h_fc_team):
                seen_ids.add(mid)
                h2h.append(m)

        h2h.sort(key=lambda x: x.get("date", ""), reverse=True)
        if h2h:
            rows = [_fc_match_to_row(m, h_fc_team) for m in h2h[:n]]
            df = pd.DataFrame(rows)
            logger.info(f"[football-charts] H2H {home_cn} vs {away_cn}: {len(df)} 场")
            return df

    logger.error(f"H2H 无数据源: {home_cn} vs {away_cn}")
    return pd.DataFrame()


def get_history(home: str, away: str, football_data_token: str = "") -> dict:
    """
    统一入口 —— 获取两队历史交锋 + 近期战绩

    Args:
        home: 主队中文名
        away: 客队中文名
        football_data_token: football-data.org API token（空则跳过 football-data，降级 football-charts）
    """
    logger.info(f"获取历史战绩: {home} vs {away}")
    df_h2h = fetch_h2h(home, away, 10, football_data_token)
    df_home = fetch_recent_form(home, 10, football_data_token)
    df_away = fetch_recent_form(away, 10, football_data_token)
    logger.info(
        f"结果: H2H={len(df_h2h)}  主近={len(df_home)}  客近={len(df_away)}"
    )
    return {
        "h2h": df_h2h,
        "home_recent": df_home,
        "away_recent": df_away,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    # 今日体彩真实比赛: 马竞 vs 曼联
    home, away = "马竞", "曼联"
    print(f"\n{'='*60}")
    print(f"  测试: {home} vs {away}")
    print(f"{'='*60}")

    result = get_history(home, away)

    for key, df in result.items():
        print(f"\n--- {key} ({len(df)} 条) ---")
        if df.empty:
            print("  (空)")
        else:
            cols = [c for c in ["日期", "联赛", "主队", "客队", "对手",
                                "比分", "半场", "结果", "胜平负", "总进球", "半全场"]
                    if c in df.columns]
            print(df[cols].to_string(index=False))
