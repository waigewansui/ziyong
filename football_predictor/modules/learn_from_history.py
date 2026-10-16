"""
从手动复制的体彩赛果 CSV 学习真实参数
适配格式：
赛事日期 | 赛事编号 | 联赛 | 主队（让球）vs客队 | 半场比分 | 全场比分 | 胜 | 平 | 负 | 状态 | 详情链接
"""
import os, re, csv, json, glob, logging, yaml
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("learn")

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "sporttery_history"
)
OUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "config"
)

RE_WITH_HC = re.compile(r"^(.+?)\(([+-]?\d+\.?\d*)\)\s*[Vv][Ss]\s*(.+)$")
RE_NO_HC = re.compile(r"^(.+?)\s*[Vv][Ss]\s*(.+)$")


def _norm_score(s):
    s = (s or "").strip()
    if ":" not in s:
        return ""
    try:
        h, a = s.split(":", 1)
        return f"{int(h)}:{int(a)}"
    except Exception:
        return s


def _parse_score(s):
    if not s or ":" not in s:
        return None
    try:
        h, a = s.split(":", 1)
        return int(h), int(a)
    except Exception:
        return None


def _parse_teams(s):
    s = (s or "").strip()
    m = RE_WITH_HC.match(s)
    if m:
        return m.group(1).strip(), m.group(3).strip(), m.group(2).strip()
    m = RE_NO_HC.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip(), "0"
    return s, "", "0"


