"""
情报聚合模块
主源：懂球帝（比赛分析 + 赔率）
降级：football-data

所有字段名已通过 API 实测验证（snake_case，嵌套在 info 下）。
"""
import time
import random
import logging
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ============ 请求配置 ============
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S9080) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
HEADERS = {
    "User-Agent": ANDROID_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.dongqiudi.com/",
}


# ============ 通用请求 ============
def _safe_get(url: str, params: dict = None,
              retry: int = 3, timeout: int = 15) -> Optional[dict]:
    """带随机延时 + 重试的 JSON GET"""
    for i in range(retry):
        try:
            time.sleep(random.uniform(1.0, 3.0))
            resp = requests.get(url, headers=HEADERS,
                                params=params, timeout=timeout)
            if resp.status_code == 403:
                logger.warning(f"403 被拒: {url}")
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"请求失败 ({i+1}/{retry}): {url} - {e}")
    return None


def _contains(name: str, keyword: str) -> bool:
    """子串匹配，处理名称变体（马竞→马德里竞技，曼联→曼彻斯特联）"""
    if not name or not keyword:
        return False
    return keyword in name or name in keyword


# ============================================================
# 1. 搜索 API —— 搜球队名拿到 match_id
# ============================================================
def dongqiudi_search(keyword: str) -> dict:
    """
    懂球帝搜索（type=all）。
    返回原始 JSON（含 teams / matches / news / users 等）。
    """
    url = "http://api.dongqiudi.com/search"
    data = _safe_get(url, params={"keywords": keyword,
                                   "type": "all", "page": 1})
    return data or {}


def find_match_id(home: str, away: str) -> Optional[str]:
    """
    自动查找懂球帝 match_id。

    策略：
      1. 搜主队队名 → 取返回的 matches.data[]（该队近期赛程列表）
      2. 遍历找 team_A_name / team_B_name 同时匹配 home 和 away 的那场
      3. 子串匹配容忍名称变体（马竞 vs 马德里竞技）
    """
    data = dongqiudi_search(home)
    matches = data.get("matches", {}).get("data", [])
    if not matches:
        logger.warning(f"搜索 '{home}' 未返回赛程列表")
        return None

    # 先找"主队为主场"的
    for m in matches:
        tA = m.get("team_A_name", "")
        tB = m.get("team_B_name", "")
        if _contains(tA, home) and _contains(tB, away):
            mid = str(m.get("match_id", ""))
            logger.info(f"找到 match_id: {mid} "
                        f"({tA} vs {tB}, {m.get('competition_name','')}, "
                        f"{m.get('status','')})")
            return mid

    # 再找"主队为客场"的
    for m in matches:
        tA = m.get("team_A_name", "")
        tB = m.get("team_B_name", "")
        if _contains(tA, away) and _contains(tB, home):
            mid = str(m.get("match_id", ""))
            logger.info(f"找到 match_id (主客对调): {mid} "
                        f"({tA} vs {tB}, {m.get('competition_name','')})")
            return mid

    logger.warning(f"赛程列表中未找到 {home} vs {away}")
    return None


# ============================================================
# 2. 比赛分析 API —— info 下嵌套全部数据
# ============================================================
def dongqiudi_analysis(match_id: str) -> Dict[str, Any]:
    """
    懂球帝比赛分析 /mobile/match/analysis/{matchId}

    实测返回结构：
      顶层: [show_time_day, show_time_min, match, info, matchid]
      info 下:
        battle_history  → team_A/team_B/percent/list
        recent_record   → team_A/team_B (各 10 场)
        league_table    → team_A/team_B (各有 total/home/away)
        sideline        → team_A/team_B (伤停列表)
    """
    url = f"https://api.dongqiudi.com/mobile/match/analysis/{match_id}"
    data = _safe_get(url)
    if not data:
        return {}

    info = data.get("info", {})
    return {
        "battle_history": info.get("battle_history", {}),
        "recent_record": info.get("recent_record", {}),
        "league_table": info.get("league_table", {}),
        "sideline": info.get("sideline", {}),
        "team_A_href": info.get("team_A_href", ""),
        "team_B_href": info.get("team_B_href", ""),
        "match_top": data.get("match", {}),
        "has_odds": info.get("has_odds", False),
    }


# ---------- 4 个 parser：全部用实测 snake_case ----------

