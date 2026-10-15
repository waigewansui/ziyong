"""Streamlit 结果卡片 —— 5 列大号统一高度版"""
from typing import List, Dict


# 联赛名缩写（省空间）
LEAGUE_SHORT = {
    "欧罗巴": "欧联", "欧罗巴联赛": "欧联",
    "欧洲联赛": "欧联", "欧洲冠军联赛": "欧冠",
    "英格兰超级联赛": "英超", "英格兰冠军联赛": "英冠",
    "西班牙甲级联赛": "西甲", "西班牙足球甲级联赛": "西甲",
    "意大利甲级联赛": "意甲", "意大利足球甲级联赛": "意甲",
    "德国甲级联赛": "德甲", "德国足球甲级联赛": "德甲",
    "法国甲级联赛": "法甲", "法国足球甲级联赛": "法甲",
    "亚足联冠军联赛": "亚冠", "亚足联冠军联赛精英": "亚冠精英",
    "南美解放者杯": "解放者杯", "美国职业足球大联盟": "美职",
    "荷兰甲级联赛": "荷甲", "葡萄牙超级联赛": "葡超",
    "欧协联": "欧协", "欧洲协会联赛": "欧协",
}


def _short_league(name: str) -> str:
    return LEAGUE_SHORT.get(name, name)


def _conf_dot(conf: float) -> str:
    if conf >= 50:
        return "#4CAF50"   # 绿
    if conf >= 40:
        return "#FFC107"   # 黄
    return "#666"          # 灰


def render_match_cards(results: List[Dict], columns: int = 5):
    import streamlit as st

    if not results:
        st.info("无结果")
        return

    cards_html = []
    for r in results:
        code = r.get("场次编号", "—")
        vs = r.get("对阵", "")
        league = _short_league(r.get("联赛", ""))
        pick = r.get("胜平负推荐", "—")
        score = r.get("比分推荐", "—")
        conf = r.get("置信度", 0)
        cold = r.get("冷门", False)
        stake = r.get("建议金额", 0) or 0
        odds_map = r.get("真实赔率", {}) or {}
        odds = odds_map.get(pick, "")

        # 赔率只显示 1 位小数
        try:
            odds_str = f"{float(odds):.1f}" if odds else "—"
        except (ValueError, TypeError):
            odds_str = "—"

        cold_tag = "❄️" if cold else ""
        dot = _conf_dot(conf)
        conf_visible = conf > 0
        stake_visible = float(stake) > 0
        stake_str = f"💰{float(stake):.0f}" if stake_visible else ""

        cards_html.append(f"""
        <div style="
            border:1px solid #2a2a2a;
            border-left:3px solid {dot};
            border-radius:6px;
            padding:10px 12px;
            background:#161616;
            font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
            height:140px;
            box-sizing:border-box;
            display:flex;
            flex-direction:column;
            transition:border-color .15s, background .15s;
        " onmouseover="this.style.borderColor='#FF4B4B';this.style.background='#1b1e2e'"
           onmouseout="this.style.borderColor='#2a2a2a';this.style.background='#161616'">

            <div style="color:#888; font-size:11px; margin-bottom:3px; flex-shrink:0;">
                {code} · {league}{cold_tag}
            </div>

            <div style="
                color:#eee; font-weight:700; font-size:14px;
                margin-bottom:6px;
                display:-webkit-box;
                -webkit-line-clamp:2;
                -webkit-box-orient:vertical;
                overflow:hidden;
                line-height:1.25;
                min-height:34px;
            " title="{vs}">{vs}</div>

            <div style="display:flex; justify-content:space-between;
                        align-items:baseline; margin-bottom:4px;">
                <span style="color:#FF4B4B; font-weight:700; font-size:16px;">{pick}</span>
                <span style="color:#ddd; font-weight:600; font-size:15px;">{score}</span>
            </div>

            <div style="display:flex; justify-content:space-between;
                        align-items:center; color:#aaa; font-size:12px;
                        margin-top:auto; padding-top:4px;">
                <span style="min-width:40px;">{odds_str}</span>
                <span style="color:{dot}; font-weight:600;">
                    {'● ' + f'{conf:.0f}%' if conf_visible else ''}
                </span>
                <span style="color:#9aa0b4;">{stake_str}</span>
            </div>
        </div>
        """)

    grid_html = f"""
    <div style="
        display:grid;
        grid-template-columns:repeat({columns}, minmax(0, 1fr));
        gap:8px;
        width:100%;
    ">
        {''.join(cards_html)}
    </div>
    """
    st.markdown(grid_html, unsafe_allow_html=True)
