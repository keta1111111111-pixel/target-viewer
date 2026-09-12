"""
TARGET 指数＆展開予測ビューア (Streamlit版)
------------------------------------------------
スマホのブラウザからも閲覧できるWeb版。
Streamlit Community Cloud へのデプロイを想定。
"""

import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="TARGET 指数＆展開予測ビューア", page_icon="🏇", layout="wide")

TARGET_INDICES = ['F指数', 'S指数', 'FU2']

RANK_COLORS = {
    1: ("#ffff00", "#000000"),  # 1位: 黄
    2: ("#66ccff", "#000000"),  # 2位: 水
    3: ("#66ff66", "#000000"),  # 3位: 緑
}

ROW_TAG_COLORS = {
    'recommend': "#E2EFDA",
    'nige': "#FFE6CC",
    'senkou': "#FFF2CC",
}

CATEGORY_COLORS = {
    "逃げ": "#b30000", "先行": "#cc7a00", "先差": "#338066",
    "差し": "#1a53ff", "追込": "#4d2600", "不明": "#4d4d4d",
}
CATEGORY_ORDER = ["逃げ", "先行", "先差", "差し", "追込", "不明"]

SINGLE_PAST_RACE_COLS = [
    '前走開催', '前着順', '前脚質', '前3F順', '前頭数',
    '前通過1', '前通過2', '前通過3', '前通過4', '前走2着以内頭数', '前走通過順',
]
NUMBERED_PAST_RACE_RE = re.compile(r'^前(\d+)走(.+)$')