def parse_h2h(battle_history: dict) -> Dict[str, Any]:
    """
    解析 H2H 对赛往绩。

    实测结构:
      battle_history = {
        "name": "交锋记录",
        "team_A": {"win": 4, "draw": 1, "lose": 0},  # A 在交锋中赢/平/输的场数
        "team_B": {"win": 0, "draw": 1, "lose": 4},
        "percent": {"win": 72, "draw": 18, "lose": 10},
        "list": [{"date","year","competition","team_A_name","team_B_name",
                   "score","color","match_href"}, ...]
      }
    """
    if not battle_history:
        return {"total": 0, "home_win": 0, "draw": 0, "away_win": 0,
                "home_win_pct": 0, "draw_pct": 0, "away_win_pct": 0,
                "matches": []}

    tA = battle_history.get("team_A", {})
    tB = battle_history.get("team_B", {})
    pct = battle_history.get("percent", {})

    home_win = tA.get("win", 0)
    draw = tA.get("draw", 0)
    away_win = tB.get("win", 0)
    total = home_win + draw + away_win

    matches = []
    for m in battle_history.get("list", []):
        matches.append({
            "date": f"{m.get('year','')}-{m.get('date','')}",
            "competition": m.get("competition", ""),
            "home": m.get("team_A_name", ""),
            "away": m.get("team_B_name", ""),
            "score": m.get("score", ""),
            "result": m.get("color", ""),  # win / draw / lose
        })

    return {
        "total": total,
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "home_win_pct": pct.get("win", 0),
        "draw_pct": pct.get("draw", 0),
        "away_win_pct": pct.get("lose", 0),
        "matches": matches,
    }


def parse_recent_record(recent_record: dict) -> Dict[str, List]:
    """
    解析主客近 N 场战绩。

    实测结构:
      recent_record = {
        "team_A": [{"date","year","competition",
                    "team_A_name","team_B_name","main_team",
                    "score","color"}, ...],
        "team_B": [...]
      }

    color = win / draw / lose，main_team 指明谁是那场的主队。
    """
    result = {"home": [], "away": []}
    if not recent_record:
        return result

    # 注意：team_A 是"比赛中的 team_A"，不一定是我们关心的主队。
    # 但 battle_history 里 team_A = team_B 的对手队伍，
    # recent_record 里 team_A / team_B 分别对应 battle_history 的 team_A / team_B。
    # 为了与其他 parser 统一，我们同时保留 raw 结构和解析结果。
    raw_A = recent_record.get("team_A", [])
    raw_B = recent_record.get("team_B", [])

    def _parse_one(raw: list) -> list:
        out = []
        for m in raw:
            main = m.get("main_team", "")  # "team_A" or "team_B"
            if main == "team_A":
                my_team = m.get("team_A_name", "")
                opp = m.get("team_B_name", "")
                is_home = True
            else:
                my_team = m.get("team_B_name", "")
                opp = m.get("team_A_name", "")
                is_home = False

            out.append({
                "date": f"{m.get('year','')}-{m.get('date','')}",
                "competition": m.get("competition", ""),
                "my_team": my_team,
                "opponent": opp,
                "score": m.get("score", ""),
                "result": m.get("color", ""),  # win/draw/lose
                "is_home": is_home,
            })
        return out

    result["home"] = _parse_one(raw_A)
    result["away"] = _parse_one(raw_B)
    return result


def parse_league_table(league_table: dict) -> Dict[str, Any]:
    """
    解析积分榜。

    实测结构:
      league_table = {
        "team_A": {
          "total": {"rank","points","matches_won","matches_draw","matches_lost",
                    "matches_total","goals_pro","goals_against","win_rate"},
          "home":  {...},
          "away":  {...}
        },
        "team_B": {...}
      }
    """
    if not league_table:
        return {"home": {}, "away": {}}

    def _extract(side: dict) -> dict:
        if not side:
            return {}
        t = side.get("total", {})
        return {
            "rank": int(t.get("rank", 0) or 0),
            "points": int(t.get("points", 0) or 0),
            "played": int(t.get("matches_total", 0) or 0),
            "win": int(t.get("matches_won", 0) or 0),
            "draw": int(t.get("matches_draw", 0) or 0),
            "loss": int(t.get("matches_lost", 0) or 0),
            "goals_for": int(t.get("goals_pro", 0) or 0),
            "goals_against": int(t.get("goals_against", 0) or 0),
            "goal_diff": int(t.get("goals_pro", 0) or 0)
                         - int(t.get("goals_against", 0) or 0),
            "win_rate": t.get("win_rate", ""),
            "home_table": side.get("home", {}),
            "away_table": side.get("away", {}),
        }

    return {
        "home": _extract(league_table.get("team_A", {})),
        "away": _extract(league_table.get("team_B", {})),
    }


def parse_sideline(sideline: dict) -> Dict[str, List]:
    """
    解析伤停名单。

    实测结构:
      sideline = {
        "team_A": [{"name","number","position","reason","type"}],
        "team_B": [...]
      }
    """
    result = {"home": [], "away": []}
    if not sideline:
        return result

    for key, out_key in [("team_A", "home"), ("team_B", "away")]:
        for p in sideline.get(key, []) or []:
            result[out_key].append({
                "name": p.get("name", ""),
                "number": p.get("number", ""),
                "position": p.get("position", ""),
                "reason": p.get("reason", ""),
                "type": p.get("type", ""),  # 伤病/停赛
            })
    return result


