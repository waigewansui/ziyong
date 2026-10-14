"""
足球竞猜智能推荐系统 - Web UI (V2)
新增：
- 胜平负显示真实赔率 + 建议投入 + 满中收益 + 净收益
- 让球 / 比分 / 总进球 / 半全场 独立 Tab，每个玩法全维度展示
"""
import os
import sys
import glob
import json
import subprocess
import pandas as pd
import streamlit as st
from datetime import datetime, date

# 确保能 import modules
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 隐藏 Deploy 按钮和多余菜单
st.set_page_config(
    page_title="足球竞猜智能推荐",
    page_icon="⚽",
    layout="wide",
)
st.markdown("""
<style>
    .stDeployButton {display: none;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.title("⚽ 足球竞猜智能推荐系统")


# ============ 侧边栏 ============
with st.sidebar:
    st.header("运行参数")

    mode = st.radio("赛程来源", ["自动获取今日", "指定日期", "手动输入"], index=0)

    date_input = None
    manual_text = None

    if mode == "指定日期":
        date_input = st.date_input("选择日期", value=date.today())
    elif mode == "手动输入":
        manual_text = st.text_area(
            "手动输入赛程（每行一场）",
            height=180,
            placeholder="001 意甲 2026-10-13 亚特兰大 威尼斯\n002 欧冠 2026-10-13 马竞 曼联",
        )

    match_ids = st.text_input("match_id（可选，逗号分隔）", placeholder="54470920,54577210")

    bankroll = st.number_input("本金（元）", min_value=100, max_value=100000,
                                value=1000, step=100)

    run_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)


# ============ 运行分析 ============
if run_btn:
    cmd = [sys.executable, "main.py"]
    if mode == "指定日期" and date_input:
        cmd += ["--date", date_input.strftime("%Y-%m-%d")]
    elif mode == "手动输入" and manual_text:
        cmd += ["--manual", manual_text]
    if match_ids.strip():
        cmd += ["--match-ids", match_ids.strip()]

    st.info(f"运行命令：`{' '.join(cmd)}`")

    with st.spinner("正在分析，请稍候（约 1-3 分钟）..."):
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )

    with st.expander("📋 运行日志", expanded=False):
        st.code(result.stdout or "(无输出)", language="log")
        if result.stderr:
            st.error("错误输出：")
            st.code(result.stderr, language="log")

    if result.returncode == 0:
        st.success("✅ 分析完成！")
        st.rerun()
    else:
        st.error(f"❌ 分析失败，返回码 {result.returncode}")


# ============ 展示最新结果 ============
st.markdown("---")
st.header("📊 最新推荐结果")

json_files = sorted(glob.glob("output/recommend_*.json"), key=os.path.getmtime, reverse=True)
md_files = sorted(glob.glob("output/recommend_*.md"), key=os.path.getmtime, reverse=True)
csv_files = sorted(glob.glob("output/recommend_*.csv"), key=os.path.getmtime, reverse=True)
parlay_files = sorted(glob.glob("output/parlay_*.md"), key=os.path.getmtime, reverse=True)

if not json_files:
    st.warning("还没有输出，点左侧「开始分析」跑一次")
else:
    from modules.output import kelly_stake, prob_to_odds

    latest_json = json_files[0]
    latest_md = md_files[0] if md_files else None
    mtime = datetime.fromtimestamp(os.path.getmtime(latest_json))

    with open(latest_json, "r", encoding="utf-8") as f:
        results = json.load(f)

    st.caption(
        f"最新报告：{mtime.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"本金 {bankroll} 元 | 共 {len(results)} 场"
    )

    # 构造单玩法表格
    def build_table(rec_key: str, prob_key: str,
                    odds_key: str = "真实赔率") -> pd.DataFrame:
        rows = []
        for r in results:
            pick = r.get(rec_key, "")
            prob_map = r.get(prob_key, {}) or {}
            prob = float(prob_map.get(pick, 0))
            conf = float(r.get("置信度", 0))

            # ✅ 从对应玩法的真实赔率里取
            real_odds = r.get(odds_key, {}) or {}
            if real_odds.get(pick):
                odds = round(float(real_odds[pick]), 2)
                source = "真实"
            else:
                odds = prob_to_odds(prob)
                source = "反推"

            k = kelly_stake(prob, odds, bankroll)
            stake = k["stake_final"]

            if stake > 0:
                stake_str = f"{stake:.0f}元"
                return_str = f"{stake * odds:.2f}元"
                net_str = f"{stake * odds - stake:.2f}元"
            else:
                stake_str = "不投"
                return_str = "—"
                net_str = "—"

            rows.append({
                "场次": r.get("场次编号", ""),
                "对阵": r.get("对阵", ""),
                "推荐": pick,
                "概率": f"{prob:.2%}",
                "赔率": odds,
                "来源": source,
                "建议投入": stake_str,
                "满中收益": return_str,
                "净收益": net_str,
                "置信度": f"{conf:.2%}",
            })
        return pd.DataFrame(rows)

    # 5 个 Tab
    tab_wdl, tab_hd, tab_score, tab_total, tab_hf = st.tabs(
        ["🎯 胜平负", "🔀 让球", "🎲 比分", "⚽ 总进球", "🔁 半全场"]
    )

    with tab_wdl:
        st.dataframe(build_table("胜平负推荐", "胜平负概率", "真实赔率"),
                     use_container_width=True, hide_index=True)
    with tab_hd:
        st.dataframe(build_table("让球推荐", "让球概率", "真实赔率_让球"),
                     use_container_width=True, hide_index=True)
    with tab_score:
        st.dataframe(build_table("比分推荐", "比分概率", "真实赔率_比分"),
                     use_container_width=True, hide_index=True)
    with tab_total:
        st.dataframe(build_table("总进球推荐", "总进球概率", "真实赔率_总进球"),
                     use_container_width=True, hide_index=True)
    with tab_hf:
        st.dataframe(build_table("半全场推荐", "半全场概率", "真实赔率_半全场"),
                     use_container_width=True, hide_index=True)

    # 串关
    st.markdown("---")
    st.subheader("🎯 串关推荐")
    if parlay_files:
        for pf in parlay_files[:6]:
            with open(pf, "r", encoding="utf-8") as f:
                with st.expander(os.path.basename(pf), expanded=False):
                    st.markdown(f.read())
    else:
        st.info("暂无串关推荐（可能置信度不足）")

    # 下载
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if latest_md:
            with open(latest_md, "rb") as f:
                st.download_button(
                    "⬇️ 下载 Markdown 报告",
                    f.read(),
                    file_name=os.path.basename(latest_md),
                    mime="text/markdown",
                    use_container_width=True,
                )
    with col2:
        if csv_files:
            with open(csv_files[0], "rb") as f:
                st.download_button(
                    "⬇️ 下载 CSV",
                    f.read(),
                    file_name=os.path.basename(csv_files[0]),
                    mime="text/csv",
                    use_container_width=True,
                )