def safe_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ==========================================================
# パスワード保護（Streamlit Cloudのsecretsに APP_PASSWORD を設定した場合のみ有効）
# ==========================================================
def check_password() -> bool:
    required_password = st.secrets.get("APP_PASSWORD", None)
    if not required_password:
        return True  # secrets未設定時はローカル検証用にスキップ

    if st.session_state.get("password_ok"):
        return True

    st.title("🔒 ログイン")
    pw = st.text_input("パスワード", type="password")
    if st.button("入る"):
        if pw == required_password:
            st.session_state["password_ok"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    return False


# ==========================================================
# データ処理ロジック（既存アプリから移植・フレームワーク非依存）
# ==========================================================
def calc_position_and_patterns(df: pd.DataFrame) -> pd.DataFrame:
    def format_pass(row):
        passes = []
        for p_col in ['前通過1', '前通過2', '前通過3', '前通過4']:
            p = row.get(p_col)
            if pd.notna(p) and str(p).strip() not in ['', 'nan', 'NaN']:
                try:
                    passes.append(str(int(float(p))))
                except Exception:
                    pass
        return "-".join(passes) if passes else "-"

    df['前走通過順'] = df.apply(format_pass, axis=1)

    def calc_front_score(row):
        style = str(row.get('前脚質', '')).strip()
        if style == 'nan':
            style = ''
        total_h = safe_float(row.get('前頭数', 16), 16.0)
        total_h = 16.0 if total_h is None or total_h <= 0 else total_h

        p_val = None
        for p_col in ['前通過4', '前通過3', '前通過2', '前通過1']:
            p = row.get(p_col)
            if pd.notna(p) and str(p).strip() not in ['', 'nan', 'NaN']:
                pv = safe_float(p)
                if pv is not None:
                    p_val = pv
                    break

        if not style and p_val is None:
            return -1.0

        style_score = 50.0
        if '逃' in style:
            style_score = 90.0
        elif '先' in style:
            style_score = 70.0
        elif '中' in style or '差' in style:
            style_score = 45.0
        elif '後' in style or '追' in style:
            style_score = 25.0

        if p_val is not None:
            rel_pos = max(0.0, min(1.0, 1.0 - (p_val - 1) / max(1.0, total_h - 1.0)))
            pos_score = rel_pos * 100.0
            return round(style_score * 0.4 + pos_score * 0.6, 1)
        return round(style_score, 1)

    df['先行スコア'] = df.apply(calc_front_score, axis=1)
    valid_scores = df['先行スコア'][df['先行スコア'] >= 0]
    if not valid_scores.empty:
        df['先行順位'] = df['先行スコア'].rank(ascending=False, method='min')
    else:
        df['先行順位'] = 99

    total_in_race = len(df)

    def predict_pos(row):
        score = row['先行スコア']
        if score < 0:
            return "不明"
        rank = row['先行順位']
        if rank == 1:
            return "逃げ"
        elif rank <= max(2, int(total_in_race * 0.25)):
            return "先行"
        elif rank <= max(3, int(total_in_race * 0.5)):
            return "先差"
        elif rank <= max(4, int(total_in_race * 0.75)):
            return "差し"
        else:
            return "追込"

    df['予想展開'] = df.apply(predict_pos, axis=1)

    def calc_3f_score(row):
        f3 = safe_float(row.get('前3F順', 0))
        total_h = safe_float(row.get('前頭数', 16))
        if f3 and total_h and f3 > 0 and total_h > 0:
            rel = max(0.0, min(1.0, 1.0 - (f3 - 1) / max(1.0, total_h - 1.0)))
            return str(round(rel * 100.0, 1))
        return "-"

    df['末脚スコア'] = df.apply(calc_3f_score, axis=1)

    def check_recommend(row):
        odds = safe_float(row.get('単オッズ', 0), 0.0)
        pos = row.get('予想展開', '')
        f3_rank = safe_float(row.get('前3F順', 99), 99.0)

        if pos in ['逃げ', '先行'] and 4.0 <= odds <= 30.0:
            return "先行妙味"
        if f3_rank <= 2 and 5.0 <= odds <= 35.0:
            return "末脚妙味"
        return ""

    df['推奨'] = df.apply(check_recommend, axis=1)
    return df


def safe_rank(series):
    return pd.to_numeric(series, errors='coerce').rank(ascending=False, method='min')


def group_previous_race_columns(columns):
    numbered = {}
    for col in columns:
        m = NUMBERED_PAST_RACE_RE.match(col)
        if m:
            race_no, label = m.group(1), m.group(2)
            numbered.setdefault(race_no, []).append((label, col))

    if numbered:
        sections = []
        for race_no in sorted(numbered.keys(), key=int):
            sections.append((f"前{race_no}走", numbered[race_no]))
        return sections

    single_cols = [(c, c) for c in SINGLE_PAST_RACE_COLS if c in columns]
    if single_cols:
        return [("直近走", single_cols)]
    return []


# ==========================================================
# データ読み込み（アップロードファイルから）
# ==========================================================
@st.cache_data(show_spinner=False)
def load_main_csv(file_bytes) -> pd.DataFrame:
    df = pd.read_csv(file_bytes, dtype=str, encoding="cp932")
    df = calc_position_and_patterns(df)
    return df


def merge_index_csv(df: pd.DataFrame, idx_name: str, file_bytes) -> pd.DataFrame:
    df_idx = pd.read_csv(file_bytes, header=None, sep=r'[\t,]', engine='python',
                          dtype=str, encoding="cp932")
    df_idx = df_idx.iloc[:, [0, 1]].dropna()
    df_idx.columns = ['ID', idx_name]
    df_idx['馬番'] = df_idx['ID'].apply(lambda x: str(int(str(x)[-2:])) if len(str(x)) >= 18 else "")
    df_idx = df_idx[['馬番', idx_name]].drop_duplicates(subset=['馬番'])

    if idx_name in df.columns:
        df = df.drop(columns=[idx_name])
    return pd.merge(df, df_idx, on='馬番', how='left')


# ==========================================================
# 表示（出馬表：スタイル付きデータフレーム＋行タップで詳細）
# ==========================================================
def build_display_dataframe(df: pd.DataFrame, display_columns):
    return df[display_columns].reset_index(drop=True)


def style_dataframe(display_df: pd.DataFrame, full_df: pd.DataFrame):
    full_reset = full_df.reset_index(drop=True)

    def row_style(row):
        idx = row.name
        rec = full_reset.loc[idx, '推奨'] if '推奨' in full_reset.columns else ''
        pos = full_reset.loc[idx, '予想展開'] if '予想展開' in full_reset.columns else ''
        tag = None
        if rec in ['先行妙味', '末脚妙味']:
            tag = 'recommend'
        elif pos == '逃げ':
            tag = 'nige'
        elif pos == '先行':
            tag = 'senkou'
        if tag:
            return [f'background-color:{ROW_TAG_COLORS[tag]};'] * len(row)
        return [''] * len(row)

    styler = display_df.style.apply(row_style, axis=1)

    for col in TARGET_INDICES:
        if col not in display_df.columns:
            continue
        rank_col = f"{col}_rank"
        if rank_col not in full_reset.columns:
            continue

        def highlight_index(s, rank_col=rank_col):
            styles = []
            for i in s.index:
                r = full_reset.loc[i, rank_col]
                if pd.notna(r) and int(r) in RANK_COLORS:
                    bg, fg = RANK_COLORS[int(r)]
                    styles.append(f'background-color:{bg}; color:{fg}; font-weight:bold;')
                else:
                    styles.append('')
            return styles

        styler = styler.apply(highlight_index, subset=[col])

    return styler


def render_horse_detail(row: pd.Series):
    st.markdown(f"#### {row.get('馬番', '')}番 {row.get('馬名', '')}")
    sections = group_previous_race_columns(row.index.tolist())
    if not sections:
        st.info("過去走のデータが見つかりませんでした。")
        return
    for title, items in sections:
        with st.expander(title, expanded=True):
            for label, col in items:
                val = row.get(col, '-')
                if pd.isna(val) or str(val).strip() == '':
                    val = '-'
                st.markdown(f"**{label}**: {val}")


# ==========================================================
# 展開予想図（カード表示・スマホ幅対応）
# ==========================================================
def render_tenkai_view(df: pd.DataFrame):
    st.markdown(
        "<p style='color:#aaaaaa;font-size:13px;'>"
        "逃 → 先 → 先差 → 差 → 追　/　同じ段では左（上）ほど前寄り</p>",
        unsafe_allow_html=True,
    )

    df_sorted = df.sort_values(by='先行スコア', ascending=False)

    for cat in CATEGORY_ORDER:
        cat_color = CATEGORY_COLORS[cat]
        cat_horses = df_sorted[df_sorted['予想展開'] == cat]

        st.markdown(
            f"<div style='background-color:{cat_color};color:white;font-weight:bold;"
            f"padding:6px 10px;border-radius:4px;margin-top:10px;'>{cat}"
            f"（{len(cat_horses)}頭）</div>",
            unsafe_allow_html=True,
        )

        if cat_horses.empty:
            st.markdown(
                "<p style='color:gray;padding:6px 10px;'>該当馬なし</p>",
                unsafe_allow_html=True,
            )
            continue

        cards_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;padding:8px 0;'>"
        for _, row in cat_horses.iterrows():
            pass_str = row.get('前走通過順', '-')
            badges_html = ""
            for idx_name in TARGET_INDICES:
                val = row.get(idx_name)
                rank = row.get(f"{idx_name}_rank")
                if pd.isna(val) or val == "":
                    badges_html += (
                        "<span style='background:#111;color:white;border:1px solid #444;"
                        "border-radius:3px;padding:2px 5px;font-size:11px;margin-right:2px;'>-</span>"
                    )
                    continue
                r = int(rank) if pd.notna(rank) else 99
                bg_c, fg_c = RANK_COLORS.get(r, ("#111111", "white"))
                name_short = idx_name.replace("指数", "")[:3]
                label = f"{name_short} {val}" + (f" ({r}位)" if r <= 3 else "")
                badges_html += (
                    f"<span style='background:{bg_c};color:{fg_c};border:1px solid #444;"
                    f"border-radius:3px;padding:2px 5px;font-size:11px;margin-right:2px;'>{label}</span>"
                )

            cards_html += (
                "<div style='background:#2a1a1a;border:1px solid #555;border-radius:4px;"
                "min-width:160px;max-width:200px;'>"
                f"<div style='background:{cat_color};color:white;font-weight:bold;"
                f"font-size:12px;padding:3px 6px;'>{row.get('馬番', '')} {row.get('馬名', '')}</div>"
                f"<div style='color:lightgray;font-size:11px;padding:3px 6px;'>前走: {pass_str}</div>"
                f"<div style='padding:3px 6px 6px;'>{badges_html}</div>"
                "</div>"
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)


# ==========================================================
# メイン
# ==========================================================
def main():
    if not check_password():
        st.stop()

    st.title("🏇 TARGET 指数＆展開予測ビューア")

    with st.sidebar:
        st.header("データ読み込み")
        main_file = st.file_uploader("出馬表CSV", type=["csv"])

        st.markdown("---")
        st.caption("追加指数ファイル（F指数・S指数・FU2など／任意）")
        num_idx = st.number_input("追加する指数の数", min_value=0, max_value=10, value=0, step=1)
        idx_uploads = []
        for i in range(int(num_idx)):
            c1, c2 = st.columns([1, 2])
            name = c1.text_input(f"指数名{i+1}", key=f"idxname{i}", placeholder="例: F指数")
            f = c2.file_uploader(f"ファイル{i+1}", type=["csv", "txt"], key=f"idxfile{i}")
            if name and f:
                idx_uploads.append((name, f))

    if main_file is None:
        st.info("サイドバーから出馬表CSVをアップロードしてください。")
        return

    df = load_main_csv(main_file)

    for name, f in idx_uploads:
        df = merge_index_csv(df, name, f)

    for idx_col in TARGET_INDICES:
        if idx_col in df.columns:
            df[f"{idx_col}_rank"] = safe_rank(df[idx_col])

    all_cols = [c for c in df.columns if not c.endswith('_rank') and c != '先行順位']
    default_cols = [c for c in [
        '馬番', '枠番', '馬名', '騎手', '人気', '単オッズ', '推奨',
        '予想展開', '先行スコア', '前走通過順', 'F指数', 'S指数', 'FU2',
    ] if c in all_cols]

    tab_table, tab_tenkai = st.tabs(["📋 出馬表", "🗺️ 展開予想図"])

    with tab_table:
        display_columns = st.multiselect("表示する項目", options=all_cols, default=default_cols)
        if not display_columns:
            st.warning("表示する項目を1つ以上選んでください。")
        else:
            display_df = build_display_dataframe(df, display_columns)
            styler = style_dataframe(display_df, df)

            event = st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
            )

            selected_rows = event.selection.rows if event and event.selection else []
            if selected_rows:
                st.markdown("---")
                st.subheader("馬詳細")
                full_row = df.reset_index(drop=True).iloc[selected_rows[0]]
                render_horse_detail(full_row)
            else:
                st.caption("行をタップすると、その馬の前走詳細が表示されます。")

    with tab_tenkai:
        render_tenkai_view(df)


if __name__ == "__main__":
    main()
