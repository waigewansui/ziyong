"""Streamlit 结果卡片 —— 彩票紧凑风"""
from typing import List, Dict


def _conf_dot(conf: float) -> str:
    if conf >= 50:
        return "#4CAF50"   # 绿
    if conf >= 40:
        return "#FFC107"   # 黄
    return "#888"          # 灰


def _pick_color(pick: str) -> str:
    if pick == "胜":
        return "#FF4B4B"
    if pick == "负":
        return "#4B9FFF"
    return "#FFC107"       # 平


def render_match_cards(results: List[Dict], columns: int = 6):
    import streamlit as st

    if not results:
        st.info("无结果")
        return

    cards = []
    for r in results:
        code = r.get("场次编号", "")
        vs = r.get("对阵", "")
        league = r.get("联赛", "")
        pick = r.get("胜平负推荐", "—")
        score = r.get("比分推荐", "—")
        conf = float(r.get("置信度", 0) or 0)
        cold = r.get("冷门", False)
        stake = float(r.get("建议金额", 0) or 0)
        odds_map = r.get("真实赔率", {}) or {}
        odds = odds_map.get(pick, "")
        try:
            odds_str = f"{float(odds):.2f}" if odds else "—"
        except (ValueError, TypeError):
            odds_str = "—"

        cold_tag = "❄️" if cold else ""
        dot = _conf_dot(conf)
        pick_color = _pick_color(pick)
        stake_html = (f'<span style="color:#FFD700;">💰{stake:.0f}</span>'
                      if stake > 0 else '')

        cards.append(f"""
        <div style="
            border:1px solid #2a2a2a;
            border-radius:5px;
            padding:5px 7px;
            background:#151515;
            font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
            height:80px;
            box-sizing:border-box;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
            overflow:hidden;
        ">
          <div style="color:#666; font-size:8px; white-space:nowrap;
                      overflow:hidden; text-overflow:ellipsis;
                      line-height:1;">
            {code} · {league} {cold_tag}
          </div>
          <div style="color:#eee; font-size:11px; font-weight:600;
                      white-space:nowrap; overflow:hidden;
                      text-overflow:ellipsis; line-height:1.2;"
               title="{vs}">
            {vs}
          </div>
          <div style="display:flex; align-items:baseline;
                      justify-content:space-between; gap:3px;
                      line-height:1;">
            <span style="color:{pick_color}; font-size:17px;
                         font-weight:800;">{pick}</span>
            <span style="color:#ccc; font-size:11px;
                         font-family:Consolas,'JetBrains Mono',monospace;">{score}</span>
            <span style="color:#aaa; font-size:10px;
                         font-family:Consolas,'JetBrains Mono',monospace;">{odds_str}</span>
            <span style="color:{dot}; font-size:9px;
                         font-family:Consolas,'JetBrains Mono',monospace;">●{conf:.0f}</span>
          </div>
          <div style="display:flex; justify-content:flex-end;
                      font-size:9px; line-height:1;">
            {stake_html}
          </div>
        </div>
        """)

    grid = f"""
    <div style="
        display:grid;
        grid-template-columns:repeat({columns}, minmax(0,1fr));
        gap:6px;
        width:100%;
    ">
        {''.join(cards)}
    </div>
    """
    st.markdown(grid, unsafe_allow_html=True)