def _f(s):
    s = str(s or "").strip()
    if s in ("--", "", "-", "null", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_csv(path):
    if not os.path.exists(path):
        logger.error(f"CSV 不存在: {path}")
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,;|")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)

        rows = []
        for row in reader:
            def g(*keys):
                for k in keys:
                    for rk in row:
                        if rk and k in rk:
                            return (row[rk] or "").strip()
                return ""
            date_raw = g("赛事日期", "日期")
            code = g("赛事编号", "编号")
            league = g("联赛")
            vs_raw = g("主队", "对阵")
            half = g("半场")
            full = g("全场", "比分")
            w = _f(g("胜"))
            d = _f(g("平"))
            a = _f(g("负"))
            if not vs_raw or not full:
                continue
            home, away, hc = _parse_teams(vs_raw)
            rows.append({
                "日期": date_raw.replace("/", "-"),
                "场次编号": code,
                "联赛": league,
                "主队": home,
                "客队": away,
                "让球": hc,
                "半场比分": _norm_score(half),
                "全场比分": _norm_score(full),
                "胜赔": w, "平赔": d, "负赔": a,
            })
    logger.info(f"解析 CSV: {len(rows)} 场")
    return rows


def learn_league(matches):
    stats = defaultdict(lambda: {"g": [], "H": 0, "D": 0, "A": 0, "n": 0})
    for m in matches:
        sc = _parse_score(m.get("全场比分", ""))
        if not sc:
            continue
        h, a = sc
        lg = m.get("联赛", "") or "未知"
        stats[lg]["g"].append(h + a)
        stats[lg]["n"] += 1
        if h > a: stats[lg]["H"] += 1
        elif h == a: stats[lg]["D"] += 1
        else: stats[lg]["A"] += 1
    out = {}
    for lg, s in stats.items():
        if s["n"] < 10:
            continue
        n = s["n"]
        out[lg] = {
            "场次": n,
            "场均进球": round(sum(s["g"]) / n, 3),
            "主胜率": round(s["H"] / n, 4),
            "平局率": round(s["D"] / n, 4),
            "客胜率": round(s["A"] / n, 4),
        }
    return out


def learn_handicap(matches):
    stats = defaultdict(lambda: {"W": 0, "D": 0, "L": 0, "n": 0})
    for m in matches:
        sc = _parse_score(m.get("全场比分", ""))
        if not sc:
            continue
        h, a = sc
        try:
            hc = float(str(m.get("让球", "0") or "0").replace("+", ""))
        except Exception:
            hc = 0.0
        adjusted = (h - a) + hc
        if adjusted > 0: wf = "W"
        elif adjusted == 0: wf = "D"
        else: wf = "L"
        key = f"{hc:+.1f}"
        stats[key][wf] += 1
        stats[key]["n"] += 1
    out = {}
    for k, s in stats.items():
        if s["n"] < 10:
            continue
        n = s["n"]
        out[k] = {
            "场次": n,
            "让胜": round(s["W"] / n, 4),
            "让平": round(s["D"] / n, 4),
            "让负": round(s["L"] / n, 4),
        }
    return out


def learn_scores(matches, top=25):
    c = defaultdict(int)
    for m in matches:
        s = m.get("全场比分", "")
        if s:
            c[s] += 1
    total = sum(c.values())
    if not total:
        return {}
    top_list = sorted(c.items(), key=lambda x: -x[1])[:top]
    return {s: {"次数": n, "占比": round(n / total, 4)}
            for s, n in top_list}


def learn_half_full(matches):
    c = defaultdict(int)
    for m in matches:
        hs = _parse_score(m.get("半场比分", ""))
        fs = _parse_score(m.get("全场比分", ""))
        if not hs or not fs:
            continue
        hh, ha = hs; fh, fa = fs
        half = "胜" if hh > ha else ("平" if hh == ha else "负")
        full = "胜" if fh > fa else ("平" if fh == fa else "负")
        c[f"{half}{full}"] += 1
    total = sum(c.values())
    if not total:
        return {}
    return {k: round(v / total, 4)
            for k, v in sorted(c.items(), key=lambda x: -x[1])}


def learn_odds_calibration(matches):
    buckets = defaultdict(lambda: {"H": 0, "D": 0, "A": 0, "n": 0})
    for m in matches:
        sc = _parse_score(m.get("全场比分", ""))
        if not sc:
            continue
        w, d, a = m.get("胜赔"), m.get("平赔"), m.get("负赔")
        if not (w and d and a):
            continue
        h, away = sc
        actual = "H" if h > away else ("D" if h == away else "A")
        try:
            inv = 1/w + 1/d + 1/a
            p_h = (1/w) / inv
        except Exception:
            continue
        if p_h >= 0.55: bk = "强主(>=55%)"
        elif p_h >= 0.45: bk = "中主(45~55%)"
        elif p_h >= 0.35: bk = "弱主(35~45%)"
        else: bk = "客优(<35%)"
        buckets[bk][actual] += 1
        buckets[bk]["n"] += 1
    out = {}
    for k, s in buckets.items():
        if s["n"] < 10:
            continue
        n = s["n"]
        out[k] = {
            "场次": n,
            "实际主胜": round(s["H"] / n, 4),
            "实际平": round(s["D"] / n, 4),
            "实际客胜": round(s["A"] / n, 4),
        }
    return out


def save_yaml(learned):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "learned.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(learned, f, allow_unicode=True, sort_keys=False)
    logger.info(f"learned.yaml 已保存: {path}")
    return path


def print_report(L):
    print("\n" + "=" * 60)
    print("学习结果")
    print("=" * 60)
    print(f"\n总样本: {L['总场次']} 场")
    print("\n--- 各联赛真实数据（前 15）---")
    for lg, s in sorted(L["联赛统计"].items(),
                        key=lambda x: -x[1]["场次"])[:15]:
        print(f"  {lg:16s} {s['场次']:>5}场  "
              f"场均 {s['场均进球']:.2f}球  "
              f"主胜 {s['主胜率']:.1%}  平 {s['平局率']:.1%}  "
              f"客胜 {s['客胜率']:.1%}")
    print("\n--- 让球盘口真实分布 ---")
    for hc, s in sorted(L["让球分布"].items()):
        print(f"  让球 {hc:>5s}: {s['场次']:>5}场  "
              f"让胜 {s['让胜']:.1%}  让平 {s['让平']:.1%}  "
              f"让负 {s['让负']:.1%}")
    print("\n--- Top 10 比分 ---")
    for sc, s in list(L["比分分布"].items())[:10]:
        print(f"  {sc:>5s}  {s['次数']:>5}场  {s['占比']:.2%}")
    print("\n--- 半全场分布（前 9）---")
    for k, v in list(L["半全场分布"].items())[:9]:
        print(f"  {k}  {v:.2%}")
    print("\n--- 赔率校准 ---")
    for k, s in L["赔率校准"].items():
        print(f"  {k:14s} {s['场次']:>5}场  "
              f"实际主胜 {s['实际主胜']:.1%}  "
              f"平 {s['实际平']:.1%}  客 {s['实际客胜']:.1%}")


def run():
    cands = glob.glob(os.path.join(CACHE_DIR, "*.csv"))
    if not cands:
        logger.error(f"{CACHE_DIR} 下没有 CSV")
        return
    csv_path = cands[0]
    logger.info(f"读取: {csv_path}")
    matches = parse_csv(csv_path)
    if len(matches) < 50:
        logger.error(f"样本太少 ({len(matches)})")
        return
    seen, uniq = set(), []
    for m in matches:
        k = (m["日期"], m["场次编号"])
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    logger.info(f"去重后: {len(uniq)} 场")
    L = {
        "总场次": len(uniq),
        "学习时间": datetime.now().isoformat(),
        "联赛统计": learn_league(uniq),
        "让球分布": learn_handicap(uniq),
        "比分分布": learn_scores(uniq),
        "半全场分布": learn_half_full(uniq),
        "赔率校准": learn_odds_calibration(uniq),
    }
    save_yaml(L)
    print_report(L)


if __name__ == "__main__":
    run()
