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

# ✅ 今日概览
try:
    files_overview = sorted(glob.glob("output/recommend_*.json"), reverse=True)
    if files_overview:
        with open(files_overview[0], encoding="utf-8") as f:
            latest_overview = json.load(f)
        total = len(latest_overview)
        high_conf = sum(1 for r in latest_overview if r.get("置信度", 0) >= 0.45)
        cold_count = sum(1 for r in latest_overview if r.get("冷门"))
        total_stake = sum(float(r.get("建议金额", 0) or 0) for r in latest_overview)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📊 场次", total)
        c2.metric("🔥 高置信 (≥45%)", high_conf)
        c3.metric("❄️ 冷门", cold_count)
        c4.metric("💰 建议总投注", f"{total_stake:.0f}元")
except Exception:
    pass


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

    # 是否过滤低置信度
    no_filter = st.checkbox("显示全部（不过滤）", value=False,
                             help="勾选后显示全部场次，不勾选只显示高置信度")

    run_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)

    # ✅ 重新预测按钮
    st.markdown("---")
    st.caption("💡 结果不新鲜？点下方重新跑一次")
    rerun_btn = st.button("🔄 重新预测", use_container_width=True)

    # ✅ 关注过滤
    st.markdown("---")
    st.subheader("🎯 关注过滤")

    from modules.team_filter import POPULAR_TEAMS
    watch_teams = st.multiselect(
        "只看这些队（留空=全部）",
        options=POPULAR_TEAMS,
        default=[],
        key="watch_teams",
    )
    watch_leagues = st.multiselect(
        "只看这些联赛",
        options=["英超", "西甲", "意甲", "德甲", "法甲",
                 "欧冠", "欧联", "亚冠", "日联赛杯", "美职",
                 "解放者杯", "英冠"],
        default=[],
        key="watch_leagues",
    )
    only_cold = st.checkbox("❄️ 只看冷门", value=False, key="only_cold")

    cached_btn = st.button("⚡ 秒跑（用今日缓存）", use_container_width=True)


