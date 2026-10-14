"""
情报聚合模块（V2 - 真实字段结构版）
主源：懂球帝 3 个 API（搜索 / 比赛分析 / 赔率）
降级：football-data
"""
import time
import random
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# ============ 请求配置 ============
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

HEADERS = {
    "User-Agent": ANDROID_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.dongqiudi.com/",
}

# 联赛 ID 映射（懂球帝）
LEAGUE_MAP = {
    "英超": 8, "西甲": 3, "意甲": 1, "德甲": 2, "法甲": 4,
    "中超": 7, "欧冠": 5, "亚冠": 15, "欧联": 6,
}

# football-data 联赛编码映射
FD_LEAGUE_MAP = {
    "英超": "PL", "西甲": "PD", "意甲": "SA", "德甲": "BL1",
    "法甲": "FL1", "欧冠": "CL", "欧联": "EL",
}

# 队名别名表：中文队名 → 搜索别名 list（懂球帝 search 用）
# 当原队名 search 不到 match 时，按序尝试这些别名
TEAM_ALIASES: Dict[str, List[str]] = {
    "里斯本": ["里斯本竞技", "Sporting CP", "葡体"],
    "里斯本竞技": ["里斯本", "Sporting CP", "葡体"],
    "米堡": ["米德尔斯堡", "Middlesbrough"],
    "米德尔斯堡": ["米堡", "Middlesbrough"],
    "斯托克城": ["Stoke City"],
    "里尔": ["Lille"],
    "布鲁日": ["布鲁日俱乐部", "Club Brugge"],
    "加拉塔萨": ["加拉塔萨雷", "Galatasaray"],
    "加拉塔萨雷": ["加拉塔萨", "Galatasaray"],
    "布里兰": ["武里南联", "Buriram Utd"],
    "武里南联": ["布里兰", "Buriram Utd"],
    "纽卡斯尔喷气机": ["纽卡斯尔", "Newcastle Jets"],
    "纽卡斯尔": ["纽卡斯尔联", "纽卡斯尔喷气机"],
    "上海海港": ["海港", "上海上港", "Shanghai Port"],
    "大田市民": ["大田韩亚市民", "Daejeon Citizen"],
    "大阪钢巴": ["Gamba Osaka"],
    "北京国安": ["国安", "Beijing Guoan"],
    "比利亚雷": ["比利亚雷亚尔", "Villarreal"],
    "比利亚雷亚尔": ["比利亚雷", "Villarreal"],
    "莱红牛": ["RB莱比锡", "Leipzig"],
    "国际米兰": ["国米", "Inter Milan"],
    "马德里竞技": ["马竞", "Atl. Madrid", "Atletico Madrid"],
    "马德里竞技": ["马竞", "Atl. Madrid", "Atletico Madrid"],
    "曼城": ["曼彻斯特城", "Manchester City"],
    "曼联": ["曼彻斯特联", "Manchester Utd"],
    "巴萨": ["巴塞罗那", "Barcelona"],
    "皇马": ["皇家马德里", "Real Madrid"],
    "拜仁": ["拜仁慕尼黑", "Bayern Munich"],
    "阿森纳": ["Arsenal"],
    "那不勒斯": ["Napoli"],
    "埃因霍温": ["PSV", "PSV Eindhoven"],
    "维京": ["Viking FK"],
}