# ============================================================
# 3. 赔率 API —— euro 是机构 list + avg/max/min 汇总
# ============================================================
def dongqiudi_odds(match_id: str) -> Dict[str, Any]:
    """
    懂球帝赔率 beta API。

    实测结构（已验证）:
      顶层 keys: matchId, euro(list), asia(list), size(list),
                has_odds, max, min, avg, corner, bf, is_spe

      euro 每项: {
        "name": "威廉希尔" / "bet365" / "avg" / "max" / "min",
        "now":  {"homeWin": "1.47", "draw": "4.40", "awayWin": "4.90", "ts": "..."},
        "begin":{...},
        "area", "abbr", "cid", "fixed_odds", "is_turn"
      }

      avg / max / min 是顶层 summary 对象，结构同 euro item 的 now/begin。
    """
    url = (
        f"https://beta-sport-data.dongqiudi.com/soccer/biz/dqd/v1/"
        f"match/odds/index/{match_id}"
    )
    params = {"app": "dqd", "lang": "zh-cn", "platform": "android"}
    data = _safe_get(url, params=params)
    if not data:
        return {}

    result = {
        "has_odds": data.get("has_odds", False),
        "euro_books": [],     # 欧赔机构列表
        "asia_books": [],     # 亚盘机构列表
        "size_books": [],     # 大小球机构列表
        "avg": {},            # 平均欧赔（summary）
        "max": {},            # 最高欧赔
        "min": {},            # 最低欧赔
    }

    # ---------- 欧赔机构列表 ----------
    for book in data.get("euro", []) or []:
        result["euro_books"].append({
            "name": book.get("name", ""),
            "area": book.get("area", ""),
            "begin": book.get("begin", {}),
            "now": book.get("now", {}),
        })

    # ---------- 亚盘机构列表 ----------
    for book in data.get("asia", []) or []:
        result["asia_books"].append({
            "name": book.get("name", ""),
            "area": book.get("area", ""),
            "begin": book.get("begin", {}),  # eg "0.85半球/一球1.03"
            "now": book.get("now", {}),
        })

    # ---------- 大小球 ----------
    for book in data.get("size", []) or []:
        result["size_books"].append({
            "name": book.get("name", ""),
            "area": book.get("area", ""),
            "begin": book.get("begin", {}),
            "now": book.get("now", {}),
        })

    # ---------- 汇总（avg/max/min） ----------
    for key in ["avg", "max", "min"]:
        summary = data.get(key) or {}
        if summary:
            result[key] = {
                "begin": {
                    "home": summary.get("begin", {}).get("homeWin", ""),
                    "draw": summary.get("begin", {}).get("draw", ""),
                    "away": summary.get("begin", {}).get("awayWin", ""),
                },
                "now": {
                    "home": summary.get("now", {}).get("homeWin", ""),
                    "draw": summary.get("now", {}).get("draw", ""),
                    "away": summary.get("now", {}).get("awayWin", ""),
                },
            }

    logger.info(
        f"赔率 {match_id}: has_odds={result['has_odds']}, "
        f"欧赔机构={len(result['euro_books'])}, "
        f"亚盘={len(result['asia_books'])}"
    )
    return result


def calc_handicap_trend(odds: Dict[str, Any]) -> Dict[str, str]:
    """
    从 avg 欧赔的初盘 vs 即时盘，判断机构态度趋势。
    """
    trend = {"direction": "稳定", "signal": ""}
    avg = odds.get("avg", {})
    if not avg:
        return trend

    try:
        begin = avg.get("begin", {})
        now = avg.get("now", {})
        begin_h = float(begin.get("home", 0) or 0)
        now_h = float(now.get("home", 0) or 0)
        begin_a = float(begin.get("away", 0) or 0)
        now_a = float(now.get("away", 0) or 0)

        if begin_h > 0 and now_h > 0:
            pct_h = (now_h - begin_h) / begin_h
            if pct_h < -0.05:
                trend["direction"] = "主胜降赔"
                trend["signal"] = "机构普遍看好主队"
            elif pct_h > 0.05:
                trend["direction"] = "主胜升赔"
                trend["signal"] = "机构看淡主队"

        if begin_a > 0 and now_a > 0:
            pct_a = (now_a - begin_a) / begin_a
            if pct_a < -0.05 and not trend["signal"]:
                trend["direction"] = "客胜降赔"
                trend["signal"] = "机构看好客队"

    except (ValueError, TypeError, ZeroDivisionError):
        pass

    return trend