# ============ 运行分析 ============
if run_btn or rerun_btn or cached_btn:
    cmd = [sys.executable, "main.py"]
    if cached_btn and not (run_btn or rerun_btn):
        cmd.append("--cached")
    elif mode == "指定日期" and date_input:
        cmd += ["--date", date_input.strftime("%Y-%m-%d")]
    elif mode == "手动输入" and manual_text:
        cmd += ["--manual", manual_text]
    if match_ids.strip():
        cmd += ["--match-ids", match_ids.strip()]
    if no_filter:
        cmd += ["--no-filter"]

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

    from modules.error_helper import friendly_error

    if result.returncode == 0:
        st.success("✅ 分析完成！")
        # ✅ 保存结果供后续过滤/投注单使用
        import glob
        files = sorted(glob.glob("output/recommend_*.json"), reverse=True)
        if files:
            try:
                with open(files[0], encoding="utf-8") as f:
                    st.session_state["latest_results"] = json.load(f)
            except Exception:
                pass
        st.rerun()
    else:
        st.error(friendly_error(result.stderr))
        with st.expander("🔧 原始错误（点开贴给开发者）", expanded=False):
            st.code(result.stderr or "(无 stderr)", language="log")


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

    # 8 个 Tab
    tab_wdl, tab_hd, tab_score, tab_total, tab_hf, tab_hist, tab_bets, tab_perf = st.tabs(
        ["🎯 胜平负", "🔀 让球", "🎲 比分", "⚽ 总进球", "🔁 半全场",
         "📅 历史", "💰 收益", "📈 模型命中率"]
    )

    with tab_wdl:
        # ✅ 过滤器 + 投注单 + 结果表
        from modules.betting_slip import generate_slip
        from modules.team_filter import filter_results

        results_raw = st.session_state.get("latest_results", []) or results
        filtered = filter_results(
            results_raw,
            teams=set(watch_teams) if watch_teams else None,
            leagues=set(watch_leagues) if watch_leagues else None,
            only_cold=only_cold,
        )
        if only_cold or watch_teams or watch_leagues:
            st.caption(f"🎯 过滤后 {len(filtered)} 场（原始 {len(results_raw)} 场）")

        slip_text = generate_slip(filtered, mode="single")
        st.text_area("📋 投注单（点右上角 ⧉ 复制到竞彩 App）", slip_text,
                     height=180, key="slip_text")
        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "💾 下载投注单 .txt",
                data=slip_text,
                file_name=f"betting_slip_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_b:
            slip_parlay = generate_slip(filtered, mode="parlay")
            st.download_button(
                "🔗 串关投注单",
                data=slip_parlay,
                file_name=f"betting_parlay_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

        st.markdown("---")
        st.subheader("🎯 胜平负推荐（完整）")

        from modules.ui_cards import render_match_cards
        render_match_cards(filtered, columns=2)
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

    with tab_hist:
        st.subheader("📅 最近 10 天历史报告")
        from glob import glob
        history_dirs = sorted(
            glob(os.path.join(BASE_DIR, "output", "history", "*")), reverse=True
        )[:10]
        for d in history_dirs:
            date_str = os.path.basename(d)
            md_files = glob(os.path.join(d, "recommend_*.md"))
            with st.expander(f"{date_str} ({len(md_files)} 份报告)"):
                for f in md_files[:1]:
                    st.markdown(open(f, encoding="utf-8").read()[:2000])
        if not history_dirs:
            st.info("暂无历史报告")

    with tab_bets:
        st.subheader("💰 投注收益跟踪")
        from modules.bets_tracker import load_bets, summary
        s = summary()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总投入", f"{s['总投入']}元")
        col2.metric("净盈亏", f"{s['净盈亏']}元")
        col3.metric("ROI", f"{s['ROI']:.2%}")
        col4.metric("命中率", f"{s['命中率']:.2%}")

        bets = load_bets()
        if bets:
            df = pd.DataFrame(bets)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无投注记录")

    with tab_perf:
        st.subheader("📈 模型累计命中率")
        from modules.performance_tracker import load_performance
        perf = load_performance()

        if perf.get("总场次", 0) == 0:
            st.info("暂无结算数据。明天比赛踢完后，跑 `python main.py --settle` 即可。")
        else:
            st.caption(f"累计 {perf['总场次']} 场结算")

            st.markdown("### 各玩法命中率")
            plays_data = []
            for play, s in perf["各玩法"].items():
                plays_data.append({
                    "玩法": play,
                    "有效场次": s["有效场次"],
                    "命中": s["命中"],
                    "命中率": f"{s['命中率']:.2%}",
                })
            st.dataframe(plays_data, use_container_width=True, hide_index=True)

            st.markdown("### 凯利模拟收益")
            k = perf["凯利模拟"]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("初始本金", f"{k['初始本金']}元")
            col2.metric("最终余额", f"{k['最终余额']}元")
            col3.metric("净盈亏", f"{k['净盈亏']}元")
            col4.metric("ROI", f"{k['ROI']:.2%}")
            st.caption(f"下注 {k['下注次数']} 次，命中 {k['命中次数']} 次，命中率 {k['命中率']:.2%}")

        st.markdown("---")
        st.caption("💡 结算昨天的预测：点下方按钮")
        if st.button("🔍 结算昨天", use_container_width=True):
            with st.spinner("正在结算..."):
                result = subprocess.run(
                    [sys.executable, "main.py", "--settle"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=600,
                )
            with st.expander("📋 结算日志", expanded=True):
                st.code(result.stdout or "(无输出)", language="log")
            if result.returncode == 0:
                st.success("✅ 结算完成，刷新页面查看最新命中率")
                st.rerun()
            else:
                st.error(f"❌ 结算失败，返回码 {result.returncode}")

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