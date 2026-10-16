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

# 隐藏 Deploy 按钮和多余菜单 + 全局字体排版
st.set_page_config(
    page_title="足球竞猜智能推荐",
    page_icon="⚽",
    layout="wide",
)
st.markdown("""
<style>
    /* ====== 字体栈 ====== */
    html, body, [class*="css"], .stApp {
        font-family: -apple-system, BlinkMacSystemFont,
            "PingFang SC", "Microsoft YaHei", "微软雅黑",
            "Helvetica Neue", Arial, "Noto Sans SC", sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    code, pre, kbd, samp {
        font-family: "JetBrains Mono", "Fira Code", "Cascadia Code",
            Menlo, Consolas, "Microsoft YaHei Mono", monospace;
    }

    /* ====== 色盘微调 ====== */
    .stApp { background: #0D0F13; }

    /* ====== 标题层级 ====== */
    h1, .stApp h1 { font-size: 1.75rem; font-weight: 700; letter-spacing: -0.01em; }
    h2, .stApp h2 { font-size: 1.35rem; font-weight: 600; letter-spacing: -0.005em; }
    h3, .stApp h3 { font-size: 1.15rem; font-weight: 600; }
    .stMarkdown { font-size: 0.95rem; line-height: 1.6; }

    /* ====== Metric / 概览卡片 ====== */
    [data-testid="stMetric"] {
        padding: 0.6rem 0.8rem;
        background: #161822;
        border: 1px solid #23263a;
        border-radius: 10px;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.75rem !important;
        color: #9aa0b4 !important;
        letter-spacing: 0.02em;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: #FAFAFA !important;
        letter-spacing: -0.02em;
    }

    /* ====== Tabs ====== */
    [data-testid="stTabs"] [role="tablist"] {
        gap: 4px;
    }
    [data-testid="stTabs"] [role="tab"] {
        font-size: 0.88rem !important;
        font-weight: 500;
        padding: 0.45rem 0.9rem !important;
        border-radius: 6px 6px 0 0;
    }

    /* ====== Dataframe ====== */
    .stDataFrame {
        font-size: 0.85rem !important;
    }
    .stDataFrame table th {
        background: #161822 !important;
        color: #c4c8d8 !important;
        font-weight: 600 !important;
        font-size: 0.8rem !important;
    }
    .stDataFrame table td {
        padding: 0.35rem 0.5rem !important;
    }

    /* ====== Code block ====== */
    pre {
        border-radius: 8px !important;
        border: 1px solid #23263a !important;
        background: #0A0C12 !important;
        font-size: 0.82rem !important;
        line-height: 1.5 !important;
    }
    code { font-size: 0.85em; }

    /* ====== Expander ====== */
    [data-testid="stExpander"] {
        border: 1px solid #23263a !important;
        border-radius: 8px !important;
    }

    /* ====== Sidebar 间距 ====== */
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }

    /* ====== Hide ====== */
    .stDeployButton { display: none; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    header { visibility: hidden; }
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

    # 9 个 Tab（新增 🔗串关）
    (tab_wdl, tab_hd, tab_score, tab_total, tab_hf,
     tab_parlay, tab_hist, tab_bets, tab_perf) = st.tabs([
        "🎯 胜平负", "🔀 让球", "🎲 比分", "⚽ 总进球", "🔁 半全场",
        "🔗 串关", "📅 历史", "💰 收益", "📈 模型命中率",
    ])

    with tab_wdl:
        st.subheader("🎯 胜平负推荐")

        from modules.team_filter import filter_results
        results_latest = st.session_state.get("latest_results", [])
        if not results_latest:
            st.info("还没有结果，点左侧「开始分析」跑一次")
        else:
            watch_teams_s = st.session_state.get("watch_teams", [])
            watch_leagues_s = st.session_state.get("watch_leagues", [])
            only_cold_s = st.session_state.get("only_cold", False)

            filtered = filter_results(
                results_latest,
                teams=set(watch_teams_s),
                leagues=set(watch_leagues_s),
                only_cold=only_cold_s,
            )
            st.caption(f"过滤后 {len(filtered)} 场（原始 {len(results_latest)} 场）")

            from modules.ui_cards import render_match_cards
            render_match_cards(filtered, columns=5)
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

    # ============================================================
    # 🔗 串关 Tab
    # ============================================================
    with tab_parlay:
        st.subheader("🔗 串关工具")

        results_p = st.session_state.get("latest_results", [])
        if not results_p:
            st.info("还没有结果，先跑一次分析")
        else:
            # --- 场次来源切换 ---
            source = st.radio(
                "场次来源",
                options=["从推荐结果选", "从全部 24 场选"],
                horizontal=True,
                key="parlay_source",
            )

            if source == "从推荐结果选":
                wt = st.session_state.get("watch_teams", [])
                wl = st.session_state.get("watch_leagues", [])
                from modules.team_filter import filter_results as _f
                pool = _f(results_p, teams=set(wt), leagues=set(wl))
            else:
                pool = results_p

            st.caption(f"候选 {len(pool)} 场")

            # --- 玩法切换（顶栏） ---
            play_mode = st.radio(
                "玩法",
                ["胜平负", "让球胜平负", "比分", "总进球", "半全场", "混合过关"],
                horizontal=True,
                key="parlay_play_mode",
            )
            # 兼容旧 key 名
            play_type_map = {
                "胜平负": "胜平负", "让球胜平负": "让球",
                "比分": "比分", "总进球": "总进球",
                "半全场": "半全场", "混合过关": "混合",
            }
            play_type = play_type_map[play_mode]

            # --- 官网风格：每场一行，行内胜/平/负按钮 ---
            st.markdown("---")
            st.caption("👆 每行点击一个结果（胜/平/负），选中后自动加入串关选单")

            # 初始化选单：{match_id: {"pick": str, "play_type": str, "odds": float}}
            cart_key = "parlay_cart"
            if cart_key not in st.session_state:
                st.session_state[cart_key] = {}

            selected_rows = []  # 收集已选场次供后面计算
            for idx, r in enumerate(pool):
                code = r.get("场次编号", "")
                league = r.get("联赛", "")
                vs = r.get("对阵", "")
                handicap = r.get("让球", "") or "0"

                # --- 该行可选的玩法 + 三个按钮 ---
                row_items = []  # [(玩法名, 选单key前缀, 赔率dict)]

                if play_type in ("胜平负", "混合"):
                    row_items.append((
                        "胜平负", "had",
                        r.get("真实赔率", {}) or {},
                    ))
                if play_type in ("让球", "混合"):
                    row_items.append((
                        f"让球({handicap})", "handicap",
                        r.get("真实赔率_让球", {}) or {},
                    ))

                if not row_items:
                    # 比分/总进球/半全场 — 展示模型推荐 + 赔率
                    pick_map = {
                        "比分": r.get("比分推荐", ""),
                        "总进球": r.get("总进球推荐", ""),
                        "半全场": r.get("半全场推荐", ""),
                    }
                    odds_key_map = {
                        "比分": "真实赔率_比分",
                        "总进球": "真实赔率_总进球",
                        "半全场": "真实赔率_半全场",
                    }
                    pick_v = pick_map.get(play_type, "")
                    odds_v = (r.get(odds_key_map.get(play_type, ""), {}) or {}).get(pick_v, "")
                    try:
                        odds_v = f"{float(odds_v):.2f}"
                    except Exception:
                        odds_v = "—"

                    with st.container(border=True):
                        st.markdown(f"**{code}** {vs}")
                        st.caption(f"{league} · {play_type}推荐: **{pick_v}** @ {odds_v}")

                        # 选/不选 开关
                        cart_match_key = f"{code}_{play_type}"
                        is_selected = st.session_state[cart_key].get(cart_match_key, {}).get("pick")
                        if st.toggle(
                            f"✅ 加入串关",
                            value=bool(is_selected),
                            key=f"toggle_{cart_match_key}",
                        ):
                            st.session_state[cart_key][cart_match_key] = {
                                "pick": pick_v,
                                "play_type": play_type,
                                "odds": float(odds_v) if odds_v not in ("", "—") else 0,
                                "row": r,
                            }
                            selected_rows.append(st.session_state[cart_key][cart_match_key])
                        elif cart_match_key in st.session_state[cart_key]:
                            del st.session_state[cart_key][cart_match_key]
                    continue

                # --- 胜平负 / 让球 按钮行 ---
                with st.container(border=True):
                    header_col, _ = st.columns([3, 1])
                    with header_col:
                        st.markdown(
                            f"<div style='font-size:13px;'>"
                            f"<b style='color:#FF4B4B;'>{code}</b> "
                            f"<span style='color:#9aa0b4;'>{league}</span> "
                            f"<b>{vs}</b> "
                            f"<span style='color:#7a8094; font-size:11px;'>[让球 {handicap}]</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                    for play_label, play_prefix, odds_dict in row_items:
                        picks = ["胜", "平", "负"]
                        # 让球玩法按钮标注"让胜/让平/让负"
                        btns_label = {
                            "胜平负": ["胜", "平", "负"],
                            f"让球({handicap})": [f"让胜({handicap})", "让平", f"让负"],
                        }[play_label]

                        cart_match_key = f"{code}_{play_prefix}"
                        current_pick = st.session_state[cart_key].get(cart_match_key, {}).get("pick")

                        # 3 个按钮横排
                        b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
                        b_clicked = None
                        for i, (col, pick, bl) in enumerate(zip([b1, b2, b3], picks, btns_label)):
                            odds_v = odds_dict.get(pick, "")
                            try:
                                odds_str = f"{float(odds_v):.2f}" if odds_v else "--"
                            except Exception:
                                odds_str = "--"

                            is_active = (current_pick == pick)
                            label = f"**{pick}** {odds_str}" if is_active else f"{pick} {odds_str}"
                            btn_type = "primary" if is_active else "secondary"
                            if col.button(
                                label,
                                key=f"btn_{cart_match_key}_{pick}",
                                type=btn_type,
                                use_container_width=True,
                            ):
                                b_clicked = pick

                        # 处理点击（选中/取消）
                        if b_clicked:
                            odds_v = odds_dict.get(b_clicked, "")
                            try:
                                odds_f = float(odds_v) if odds_v else 0
                            except Exception:
                                odds_f = 0

                            if current_pick == b_clicked:
                                # 取消选中
                                if cart_match_key in st.session_state[cart_key]:
                                    del st.session_state[cart_key][cart_match_key]
                            else:
                                st.session_state[cart_key][cart_match_key] = {
                                    "pick": b_clicked,
                                    "play_type": play_label,
                                    "odds": odds_f,
                                    "row": r,
                                }

                    # 汇总到 selected_rows（当前所有选中的）
                    for _k, _v in st.session_state[cart_key].items():
                        if _k.startswith(f"{code}_"):
                            selected_rows.append(_v)

            # 已选列表去重（可能一个 row 两个玩法都选了）
            seen_codes = set()
            selected_dedup = []
            for item in selected_rows:
                row_ref = item.get("row", {})
                c = row_ref.get("场次编号", "")
                if c and c not in seen_codes:
                    seen_codes.add(c)
                    selected_dedup.append(item)
            selected_rows = selected_dedup

            # --- 串数 ---
            st.divider()
            col_n, col_stk = st.columns(2)
            with col_n:
                max_n_options = [n for n in [2, 3, 4, 5]
                                 if n <= max(len(selected_rows), 2)]
                default_idx = min(1, len(max_n_options) - 1)
                parlay_n = st.selectbox(
                    "串数",
                    max_n_options or [2],
                    index=default_idx,
                    format_func=lambda x: f"{x}串1",
                    key="parlay_n",
                )
            with col_stk:
                stake = st.number_input(
                    "投入（元）", min_value=2, max_value=10000,
                    value=10, step=1, key="parlay_stake",
                )

            # --- 选单实时显示 ---
            cart_items = list(st.session_state[cart_key].values())
            if not cart_items:
                st.info("👈 点上面的胜/平/负按钮开始选择")
            else:
                # 组合：取前 parlay_n 场
                combo = cart_items[:parlay_n] if len(cart_items) >= parlay_n else cart_items
                total_odds = 1.0
                for it in combo:
                    try:
                        if it.get("odds", 0) > 0:
                            total_odds *= float(it["odds"])
                    except Exception:
                        pass

                st.markdown("#### 📝 选单")
                for it in combo:
                    row_r = it.get("row", {})
                    c = row_r.get("场次编号", "")
                    vs = row_r.get("对阵", "")
                    ptype = it.get("play_type", "")
                    pick = it.get("pick", "")
                    odds_f = it.get("odds", 0)
                    odds_s = f"{odds_f:.2f}" if odds_f else "--"
                    st.markdown(
                        f"- **{c}** {vs} → "
                        f"<span style='color:#FF4B4B;font-weight:700;'>"
                        f"{pick}</span> @ {odds_s} "
                        f"<span style='color:#7a8094;'>[{ptype}]</span>",
                        unsafe_allow_html=True,
                    )

                c1, c2, c3 = st.columns(3)
                c1.metric("选中场次", f"{len(combo)} / {parlay_n}串1")
                c2.metric("总赔率", f"{total_odds:.2f}")
                c3.metric("预期收益", f"{total_odds * stake:.2f} 元")

                # 生成按钮
                if len(combo) >= parlay_n:
                    if st.button(
                        f"📋 生成 {parlay_n}串1 投注单",
                        key="gen_parlay",
                        type="primary",
                        use_container_width=True,
                    ):
                        slip = f"⚽ {len(combo)}串1 串关推荐\n"
                        slip += "─" * 30 + "\n"
                        for it in combo:
                            row_r = it.get("row", {})
                            c = row_r.get("场次编号", "")
                            vs = row_r.get("对阵", "")
                            pick = it.get("pick", "")
                            odds_s = f"{it.get('odds', 0):.2f}" if it.get("odds") else "--"
                            slip += f"{c} {vs} → {pick} @ {odds_s}\n"
                        slip += "─" * 30 + "\n"
                        slip += f"总赔率：{total_odds:.2f}\n"
                        slip += f"投入：{stake} 元\n"
                        slip += f"预期收益：{total_odds * stake:.2f} 元\n"

                        from modules.copy_widget import copy_block
                        copy_block(
                            slip, label="📋 复制串关投注单",
                            height=340, key="parlay_result",
                        )
                else:
                    st.warning(f"还差 {parlay_n - len(combo)} 场才能生成 {parlay_n}串1")

            st.divider()

            # --- 单场投注单 ---
            st.markdown("### 📋 单场投注单")
            from modules.betting_slip import generate_slip
            watch_teams_t = st.session_state.get("watch_teams", [])
            watch_leagues_t = st.session_state.get("watch_leagues", [])
            only_cold_t = st.session_state.get("only_cold", False)
            filtered_t = _f(results_p, teams=set(watch_teams_t),
                            leagues=set(watch_leagues_t), only_cold=only_cold_t)
            slip_text = generate_slip(filtered_t, mode="single")

            from modules.copy_widget import copy_block
            copy_block(slip_text, label="📋 复制单场投注单",
                       height=380, key="parlay_single_slip")

            st.divider()

            # --- Markdown + CSV 报告 ---
            st.markdown("### 📄 报告下载")
            import glob, os as _os
            md_files = sorted(glob.glob("output/recommend_*.md"),
                              key=_os.path.getmtime, reverse=True)
            csv_files_p = sorted(glob.glob("output/recommend_*.csv"),
                                 key=_os.path.getmtime, reverse=True)

            col_md, col_csv = st.columns(2)
            with col_md:
                st.caption("📋 Markdown 报告")
                if md_files:
                    with open(md_files[0], encoding="utf-8") as f:
                        md_text = f.read()
                    copy_block(md_text, label="📋 复制 Markdown",
                               height=500, key="parlay_md")
                else:
                    st.info("无 Markdown 文件")

            with col_csv:
                st.caption("📋 CSV 数据")
                if csv_files_p:
                    with open(csv_files_p[0], encoding="utf-8-sig") as f:
                        csv_text = f.read()
                    copy_block(csv_text, label="📋 复制 CSV",
                               height=500, key="parlay_csv")
                else:
                    st.info("无 CSV 文件")

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

    # （底部串关 + MD/CSV 已迁移到 🔗串关 Tab）