# ============================================================
# 4. football-data 降级（补排名）
# ============================================================
def football_data_rankings(team: str, league: str,
                           token: str = "") -> Dict[str, Any]:
    """football-data.org 拿排名（降级方案）"""
    if not token:
        return {"team": team, "rank": 0, "source": "no_token"}

    LEAGUE_CODE = {
        "英超": "PL", "西甲": "PD", "意甲": "SA",
        "德甲": "BL1", "法甲": "FL1",
    }
    code = LEAGUE_CODE.get(league)
    if not code:
        return {"team": team, "rank": 0, "source": "unsupported"}

    url = f"https://api.football-data.org/v4/competitions/{code}/standings"
    try:
        resp = requests.get(url, headers={"X-Auth-Token": token}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        table = data.get("standings", [{}])[0].get("table", [])
        for entry in table:
            tname = entry.get("team", {}).get("name", "")
            if _contains(tname, team) or _contains(team, tname):
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


# ============================================================
# 5. 统一入口 get_intel
# ============================================================
def get_intel(home: str, away: str, league: str,
              match_id: str = None,
              football_data_token: str = "") -> Dict[str, Any]:
    """
    聚合所有情报。

    优先级：懂球帝 match/analysis > 懂球帝 odds > football-data 补排名
    """
    logger.info(f"===== 情报获取: {home} vs {away} ({league}) =====")

    intel: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "home": home,
        "away": away,
        "league": league,
        "match_id": "",
        "source": "none",
        "h2h": {},
        "recent": {"home": [], "away": []},
        "league_table": {"home": {}, "away": {}},
        "ranking": {
            "home_rank": 0, "away_rank": 0,
            "home_points": 0, "away_points": 0,
        },
        "sideline": {"home": [], "away": []},
        "odds": {},
        "handicap_trend": {},
    }

    # --- Step 1: 自动找 match_id ---
    if not match_id:
        match_id = find_match_id(home, away)
    if match_id:
        intel["match_id"] = str(match_id)

    # --- Step 2: 比赛分析（懂球帝主源） ---
    if match_id:
        analysis = dongqiudi_analysis(match_id)
        if analysis:
            intel["source"] = "dongqiudi"
            intel["h2h"] = parse_h2h(analysis["battle_history"])
            intel["recent"] = parse_recent_record(analysis["recent_record"])
            intel["sideline"] = parse_sideline(analysis["sideline"])
            lt = parse_league_table(analysis["league_table"])
            intel["league_table"] = lt
            intel["ranking"] = {
                "home_rank": lt.get("home", {}).get("rank", 0),
                "away_rank": lt.get("away", {}).get("rank", 0),
                "home_points": lt.get("home", {}).get("points", 0),
                "away_points": lt.get("away", {}).get("points", 0),
            }

    # --- Step 3: 赔率（懂球帝） ---
    if match_id:
        odds = dongqiudi_odds(match_id)
        if odds:
            intel["odds"] = odds
            intel["handicap_trend"] = calc_handicap_trend(odds)

    # --- Step 4: 降级 football-data 补排名 ---
    if intel["ranking"]["home_rank"] == 0 and football_data_token:
        logger.info("懂球帝无排名数据，尝试 football-data 降级")
        home_fd = football_data_rankings(home, league, football_data_token)
        away_fd = football_data_rankings(away, league, football_data_token)
        intel["ranking"]["home_rank"] = home_fd.get("rank", 0)
        intel["ranking"]["home_points"] = home_fd.get("points", 0)
        intel["ranking"]["away_rank"] = away_fd.get("rank", 0)
        intel["ranking"]["away_points"] = away_fd.get("points", 0)
        intel["fd_home"] = home_fd
        intel["fd_away"] = away_fd

    h2h = intel["h2h"]
    sl = intel["sideline"]
    logger.info(
        f"情报完成: source={intel['source']}, match_id={intel['match_id']}, "
        f"H2H={h2h.get('total',0)}场, "
        f"伤停={len(sl['home'])+len(sl['away'])}人, "
        f"ranking={intel['ranking']}"
    )
    return intel


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    import json

    # 测试 1: 已知 match_id —— 马竞 vs 曼联 (欧冠 2026-10-13)
    print("\n" + "=" * 70)
    print("测试 1: 已知 match_id=54577210 (马竞 vs 曼联)")
    print("=" * 70)
    r1 = get_intel("马德里竞技", "曼联", "欧冠", match_id="54577210")
    print(json.dumps(r1, ensure_ascii=False, indent=2)[:4000])

    # 测试 2: 自动找 match_id —— 亚特兰大 vs 威尼斯
    print("\n" + "=" * 70)
    print("测试 2: 自动搜索 match_id (亚特兰大 vs 威尼斯)")
    print("=" * 70)
    r2 = get_intel("亚特兰大", "威尼斯", "意甲")
    print(json.dumps(r2, ensure_ascii=False, indent=2)[:4000])
