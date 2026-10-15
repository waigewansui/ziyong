"""
投注单生成器 — 把分析结果转成可直接复制到竞彩 App / 微信的文本
"""
from typing import List, Dict


def _fmt_odds(o) -> str:
    try:
        return f"{float(o):.2f}"
    except Exception:
        return "—"


def generate_slip(results: List[Dict], mode: str = "single",
                  bankroll: float = 1000) -> str:
    """
    mode:
      - "single": 单场推荐（含金额）
      - "parlay": 串关推荐
    """
    lines = []
    lines.append(f"⚽ 今日推荐（{len(results)} 场）")
    lines.append("─" * 28)

    if mode == "single":
        for r in results:
            code = r.get("场次编号", "—")
            vs = r.get("对阵", "")
            pick = r.get("胜平负推荐", "")
            score = r.get("比分推荐", "")
            conf = r.get("置信度", 0)
            odds_map = r.get("真实赔率", {}) or {}
            odds = _fmt_odds(odds_map.get(pick, "—"))
            cold = "❄️" if r.get("冷门") else ""
            stake = r.get("建议金额", "")

            line = f"{code} {vs}"
            lines.append(line)
            sub = f"  → {cold}{pick} @ {odds} | 比分 {score} | 置信 {conf:.0f}%"
            if stake:
                sub += f" | 建议 {stake}元"
            lines.append(sub)

    elif mode == "parlay":
        for r in results:
            code = r.get("场次编号", "—")
            vs = r.get("对阵", "")
            pick = r.get("胜平负推荐", "")
            odds_map = r.get("真实赔率", {}) or {}
            odds = _fmt_odds(odds_map.get(pick, "—"))
            lines.append(f"{code} {vs} → {pick} @ {odds}")

        # 总赔率
        total_odds = 1.0
        for r in results:
            pick = r.get("胜平负推荐", "")
            odds_map = r.get("真实赔率", {}) or {}
            try:
                total_odds *= float(odds_map.get(pick, 1.0))
            except Exception:
                pass
        lines.append("─" * 28)
        lines.append(f"串关总赔率 ≈ {total_odds:.2f}")

    lines.append("")
    lines.append(f"本金 {bankroll}元")
    return "\n".join(lines)
