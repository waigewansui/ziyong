"""Streamlit 结果卡片渲染器"""
from typing import List, Dict


def _conf_color(conf: float) -> str:
    if conf >= 0.50:
        return "🟢"
    if conf >= 0.40:
        return "🟡"
    return "⚪"


def render_match_cards(results: List[Dict], columns: int = 2):
    """渲染比赛卡片网格"""
    import streamlit as st

    if not results:
        st.info("无结果")
        return

    rows = [results[i:i + columns] for i in range(0, len(results), columns)]
    for row in rows:
        cols = st.columns(columns)
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

    cold_badge = " ❄️" if cold else ""
    conf_icon = _conf_color(conf)

    with st.container(border=True):
        st.caption(f"{code} · {league}{cold_badge}")
        st.markdown(f"**{vs}**")

        c1, c2 = st.columns(2)
        c1.metric("推荐", pick)
        c2.metric("比分", score)

        c3, c4 = st.columns(2)
        if odds:
            try:
                c3.metric("赔率", f"{float(odds):.2f}")
            except (ValueError, TypeError):
                c3.metric("赔率", "—")
        else:
            c3.metric("赔率", "—")
        c4.metric("置信", f"{conf_icon} {conf:.0f}%")

        if stake:
            st.caption(f"💰 建议 {stake} 元")