# ============ 通用请求（优化：缩短超时、减少重试、加进度日志） ============
def _safe_get(url: str, params: dict = None, retry: int = 2,
              timeout: int = 8) -> Optional[dict]:
    """
    带重试的 JSON 请求（优化版）
    - retry: 2 次重试
    - timeout: 8 秒超时（防止长时间卡住）
    - 打印进度日志
    """
    for i in range(retry):
        try:
            delay = random.uniform(0.3, 0.8)
            logger.info(f"请求 ({i+1}/{retry}): {url[:80]}... 等待 {delay:.1f}s")
            time.sleep(delay)
            resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            if resp.status_code == 403:
                logger.warning(f"403 被拒: {url[:80]}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.warning(f"超时 ({i+1}/{retry}): {url[:80]}")
        except requests.ConnectionError as e:
            logger.warning(f"连接错误 ({i+1}/{retry}): {url[:80]} - {e}")
        except Exception as e:
            logger.warning(f"请求失败 ({i+1}/{retry}): {url[:80]} - {e}")
    logger.error(f"请求彻底失败: {url[:80]}")
    return None


# ============ 工具 ============
def _pick(d: dict, *keys, default=None):
    """从 dict 里按多个候选键取第一个非空值"""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return default


def _safe_int(v, default=0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ============ 1. 搜索 API：拿 match_id / team_id ============
def dongqiudi_search(keyword: str, page: int = 1) -> List[Dict]:
    """
    搜索懂球帝内容（修复版）

    真实行为：
    - 双队组合关键词 → 返回 0 条 match
    - 单队关键词 → 返回该队近期比赛 matches.data[]

    返回：[{match_id, team_A_name, team_B_name, competition_name, start_play, status, ...}, ...]
    """
    url = "http://api.dongqiudi.com/search"
    params = {"keywords": keyword, "type": "all", "page": page}
    data = _safe_get(url, params)
    if not data:
        return []

    results = []

    # ✅ 主搜 matches.data（比赛列表）
    matches = data.get("matches", {}) or {}
    matches_data = matches.get("data", []) if isinstance(matches, dict) else []
    for item in matches_data:
        if not isinstance(item, dict):
            continue
        results.append({
            "match_id": str(item.get("match_id", "") or ""),
            "team_A_name": item.get("team_A_name", ""),
            "team_B_name": item.get("team_B_name", ""),
            "competition_name": item.get("competition_name", ""),
            "start_play": item.get("start_play", ""),
            "status": item.get("status", ""),
            "fs_A": item.get("fs_A", ""),
            "fs_B": item.get("fs_B", ""),
        })

    # ✅ 同时收集 teams（球队 ID）
    teams = data.get("teams", []) or []
    team_list = []
    for item in teams:
        if not isinstance(item, dict):
            continue
        team_name_raw = item.get("team_name", "") or ""
        # 去掉 <font color=...> 高亮标签
        team_name_clean = team_name_raw.replace(
            '<font color=#16ac3a>', '').replace('</font>', '')
        team_list.append({
            "team_id": str(item.get("team_id", "") or ""),
            "team_name": team_name_clean,
            "team_en_name": item.get("team_en_name", ""),
            "country": item.get("country", ""),
        })

    # 附加到 results 里（方便调用方一起拿）
    if team_list:
        results = results + [{"_teams": team_list}]

    logger.info(f"搜索 '{keyword}' → matches={len(matches_data)}, teams={len(teams)}")
    return results


def _get_aliases(name: str) -> List[str]:
    """取队名的所有搜索别名（含原名）"""
    aliases = [name]
    if name in TEAM_ALIASES:
        aliases.extend(TEAM_ALIASES[name])
    # 模糊匹配：如果原名是某个 key 的子串
    for key, als in TEAM_ALIASES.items():
        if name in key or key in name:
            if key not in aliases:
                aliases.append(key)
            for a in als:
                if a not in aliases:
                    aliases.append(a)
    # 去重保持顺序
    seen = set()
    return [a for a in aliases if not (a in seen or seen.add(a))]


def find_match_id(home: str, away: str) -> Optional[str]:
    """
    通过搜索找到比赛 ID（别名链增强版）

    策略：
    1. 搜主队（别名链）→ 在 matches.data[] 里找客队名匹配
    2. 搜客队（别名链）→ 在 matches.data[] 里找主队名匹配
    3. 对手匹配也走别名链
    """
    home_aliases = _get_aliases(home)
    away_aliases = _get_aliases(away)

    # 主队搜索链
    for h_kw in home_aliases:
        match_id = _search_one_team_with_aliases(h_kw, away_aliases)
        if match_id:
            return match_id

    # 客队搜索链
    for a_kw in away_aliases:
        match_id = _search_one_team_with_aliases(a_kw, home_aliases)
        if match_id:
            logger.info(f"  主队方向未命中，最终通过客队别名 {a_kw!r} 找到")
            return match_id

    logger.warning(f"未找到 {home} vs {away} 的 match_id（已尝试 {len(home_aliases)+len(away_aliases)} 个关键词）")
    return None


def _search_one_team_with_aliases(team_keyword: str, opponent_aliases: List[str]) -> Optional[str]:
    """
    搜索单队，对手匹配支持别名链

    Args:
        team_keyword: 搜索关键词
        opponent_aliases: 对手队名的所有可能别名 list
    """
    logger.info(f"搜索 match_id: {team_keyword} → 找对手 {'/'.join(opponent_aliases[:3])}")
    results = dongqiudi_search(team_keyword)
    if not results:
        return None

    for item in results:
        if not isinstance(item, dict):
            continue
        if "_teams" in item and "match_id" not in item:
            continue

        match_id = item.get("match_id", "")
        team_a = item.get("team_A_name", "")
        team_b = item.get("team_B_name", "")

        if not match_id:
            continue

        # 对手队名匹配（别名链）
        for opp in opponent_aliases:
            if opp and (opp in team_a or opp in team_b or team_a in opp or team_b in opp):
                logger.info(f"  ✅ 命中: {team_a} vs {team_b} → match_id={match_id}")
                return str(match_id)

    return None


# ============ 2. 比赛分析 API ============
def dongqiudi_analysis(match_id: str) -> Dict[str, Any]:
    """
    懂球帝比赛分析（真实结构）
    真实字段：info.battle_history / info.recent_record / info.league_table / info.sideline
    """
    url = f"https://api.dongqiudi.com/mobile/match/analysis/{match_id}"
    data = _safe_get(url)
    if not data:
        logger.warning(f"比赛分析无响应: {match_id}")
        return {}

    # ✅ 真实结构：全部在 info 下
    info = data.get("info", {}) or {}

    result = {
        "battle_history": info.get("battle_history", {}) or {},
        "recent_record": info.get("recent_record", {}) or {},
        "league_table": info.get("league_table", {}) or {},
        "sideline": info.get("sideline", {}) or {},
        "info": info,
    }
    logger.info(f"比赛分析 {match_id} 获取成功")
    return result


def parse_h2h(battle_history: dict, home: str = "") -> Dict[str, Any]:
    """
    解析 H2H
    真实结构：
    {
        "team_A": {"win": N, "draw": N, "lose": N, "name": "..."},
        "team_B": {"win": N, "draw": N, "lose": N, "name": "..."},
        "percent": {"win": "72%", "draw": "14%", "lose": "14%"},
        "list": [{color: "win"|"draw"|"lose", ...}, ...]
    }
    """
    if not battle_history:
        return {"total": 0, "home_win": 0, "draw": 0, "away_win": 0, "matches": []}

    team_a = battle_history.get("team_A", {}) or {}
    team_b = battle_history.get("team_B", {}) or {}
    percent = battle_history.get("percent", {}) or {}

    # 找到主队视角（默认 team_A 是主队）
    a_name = _pick(team_a, "name", "team_name", default="")
    b_name = _pick(team_b, "name", "team_name", default="")

    if home and b_name and home in b_name:
        me = team_b
    else:
        me = team_a

    my_win = _safe_int(_pick(me, "win", "win_count"))
    my_draw = _safe_int(_pick(me, "draw", "draw_count"))
    my_lose = _safe_int(_pick(me, "lose", "lose_count", "loss"))
    total = my_win + my_draw + my_lose

    matches = []
    for m in battle_history.get("list", []):
        matches.append({
            "color": m.get("color", ""),
            "date": m.get("date", ""),
            "home": m.get("home_team", {}).get("name", "") if isinstance(m.get("home_team"), dict) else m.get("home_team", ""),
            "away": m.get("away_team", {}).get("name", "") if isinstance(m.get("away_team"), dict) else m.get("away_team", ""),
            "score": m.get("score", ""),
        })

    return {
        "total": total,
        "home_win": my_win,
        "draw": my_draw,
        "away_win": my_lose,
        "home_win_pct": percent.get("win", ""),
        "draw_pct": percent.get("draw", ""),
        "away_win_pct": percent.get("lose", ""),
        "percent": percent,
        "matches": matches,
    }


def _color_to_result(color) -> str:
    """懂球帝 color 字段转中文结果"""
    if not color:
        return ""
    c = str(color).lower().strip()
    if c in ("win", "w", "胜", "3"):
        return "胜"
    if c in ("draw", "d", "平", "0"):
        return "平"
    if c in ("lose", "loss", "l", "负", "2"):
        return "负"
    return ""


def parse_recent_record(recent_record: dict) -> Dict[str, List]:
    """
    解析主客近 10 场
    真实结构：
    {
        "team_A": [{date, team_A_name, team_B_name, main_team, score, color}, ...],
        "team_B": [...]
    }
    """
    result = {"home": [], "away": []}

    for side_key, side_name in [("team_A", "home"), ("team_B", "away")]:
        matches = recent_record.get(side_key, [])
        if not isinstance(matches, list):
            continue
        for m in matches:
            if not isinstance(m, dict):
                continue
            color = m.get("color", "")
            result[side_name].append({
                "date": m.get("date", ""),
                "competition": m.get("competition", ""),
                "team_A_name": m.get("team_A_name", ""),
                "team_B_name": m.get("team_B_name", ""),
                "main_team": m.get("main_team", ""),
                "score": m.get("score", ""),
                "half_score": m.get("half_score", ""),
                "color": color,
                "result": _color_to_result(color),
            })
    return result


def parse_league_table(league_table: dict) -> Dict[str, Any]:
    """
    解析积分榜
    真实结构：
    {
        "team_A": {"total": {...}, "home": {...}, "away": {...}},
        "team_B": {...}
    }
    """
    def _extract(team_data):
        if not isinstance(team_data, dict):
            return {}
        total = team_data.get("total", {}) or {}
        return {
            "rank": _safe_int(_pick(total, "rank", "position", "ranking")),
            "points": _safe_int(_pick(total, "points", "score", "point")),
            "played": _safe_int(_pick(total, "matches_total", "played", "games")),
            "win": _safe_int(_pick(total, "matches_won", "win", "won")),
            "draw": _safe_int(_pick(total, "matches_draw", "draw", "drawn")),
            "loss": _safe_int(_pick(total, "matches_lost", "lose", "lost")),
            "goals_for": _safe_int(_pick(total, "goals_pro", "goals_for", "goal_for")),
            "goals_against": _safe_int(_pick(total, "goals_against", "goals_con", "goal_against")),
            "goal_diff": _safe_int(_pick(total, "goal_diff", "goals_diff")),
        }

    return {
        "home": _extract(league_table.get("team_A", {})),
        "away": _extract(league_table.get("team_B", {})),
    }


def parse_sideline(sideline: dict) -> Dict[str, List]:
    """
    解析伤停名单
    真实结构：
    {
        "team_A": [...],   # 直接是 list
        "team_B": [...]
    }
    """
    result = {"home": [], "away": []}

    for side_key, side_name in [("team_A", "home"), ("team_B", "away")]:
        players = sideline.get(side_key, [])
        if not isinstance(players, list):
            continue
        for p in players:
            if not isinstance(p, dict):
                continue
            result[side_name].append({
                "name": p.get("name", "") or p.get("player_name", ""),
                "number": p.get("number", "") or p.get("shirt_number", ""),
                "position": p.get("position", ""),
                "reason": p.get("reason", "") or p.get("injury", "") or p.get("injury_reason", ""),
                "status": p.get("status", "") or p.get("type", ""),
            })
    return result


# ============ 3. 赔率 API ============
def dongqiudi_odds(match_id: str) -> Dict[str, Any]:
    """
    懂球帝赔率（带超时降级）
    真实结构：euro[] 是机构 list（19家），avg/max/min 是顶层 summary
    """
    if not match_id:
        logger.warning("match_id 为空，跳过赔率请求")
        return {}

    url = f"https://beta-sport-data.dongqiudi.com/soccer/biz/dqd/v1/match/odds/index/{match_id}"
    params = {"app": "dqd", "lang": "zh-cn", "platform": "android"}

    try:
        data = _safe_get(url, params, retry=2, timeout=8)
    except Exception as e:
        logger.error(f"赔率请求异常: {e}")
        return {}

    if not data:
        logger.warning(f"赔率接口无响应，跳过: {match_id}")
        return {}

    result = {
        "has_odds": data.get("has_odds", False),
        "euro": [],
        "asia": [],
        "size": [],
        "avg": {},
        "max": {},
        "min": {},
    }

    # euro[] 是机构 list
    euro_list = data.get("euro", [])
    if isinstance(euro_list, list):
        for item in euro_list:
            if not isinstance(item, dict):
                continue
            result["euro"].append({
                "company": item.get("company", ""),
                "begin": item.get("begin", {}),
                "now": item.get("now", {}),
            })

    # asia[] 是机构 list
    asia_list = data.get("asia", [])
    if isinstance(asia_list, list):
        for item in asia_list[:10]:
            if not isinstance(item, dict):
                continue
            result["asia"].append({
                "company": item.get("company", ""),
                "begin": item.get("begin", ""),
                "now": item.get("now", ""),
                "begin_water": item.get("begin_water", ""),
                "now_water": item.get("now_water", ""),
            })

    # size[] 是机构 list
    size_list = data.get("size", [])
    if isinstance(size_list, list):
        for item in size_list[:10]:
            if not isinstance(item, dict):
                continue
            result["size"].append({
                "company": item.get("company", ""),
                "begin": item.get("begin", ""),
                "now": item.get("now", ""),
            })

    # 顶层 summary
    for key in ["avg", "max", "min"]:
        section = data.get(key, {})
        if isinstance(section, dict):
            result[key] = {
                "name": section.get("name", ""),
                "begin": section.get("begin", {}),
                "now": section.get("now", {}),
            }

    logger.info(
        f"赔率 {match_id} 获取成功, has_odds={result['has_odds']}, "
        f"欧赔机构={len(result['euro'])}, 亚盘机构={len(result['asia'])}"
    )
    return result


def calc_handicap_trend(odds: Dict[str, Any]) -> Dict[str, str]:
    """分析赔率变化趋势（机构注水）"""
    trend = {"direction": "稳定", "signal": ""}
    avg = odds.get("avg", {}) or {}
    begin = avg.get("begin", {}) or {}
    now = avg.get("now", {}) or {}

    try:
        begin_h = float(_pick(begin, "homeWin", "home", "h", default=0))
        now_h = float(_pick(now, "homeWin", "home", "h", default=0))
        if begin_h > 0 and now_h > 0:
            if now_h < begin_h * 0.95:
                trend["direction"] = "主胜降赔"
                trend["signal"] = "机构看好主队"
            elif now_h > begin_h * 1.05:
                trend["direction"] = "主胜升赔"
                trend["signal"] = "机构看淡主队"
    except (ValueError, TypeError):
        pass

    return trend


# 杯赛（无传统积分榜，football-data free tier 也拿不到 standings）
CUP_LEAGUES = {"欧冠", "欧联", "亚冠", "欧协", "世俱杯", "世界杯", "欧洲杯", "美洲杯"}


# ============ 4. football-data 降级 ============
def football_data_rankings(team: str, league: str,
                           token: str = "") -> Dict[str, Any]:
    """从 football-data 拿排名（降级方案）。杯赛直接跳过"""
    # 杯赛直接跳过 —— 无传统积分榜，懂球帝 league_table 本身就是小组排名
    if league in CUP_LEAGUES:
        return {"team": team, "rank": 0, "source": "cup_league", "league": league}

    if not token:
        return {"team": team, "rank": 0, "source": "unavailable"}

    code = FD_LEAGUE_MAP.get(league)
    if not code:
        return {"team": team, "rank": 0, "source": "unsupported_league"}

    url = f"https://api.football-data.org/v4/competitions/{code}/standings"
    headers = {"X-Auth-Token": token}

    try:
        time.sleep(random.uniform(0.3, 0.8))
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get("standings", [{}])[0].get("table", []):
            if team in entry.get("team", {}).get("name", ""):
                return {
                    "team": team,
                    "rank": entry.get("position", 0),
                    "points": entry.get("points", 0),
                    "played": entry.get("playedGames", 0),
                    "goal_diff": entry.get("goalDifference", 0),
                    "source": "football-data",
                }
    except Exception as e:
        logger.warning(f"football-data 降级失败: {e}")
    return {"team": team, "rank": 0, "source": "failed"}


# ============ 5. 统一入口 ============
def get_intel(home: str, away: str, league: str,
              match_id: str = None,
              football_data_token: str = "") -> Dict[str, Any]:
    """
    统一入口：聚合所有情报
    优先级：懂球帝比赛分析 > football-data 降级
    """
    # 联赛名归一化（体彩/手动输入的联赛名 vs 懂球帝/FD 的标准名）
    LEAGUE_NORMALIZE = {
        "亚冠精英": "亚冠",
        "亚冠联赛": "亚冠",
        "亚洲冠军联赛": "亚冠",
        "英冠": "英冠",
        "冠军联赛": "欧冠",
        "UEFA欧冠": "欧冠",
        "英超联赛": "英超",
        "西甲联赛": "西甲",
        "意甲联赛": "意甲",
        "德甲联赛": "德甲",
        "法甲联赛": "法甲",
    }
    league = LEAGUE_NORMALIZE.get(league, league)
    logger.info(f"===== 情报获取: {home} vs {away} ({league}) =====")

    intel = {
        "timestamp": datetime.now().isoformat(),
        "home": home,
        "away": away,
        "league": league,
        "match_id": match_id or "",
        "source": "none",
        "h2h": {},
        "recent": {"home": [], "away": []},
        "ranking": {
            "home_rank": 0, "away_rank": 0,
            "home_points": 0, "away_points": 0,
        },
        "sideline": {"home": [], "away": []},
        "odds": {},
        "handicap_trend": {},
    }

    # 1. 加固：match_id 必须是纯数字，否则重新搜索
    if not match_id or not str(match_id).isdigit():
        if match_id:
            logger.warning(f"match_id '{match_id}' 非数字，重新搜索")
        match_id = find_match_id(home, away)
        intel["match_id"] = match_id or ""

    # 2. 懂球帝比赛分析
    if match_id:
        analysis = dongqiudi_analysis(match_id)
        if analysis:
            intel["source"] = "dongqiudi"

            h2h = parse_h2h(analysis.get("battle_history", {}), home)
            intel["h2h"] = h2h

            recent = parse_recent_record(analysis.get("recent_record", {}))
            intel["recent"] = recent

            intel["sideline"] = parse_sideline(analysis.get("sideline", {}))

            lt = parse_league_table(analysis.get("league_table", {}))
            intel["league_table"] = lt
            intel["ranking"] = {
                "home_rank": lt.get("home", {}).get("rank", 0),
                "away_rank": lt.get("away", {}).get("rank", 0),
                "home_points": lt.get("home", {}).get("points", 0),
                "away_points": lt.get("away", {}).get("points", 0),
            }

            logger.info(
                f"  H2H={h2h.get('total', 0)}场, "
                f"主近={len(recent['home'])}场, 客近={len(recent['away'])}场, "
                f"伤停={len(intel['sideline']['home'])}+{len(intel['sideline']['away'])}"
            )

        # 3. 赔率
        odds = dongqiudi_odds(match_id)
        if odds:
            intel["odds"] = odds
            intel["handicap_trend"] = calc_handicap_trend(odds)

    # 4. 降级：football-data 补排名
    if intel["ranking"]["home_rank"] == 0 and football_data_token:
        logger.info("  排名缺失，尝试 football-data 降级")
        intel["ranking"]["home"] = football_data_rankings(home, league, football_data_token)
        intel["ranking"]["away"] = football_data_rankings(away, league, football_data_token)

    logger.info(
        f"  情报完成: source={intel['source']}, "
        f"match_id={match_id}, "
        f"ranking={intel['ranking']}"
    )
    return intel


# ============ 测试 ============
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    import json

    # 测试 1：搜索
    print("=" * 60)
    print("测试 1：搜索 API")
    print("=" * 60)
    results = dongqiudi_search("曼联")
    print(f"搜索 '曼联' 返回 {len(results)} 条")
    for r in results[:3]:
        print(f"  - {r['title'][:40]} | id={r['id']}")

    # 测试 2：比赛分析
    print("\n" + "=" * 60)
    print("测试 2：比赛分析 API")
    print("=" * 60)
    test_match_id = "54470920"  # 亚特兰大 vs 威尼斯
    analysis = dongqiudi_analysis(test_match_id)
    if analysis:
        h2h = parse_h2h(analysis.get("battle_history", {}), "亚特兰大")
        print(f"H2H: total={h2h.get('total')}, 主胜={h2h.get('home_win')}, "
              f"平={h2h.get('draw')}, 客胜={h2h.get('away_win')}")
        recent = parse_recent_record(analysis.get("recent_record", {}))
        print(f"主队近绩: {len(recent['home'])} 场, 客队近绩: {len(recent['away'])} 场")

    # 测试 3：赔率
    print("\n" + "=" * 60)
    print("测试 3：赔率 API")
    print("=" * 60)
    odds = dongqiudi_odds(test_match_id)
    if odds:
        print(f"has_odds={odds.get('has_odds')}, "
              f"欧赔机构={len(odds.get('euro', []))}, "
              f"亚盘机构={len(odds.get('asia', []))}")

    # 测试 4：完整流程
    print("\n" + "=" * 60)
    print("测试 4：完整 get_intel")
    print("=" * 60)
    intel = get_intel("亚特兰大", "威尼斯", "意甲", match_id=test_match_id)
    print(f"source: {intel['source']}")
    print(f"ranking: {intel['ranking']}")
    print(f"h2h: {intel['h2h'].get('total', 0)} 场")
    print(f"recent: 主 {len(intel['recent']['home'])} / 客 {len(intel['recent']['away'])}")