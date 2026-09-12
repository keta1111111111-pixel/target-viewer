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

# JRA公式の枠番カラー（1〜8枠）
WAKU_COLORS = {
    1: ("#ffffff", "#000000"),  # 白
    2: ("#000000", "#ffffff"),  # 黒
    3: ("#e2231a", "#ffffff"),  # 赤
    4: ("#0068b7", "#ffffff"),  # 青
    5: ("#ffe200", "#000000"),  # 黄
    6: ("#009944", "#ffffff"),  # 緑
    7: ("#f39800", "#ffffff"),  # 橙
    8: ("#e4007f", "#ffffff"),  # 桃
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
    '前走開催', '前着順', '前脚質', '前走決め手', '前3F順', '前頭数',
    '前通過1', '前通過2', '前通過3', '前通過4', '前走2着以内頭数', '前走通過順',
]
NUMBERED_PAST_RACE_RE = re.compile(r'^前(\d+)走(.+)$')

# 脚質（走り方）を表す列は、CSVの出力設定によって列名が異なることがあるため、
# 複数の候補から最初に値が入っているものを使う。
STYLE_COLS = ['前脚質', '前走決め手']

def first_nonempty(row, cols):
    for c in cols:
        v = row.get(c)
        if pd.notna(v) and str(v).strip() not in ('', 'nan', 'NaN'):
            return v
    return None

# レースを一意に識別するための列（出馬表CSVの「場所」「Ｒ」列）
RACE_KEY_COLS = ['場所', 'Ｒ']
RACE_KEY_COL = '__race_key__'

# JRA場所コード（指数ファイルのID中の場所コードをレース名に変換するために使用）
VENUE_CODE_MAP = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

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
# レース単位のグルーピング
# ==========================================================
def has_race_columns(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in RACE_KEY_COLS)

def get_race_key(df: pd.DataFrame) -> pd.Series:
    """出馬表1行ごとに、どのレースに属するかを表すキーを返す。
    「場所」「Ｒ」列が無いCSV（旧形式）の場合は全行を1つのレース扱いにする。"""
    if has_race_columns(df):
        return df['場所'].astype(str) + '_' + df['Ｒ'].astype(str)
    return pd.Series(['__all__'] * len(df), index=df.index)

def build_race_options(df: pd.DataFrame):
    """各レースのメタ情報（キー・場所・Ｒ・レース名・発走時刻など）を
    発走時刻順に並べたリストで返す。レース列が無ければ None。"""
    if not has_race_columns(df) or RACE_KEY_COL not in df.columns:
        return None

    rows = []
    for key, g in df.groupby(RACE_KEY_COL, sort=False):
        first = g.iloc[0]
        rows.append({
            'key': key,
            '場所': first.get('場所', ''),
            'Ｒ': first.get('Ｒ', ''),
            'レース名': first.get('レース名', ''),
            '発走時刻': first.get('発走時刻', ''),
            '芝ダ': first.get('芝ダ', ''),
            '距離': first.get('距離', ''),
            '頭数': len(g),
        })

    rows.sort(key=lambda r: str(r['発走時刻']))
    return rows
