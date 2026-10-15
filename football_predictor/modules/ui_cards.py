"""Streamlit 结果卡片 —— 6 列超紧凑 HTML 版"""
from typing import List, Dict


def _conf_dot(conf: float) -> str:
    if conf >= 50:
        return "#4CAF50"   # 绿
    if conf >= 40:
        return "#FFC107"   # 黄
    return "#666"          # 灰


def render_match_cards(results: List[Dict], columns: int = 6):
    import streamlit as st

    if not results:
        st.info("无结果")
        return

    cards_html = []
    for r in results:
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

        cold_tag = "❄️" if cold else ""
        dot = _conf_dot(conf)
        stake_str = f"{stake}元" if stake else ""

        # 对阵名太长就截断
        vs_short = vs if len(vs) <= 14 else vs[:13] + "…"

        cards_html.append(f"""
        <div style="
            border:1px solid #23263a;
            border-left:2px solid {dot};
            border-radius:6px;
            padding:6px 8px;
            background:#161822;
            font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
            font-size:10.5px;
            line-height:1.4;
            height:100%;
            box-sizing:border-box;
            transition:border-color .15s, background .15s;
        " onmouseover="this.style.borderColor='#FF4B4B';this.style.background='#1b1e2e'"
           onmouseout="this.style.borderColor='#23263a';this.style.background='#161822'">
            <div style="color:#7a8094; font-size:8px; margin-bottom:2px;
                        white-space:nowrap; overflow:hidden;
                        text-overflow:ellipsis;">
                {code} · {league}{cold_tag}
            </div>
            <div style="color:#e8eaf0; font-weight:600; font-size:11px;
                        margin-bottom:4px; white-space:nowrap;
                        overflow:hidden; text-overflow:ellipsis;"
                 title="{vs}">
                {vs_short}
            </div>
            <div style="display:flex; justify-content:space-between;
                        color:#c4c8d8; font-size:10.5px;">
                <span style="color:#FF4B4B; font-weight:700; font-size:11px;">{pick}</span>
                <span style="color:#b0b4c4; font-weight:500;">{score}</span>
            </div>
            <div style="display:flex; justify-content:space-between;
                        color:#8a90a4; font-size:9px; margin-top:3px;">
                <span>{odds_str}</span>
                <span style="color:{dot}; font-weight:600;">● {conf:.0f}%</span>
                <span style="color:#9aa0b4;">{stake_str}</span>
            </div>
        </div>
        """)

    # 用 CSS grid 一次性渲染，6 列等宽
    grid_html = f"""
    <div style="
        display:grid;
        grid-template-columns:repeat({columns}, minmax(0, 1fr));
        gap:6px;
        width:100%;
    ">
        {''.join(cards_html)}
    </div>
    """
    st.markdown(grid_html, unsafe_allow_html=True)
