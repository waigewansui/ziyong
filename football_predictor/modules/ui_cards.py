"""Streamlit 结果卡片渲染器 —— 紧凑 HTML 版"""
from typing import List, Dict


def _conf_icon(conf: float) -> str:
    if conf >= 50:
        return "🟢"
    if conf >= 40:
        return "🟡"
    return "⚪"


def render_match_cards(results: List[Dict], columns: int = 3):
    """渲染比赛卡片网格（3 列紧凑）"""
    import streamlit as st

    if not results:
        st.info("无结果")
        return

    rows = [results[i:i + columns] for i in range(0, len(results), columns)]
    for row in rows:
        cols = st.columns(columns, gap="small")
        for col, r in zip(cols, row):
            with col:
                _render_one_card(r)


def _render_one_card(r: Dict):
    import streamlit as st

    code = r.get("场次编号", "—")
    vs = r.get("对阵", "")
    league = r.get("联赛", "")
    pick = r.get("胜平负推荐", "—")
    score = r.get("比分推荐", "—")
    conf = r.get("置信度", 0)
    cold = r.get("冷门", False)
    stake = r.get("建议金额", "")
    odds_map = r.get("真实赔率", {}) or {}
    odds = odds_map.get(pick, "")
    try:
        odds_str = f"{float(odds):.2f}" if odds else "—"
    except (ValueError, TypeError):
        odds_str = "—"

    cold_badge = "❄️" if cold else ""
    conf_icon = _conf_icon(conf)
    stake_str = f"💰 {stake}元" if stake else ""

    st.markdown(f"""
    <div style="
        border: 1px solid #2a2a2a;
        border-left: 3px solid #FF4B4B;
        border-radius: 6px;
        padding: 8px 10px;
        margin-bottom: 6px;
        background: #161616;
        font-size: 12px;
        line-height: 1.45;
    ">
        <div style="color:#888; font-size:10px; margin-bottom:2px;">
            {code} · {league} {cold_badge}
        </div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;
                    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {vs}
        </div>
        <div style="display:flex; justify-content:space-between;
                    align-items:center; color:#ddd;">
            <span>推荐 <b style="color:#FF4B4B; font-size:13px;">{pick}</b></span>
            <span>比分 <b>{score}</b></span>
        </div>
        <div style="display:flex; justify-content:space-between;
                    align-items:center; color:#aaa; font-size:11px;
                    margin-top:3px;">
            <span>赔率 {odds_str}</span>
            <span>{conf_icon} {conf:.0f}%</span>
            <span>{stake_str}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