def render_race_selector(race_options):
    """場所ごとにグループ化した「1R」「2R」…ボタンでレースを選ばせ、
    選択中のレースのメタ情報（dict）を返す。race_options が空/Noneなら None。"""
    if not race_options:
        return None

    by_key = {r['key']: r for r in race_options}

    if st.session_state.get('selected_race_key') not in by_key:
        st.session_state['selected_race_key'] = race_options[0]['key']

    venues = []
    races_by_venue = {}
    for r in race_options:
        venue = r['場所']
        if venue not in races_by_venue:
            races_by_venue[venue] = []
            venues.append(venue)
        races_by_venue[venue].append(r)

    cols_per_row = 6
    for venue in venues:
        st.markdown(
            f"<div style='border-left:4px solid #2e7d32;padding-left:8px;"
            f"font-weight:bold;font-size:15px;margin:12px 0 6px;'>{venue}</div>",
            unsafe_allow_html=True,
        )
        races = sorted(races_by_venue[venue], key=lambda r: safe_float(r['Ｒ'], 0) or 0)
        for start in range(0, len(races), cols_per_row):
            chunk = races[start:start + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, r in zip(cols, chunk):
                is_selected = r['key'] == st.session_state['selected_race_key']
                if col.button(
                    f"{r['Ｒ']}R",
                    key=f"racebtn_{r['key']}",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ):
                    st.session_state['selected_race_key'] = r['key']

    return by_key[st.session_state['selected_race_key']]

def render_race_info(race_meta, df_race: pd.DataFrame):
    """選択中レースの発走時刻・レース名・距離・頭数などをまとめて表示する。"""
    if race_meta is None:
        return

    parts = []
    if race_meta.get('発走時刻'):
        parts.append(str(race_meta['発走時刻']))
    if race_meta.get('場所') or race_meta.get('Ｒ'):
        parts.append(f"{race_meta.get('場所', '')}{race_meta.get('Ｒ', '')}R")
    if race_meta.get('レース名'):
        parts.append(str(race_meta['レース名']))
    surface = race_meta.get('芝ダ', '') or ''
    distance = race_meta.get('距離', '') or ''
    if surface or distance:
        parts.append(f"{surface}{distance}m".strip())
    parts.append(f"{len(df_race)}頭")

    st.markdown(
        "<div style='background:#eef6ee;border:1px solid #cfe8cf;border-radius:8px;"
        "padding:10px 16px;font-size:17px;font-weight:bold;margin:4px 0 16px;'>"
        + "　".join(parts) + "</div>",
        unsafe_allow_html=True,
    )
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
        style = str(first_nonempty(row, STYLE_COLS) or '').strip()
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

    # 先行順位・予想展開は「同じレースの馬同士」で比較しないと意味がないため、
    # レース（場所＋Ｒ）ごとにグループ化して計算する。
    df[RACE_KEY_COL] = get_race_key(df)
    df['先行順位'] = df.groupby(RACE_KEY_COL)['先行スコア'].rank(ascending=False, method='min')
    race_size = df.groupby(RACE_KEY_COL)[RACE_KEY_COL].transform('size')

    def predict_pos(row, race_size):
        score = row['先行スコア']
        if score < 0:
            return "不明"
        rank = row['先行順位']
        total_in_race = race_size[row.name]
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

    df['予想展開'] = df.apply(predict_pos, axis=1, race_size=race_size)

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

def parse_index_id(id_str) -> tuple:
    """指数ファイルのID（日付8桁＋場所コード2桁＋回2桁＋日2桁＋Ｒ2桁＋馬番2桁の18桁）から
    (場所名, Ｒ, 馬番) を取り出す。形式が合わない場合はすべて空文字を返す。"""
    s = str(id_str).strip()
    if len(s) < 18:
        return "", "", ""

    venue_code = s[8:10]
    race_no_raw = s[14:16]
    horse_no_raw = s[16:18]

    venue_name = VENUE_CODE_MAP.get(venue_code, "")
    try:
        race_no = str(int(race_no_raw))
    except ValueError:
        race_no = ""
    try:
        horse_no = str(int(horse_no_raw))
    except ValueError:
        horse_no = ""

    return venue_name, race_no, horse_no

def merge_index_csv(df: pd.DataFrame, idx_name: str, file_bytes) -> pd.DataFrame:
    df_idx = pd.read_csv(file_bytes, header=None, sep=r'[\t,]', engine='python',
                          dtype=str, encoding="cp932")
    df_idx = df_idx.iloc[:, [0, 1]].dropna()
    df_idx.columns = ['ID', idx_name]

    parsed = df_idx['ID'].apply(parse_index_id)
    df_idx['場所'] = parsed.apply(lambda t: t[0])
    df_idx['Ｒ'] = parsed.apply(lambda t: t[1])
    df_idx['馬番'] = parsed.apply(lambda t: t[2])

    # 出馬表側にレース情報（場所・Ｒ）があれば「場所＋Ｒ＋馬番」で紐付ける。
    # 馬番は1日の中でレースごとに1〜16番が重複するため、馬番だけでの結合は
    # 複数レースが混在するCSVでは別レースの馬に値を取り違えてしまう。
    if has_race_columns(df):
        merge_keys = ['場所', 'Ｒ', '馬番']
        df_idx = df_idx[df_idx['場所'] != ""]
    else:
        merge_keys = ['馬番']

    df_idx = df_idx[df_idx['馬番'] != ""]
    df_idx = df_idx[merge_keys + [idx_name]].drop_duplicates(subset=merge_keys)

    if idx_name in df.columns:
        df = df.drop(columns=[idx_name])
    return pd.merge(df, df_idx, on=merge_keys, how='left')
# ==========================================================
# 表示（出馬表：スタイル付きデータフレーム＋行タップで詳細）
# ==========================================================
def build_display_dataframe(df: pd.DataFrame, display_columns):
    out = df[display_columns].reset_index(drop=True)
    # CSVはdtype=strで読み込んでいるため、そのままだと表の列見出しクリックでの
    # 並べ替えが文字列比較になり「10」が「2」より前に来るなど直感に反する結果になる。
    # 大半の値が数値に変換できる列は、表示用に数値型へ変換しておく。
    for col in out.columns:
        converted = pd.to_numeric(out[col], errors='coerce')
        non_empty = out[col].notna() & (out[col].astype(str).str.strip() != '')
        if non_empty.sum() > 0 and converted.notna().sum() >= non_empty.sum() * 0.9:
            if (converted.dropna() % 1 == 0).all():
                out[col] = converted.astype('Int64')
            else:
                out[col] = converted
    return out

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

    if '枠番' in display_df.columns:
        def highlight_waku(s):
            styles = []
            for v in s:
                wk = safe_float(v)
                wk = int(wk) if wk is not None else None
                if wk in WAKU_COLORS:
                    bg, fg = WAKU_COLORS[wk]
                    styles.append(f'background-color:{bg}; color:{fg}; font-weight:bold; text-align:center;')
                else:
                    styles.append('')
            return styles
        styler = styler.apply(highlight_waku, subset=['枠番'])

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

@st.dialog("馬詳細")
def show_horse_detail_dialog(row: pd.Series):
    """出馬表の行をクリックした際に、スクロール不要でその場にポップアップ表示する。"""
    render_horse_detail(row)
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
                label = f"{name_short} {val}"
                badges_html += (
                    f"<span style='background:{bg_c};color:{fg_c};border:1px solid #444;"
                    f"border-radius:3px;padding:2px 5px;font-size:11px;margin-right:2px;'>{label}</span>"
                )

            waku_val = safe_float(row.get('枠番'))
            waku_val = int(waku_val) if waku_val is not None else None
            if waku_val in WAKU_COLORS:
                wbg, wfg = WAKU_COLORS[waku_val]
                waku_badge = (
                    f"<span style='background:{wbg};color:{wfg};border:1px solid #444;"
                    f"border-radius:3px;padding:1px 5px;font-size:11px;margin-right:4px;'>{waku_val}</span>"
                )
            else:
                waku_badge = ""

            cards_html += (
                "<div style='background:#2a1a1a;border:1px solid #555;border-radius:4px;"
                "min-width:160px;max-width:200px;'>"
                f"<div style='background:{cat_color};color:white;font-weight:bold;"
                f"font-size:12px;padding:3px 6px;'>{waku_badge}{row.get('馬番', '')} {row.get('馬名', '')}</div>"
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

    # st.cache_data が古いバージョンの結果を保持している場合（デプロイ直後など）に備えて、
    # レースキー列が無ければここで補っておく（自己修復）。
    if RACE_KEY_COL not in df.columns:
        df[RACE_KEY_COL] = get_race_key(df)

    for name, f in idx_uploads:
        df = merge_index_csv(df, name, f)

    for idx_col in TARGET_INDICES:
        if idx_col in df.columns:
            df[f"{idx_col}_rank"] = df.groupby(RACE_KEY_COL)[idx_col].transform(safe_rank)

    # ---- レース選択 ----
    race_options = build_race_options(df)
    selected_race = render_race_selector(race_options)
    if selected_race is not None:
        df_race = df[df[RACE_KEY_COL] == selected_race['key']].reset_index(drop=True)
    else:
        df_race = df
    render_race_info(selected_race, df_race)

    all_cols = [c for c in df_race.columns if not c.endswith('_rank') and c not in ('先行順位', RACE_KEY_COL)]
    default_cols = [c for c in [
        '枠番', '馬番', '馬名', '騎手', '人気', '単オッズ', '推奨',
        '予想展開', '前走通過順', 'F指数', 'S指数', 'FU2',
    ] if c in all_cols]

    tab_table, tab_tenkai = st.tabs(["📋 出馬表", "🗺️ 展開予想図"])

    with tab_table:
        with st.popover("⚙️ 表示する項目"):
            display_columns = st.multiselect("表示する項目", options=all_cols, default=default_cols)
        if not display_columns:
            st.warning("表示する項目を1つ以上選んでください。")
        else:
            display_df = build_display_dataframe(df_race, display_columns)
            styler = style_dataframe(display_df, df_race)

            event = st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
            )

            selected_rows = event.selection.rows if event and event.selection else []
            if selected_rows:
                full_row = df_race.reset_index(drop=True).iloc[selected_rows[0]]
                show_horse_detail_dialog(full_row)
            else:
                st.caption("行をクリックすると、その馬の前走詳細がポップアップで表示されます。")

    with tab_tenkai:
        render_tenkai_view(df_race)

if __name__ == "__main__":
    main()
