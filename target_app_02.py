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

# TARGET本体の指数順位ハイライト（黄・水・緑）になるべく近づけた、
# 純色に近い彩度の高い配色。
RANK_COLORS = {
    1: ("#ffff00", "#000000"),  # 1位: 黄
    2: ("#00ffff", "#000000"),  # 2位: 水
    3: ("#00ff00", "#000000"),  # 3位: 緑
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

# 出馬表で「信頼できる先行馬」（展開予想図の🔥アイコンと同じ判定基準）の
# 行全体をハイライトする背景色。脚質安定性が「安定」なら濃い方、
# 「やや不安定」なら薄い方を使い、強弱を付ける。
RELIABLE_ROW_COLOR_STRONG = "#A9D18E"  # 安定
RELIABLE_ROW_COLOR_WEAK = "#E2EFDA"    # やや不安定

CATEGORY_COLORS = {
    "逃げ": "#b30000", "先行": "#cc7a00", "先差": "#338066",
    "差し": "#1a53ff", "追込": "#4d2600", "不明": "#4d4d4d",
}
CATEGORY_ORDER = ["逃げ", "先行", "先差", "差し", "追込", "不明"]

SINGLE_PAST_RACE_COLS = [
    '前走開催', '前着順', '前脚質', '前走決め手', '前3F順', '前頭数',
    '前走2着以内頭数', '前走通過順',
]
NUMBERED_PAST_RACE_RE = re.compile(r'^前(\d+)走(.+)$')

# 脚質（走り方）を表す列は、CSVの出力設定によって列名が異なることがあるため、
# 複数の候補から最初に値が入っているものを使う。
# 「決手」はTARGETの「過去5走分込み」形式のCSVでの1走前の脚質列（今走欄には
# 存在しないため列名の衝突は無い）。
STYLE_COLS = ['前脚質', '前走決め手', '決手']

# 直近走の3F順（末脚の順位）を表す列の候補。「上3F順位」は「過去5走分込み」
# 形式のCSVでの1走前の列名。
F3_RANK_COLS = ['前3F順', '上3F順位']

# 直近走のコーナー通過順位を表す列の候補（1〜4コーナー）。「通過順1」「2」
# 「3」「4」は「過去5走分込み」形式のCSVでの1走前の列名
# （2〜4コーナーは今走欄に同名の列が無いため列名がそのまま流用されている）。
PASSING_COL_CANDIDATES = {
    1: ['前通過1', '通過順1'],
    2: ['前通過2', '2'],
    3: ['前通過3', '3'],
    4: ['前通過4', '4'],
}

def first_nonempty(row, cols):
    for c in cols:
        v = row.get(c)
        if pd.notna(v) and str(v).strip() not in ('', 'nan', 'NaN'):
            return v
    return None

# レースを一意に識別するための列（出馬表CSVの「場所」「Ｒ」列）。
# 「Ｒ」列はCSVの出力設定によって全角「Ｒ」・半角「R」のどちらの場合もあるため、
# 実際に存在する方を都度解決する。
RACE_KEY_COL = '__race_key__'

def race_number_col(df: pd.DataFrame):
    """出馬表CSVのレース番号列（全角「Ｒ」または半角「R」）の実際の列名を返す。
    どちらも存在しなければ None。"""
    for c in ('Ｒ', 'R'):
        if c in df.columns:
            return c
    return None

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

# 過去走を使った分析で使う走数。
# 指数推移・脚質安定性は「直近の調子」を見たいので直近走に絞り、
# 同コース実績・好走時の脚質は該当例を見つけたいので取得できる分すべて使う。
RECENT_WALKS = 5
EXTENDED_WALKS = 20

def detect_available_walks(df: pd.DataFrame, max_cap: int = EXTENDED_WALKS) -> int:
    """出馬表CSVに実際に含まれる過去走の数（0〜max_cap）を検出する。
    「ﾚｰｽ名･N走前」列が1走前から連番で存在する前提で判定する。"""
    n = 0
    for walk_no in range(1, max_cap + 1):
        if f'ﾚｰｽ名･{walk_no}走前' not in df.columns:
            break
        n = walk_no
    return n

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
    return '場所' in df.columns and race_number_col(df) is not None

def drop_header_leak_rows(df: pd.DataFrame) -> pd.DataFrame:
    """出馬表CSVには、レースの区切りを示すヘッダー行がそのままデータとして
    紛れ込むことがある（例：「場所」列の値が文字列「場所」、「Ｒ」列の値が
    文字列「Ｒ」になっている）。そのような行は実在のレース・馬ではないため
    取り除く。"""
    if '場所' not in df.columns:
        return df
    mask = df['場所'] != '場所'
    r_col = race_number_col(df)
    if r_col:
        mask &= df[r_col] != r_col
    return df[mask].reset_index(drop=True)

def get_race_key(df: pd.DataFrame) -> pd.Series:
    """出馬表1行ごとに、どのレースに属するかを表すキーを返す。
    「場所」「Ｒ」列が無いCSV（旧形式）の場合は全行を1つのレース扱いにする。"""
    if has_race_columns(df):
        r_col = race_number_col(df)
        return df['場所'].astype(str) + '_' + df[r_col].astype(str)
    return pd.Series(['__all__'] * len(df), index=df.index)

def build_race_options(df: pd.DataFrame):
    """各レースのメタ情報（キー・場所・Ｒ・レース名・発走時刻など）を
    発走時刻順に並べたリストで返す。レース列が無ければ None。"""
    if not has_race_columns(df) or RACE_KEY_COL not in df.columns:
        return None

    r_col = race_number_col(df)
    rows = []
    for key, g in df.groupby(RACE_KEY_COL, sort=False):
        first = g.iloc[0]
        rows.append({
            'key': key,
            '場所': first.get('場所', ''),
            'Ｒ': first.get(r_col, ''),
            # 「レース名」列が無いCSV（新形式）では「略レース名」を使う
            'レース名': first_nonempty(first, ['レース名', '略レース名']) or '',
            '発走時刻': first.get('発走時刻', ''),
            '芝ダ': first.get('芝ダ', ''),
            '距離': first.get('距離', ''),
            '頭数': len(g),
        })

    rows.sort(key=lambda r: str(r['発走時刻']))
    return rows

def render_race_selector(race_options):
    """場所ごとにグループ化した「1R」「2R」…のピル（st.pillsウィジェット）で
    レースを選ばせ、選択中のレースのメタ情報（dict）を返す。
    以前はst.columns+st.buttonで組んだグリッドをCSSでスマホ幅用に折り返す
    方式だったが、Streamlit内部がこのブロックをスマホ幅で縦積みにする挙動を
    CSSで確実に上書きするのが難しく、実機（スマホのポートレート表示）では
    改善しなかった。st.pillsはそもそも折り返し表示に対応したStreamlit標準
    ウィジェットなので、CSSに頼らずスマホでも崩れずに並ぶ。
    race_options が空/Noneなら None。"""
    if not race_options:
        return None

    by_key = {r['key']: r for r in race_options}

    if st.session_state.get('selected_race_key') not in by_key:
        st.session_state['selected_race_key'] = race_options[0]['key']

    current_key = st.session_state['selected_race_key']
    current_race = by_key[current_key]

    venues = []
    races_by_venue = {}
    for r in race_options:
        venue = r['場所']
        if venue not in races_by_venue:
            races_by_venue[venue] = []
            venues.append(venue)
        races_by_venue[venue].append(r)

    for venue in venues:
        st.markdown(
            f"<div style='border-left:4px solid #2e7d32;padding-left:8px;"
            f"font-weight:bold;font-size:15px;margin:12px 0 6px;'>{venue}</div>",
            unsafe_allow_html=True,
        )
        races = sorted(races_by_venue[venue], key=lambda r: safe_float(r['Ｒ'], 0) or 0)
        labels = [f"{r['Ｒ']}R" for r in races]
        label_to_key = {label: r['key'] for label, r in zip(labels, races)}

        pills_key = f"pills_{venue}"
        # st.pillsは自身のkeyに紐づくsession_stateで選択状態を保持するため、
        # 描画の直前にこちら（selected_race_key）の状態を反映させておく。
        # こうしないと「別の開催のレースを選んだ後もこの開催のピルが
        # 選択済みのままに見える」というズレが起きる。
        st.session_state[pills_key] = (
            f"{current_race['Ｒ']}R" if current_race['場所'] == venue else None
        )
        selected_label = st.pills(
            venue, options=labels, key=pills_key, label_visibility="collapsed",
        )
        if selected_label is not None:
            new_key = label_to_key[selected_label]
            if new_key != current_key:
                st.session_state['selected_race_key'] = new_key
                st.rerun()

    return by_key[st.session_state['selected_race_key']]

def get_adjacent_races(race_options, current_key):
    """現在選択中のレースと同じ開催（場所）内で、Ｒ番号順に見た前後の
    レースのメタ情報を返す（prev_race, next_race）。該当が無ければ
    その方はNone。"""
    if not race_options or current_key is None:
        return None, None
    current = next((r for r in race_options if r['key'] == current_key), None)
    if current is None:
        return None, None
    venue = current['場所']
    same_venue = sorted(
        (r for r in race_options if r['場所'] == venue),
        key=lambda r: safe_float(r['Ｒ'], 0) or 0,
    )
    idx = next((i for i, r in enumerate(same_venue) if r['key'] == current_key), None)
    if idx is None:
        return None, None
    prev_race = same_venue[idx - 1] if idx > 0 else None
    next_race = same_venue[idx + 1] if idx < len(same_venue) - 1 else None
    return prev_race, next_race

def render_race_info(race_meta, df_race: pd.DataFrame, race_options=None):
    """選択中レースの発走時刻・レース名・距離・頭数などをまとめて表示する。
    race_optionsを渡すと、同じ開催内の前後のレースへ移動するボタンを
    バナーの両端に表示する。"""
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

    banner_html = (
        "<div style='background:#eef6ee;border:1px solid #cfe8cf;border-radius:8px;"
        "padding:10px 16px;font-size:17px;font-weight:bold;margin:4px 0 16px;'>"
        + "　".join(parts) + "</div>"
    )

    prev_race, next_race = get_adjacent_races(race_options, race_meta.get('key'))
    col_prev, col_mid, col_next = st.columns([1, 6, 1])

    if prev_race is not None:
        if col_prev.button("◀ 前R", key=f"prevrace_{race_meta['key']}", use_container_width=True):
            st.session_state['selected_race_key'] = prev_race['key']
            # render_race_infoが呼ばれた時点でdf_race等は既にこの回の
            # session_state（変更前の値）を元に計算済みのため、ここで
            # session_stateを更新しただけでは同じ実行内には反映されない
            # （ボタンを2回押さないと切り替わらないように見える不具合の原因）。
            # st.rerun()で即座に再実行し、更新後のレースを反映させる。
            st.rerun()
    else:
        col_prev.button("◀ 前R", key=f"prevrace_disabled_{race_meta['key']}",
                         disabled=True, use_container_width=True)

    col_mid.markdown(banner_html, unsafe_allow_html=True)

    if next_race is not None:
        if col_next.button("次R ▶", key=f"nextrace_{race_meta['key']}", use_container_width=True):
            st.session_state['selected_race_key'] = next_race['key']
            st.rerun()
    else:
        col_next.button("次R ▶", key=f"nextrace_disabled_{race_meta['key']}",
                         disabled=True, use_container_width=True)

# ==========================================================
# データ処理ロジック（既存アプリから移植・フレームワーク非依存）
# ==========================================================
def calc_position_and_patterns(df: pd.DataFrame) -> pd.DataFrame:
    def format_pass(row):
        passes = []
        for corner in [1, 2, 3, 4]:
            p = first_nonempty(row, PASSING_COL_CANDIDATES[corner])
            if p is not None:
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
        for corner in [4, 3, 2, 1]:
            p = first_nonempty(row, PASSING_COL_CANDIDATES[corner])
            if p is not None:
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
        f3 = safe_float(first_nonempty(row, F3_RANK_COLS), 0)
        total_h = safe_float(row.get('前頭数', 16))
        if f3 and total_h and f3 > 0 and total_h > 0:
            rel = max(0.0, min(1.0, 1.0 - (f3 - 1) / max(1.0, total_h - 1.0)))
            return str(round(rel * 100.0, 1))
        return "-"

    df['末脚スコア'] = df.apply(calc_3f_score, axis=1)

    def check_recommend(row):
        odds = safe_float(row.get('単オッズ', 0), 0.0)
        pos = row.get('予想展開', '')
        f3_rank = safe_float(first_nonempty(row, F3_RANK_COLS), 99.0)

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
def normalize_today_columns(df: pd.DataFrame) -> pd.DataFrame:
    """TARGETの「過去5走分込み」形式のCSVでは、今走の基本項目の列名が
    従来形式と異なる（馬番→番、馬名→馬名S、単オッズ→ 単勝〈先頭スペース〉）。
    さらに「馬番」「場所」など一部の項目名は過去走ブロックでも再利用され、
    そちらが優先的にpandasの列名として残ることがある（例：「馬番」は
    実際には1走前の馬番＝今走とは無関係の値になっている）。
    そのため、今走用の別名列が存在する場合は、既存の同名列（＝過去走側の
    データ）を退避してから、今走の値で上書きする。"""
    aliases = {
        '馬番': '番',
        '馬名': '馬名S',
        '単オッズ': ' 単勝',
    }
    for canonical, alias in aliases.items():
        if alias not in df.columns:
            continue
        if canonical in df.columns:
            # 既存の同名列は今走のものではない（過去走ブロック由来）ため、
            # データを失わないよう別名で退避してから上書きする。
            if f'{canonical}_過去走由来' not in df.columns:
                df[f'{canonical}_過去走由来'] = df[canonical]
        df[canonical] = df[alias]
    return df

@st.cache_data(show_spinner=False)
def load_main_csv(file_bytes) -> pd.DataFrame:
    df = pd.read_csv(file_bytes, dtype=str, encoding="cp932")
    df = drop_header_leak_rows(df)
    df = normalize_today_columns(df)
    df = calc_position_and_patterns(df)
    # 過去走データが無いCSV（旧形式）ではget_same_course_markが常に空文字を
    # 返すだけなので、常に計算して問題ない。
    df['同コース好走'] = df.apply(get_same_course_mark, axis=1)
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
        r_col = race_number_col(df)
        df_idx = df_idx.rename(columns={'Ｒ': r_col})
        merge_keys = ['場所', r_col, '馬番']
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
        # 「信頼できる先行馬」（展開予想図の🔥アイコンと同じ基準：予想展開が
        # 逃げ・先行で、かつ脚質安定性が安定/やや不安定）の行をハイライトする。
        # 安定＝濃い色、やや不安定＝薄い色で強弱を付ける。
        # 過去走データ（決手）が無いCSV（旧形式）では判定できないため、
        # その場合は何もハイライトしない。
        idx = row.name
        pos = full_reset.loc[idx, '予想展開'] if '予想展開' in full_reset.columns else ''
        if pos in ('逃げ', '先行') and past_race_col('決手', 1) in full_reset.columns:
            stability = compute_style_stability(full_reset.loc[idx])
            if stability['label'] == '安定':
                return [f'background-color:{RELIABLE_ROW_COLOR_STRONG};'] * len(row)
            if stability['label'] == 'やや不安定':
                return [f'background-color:{RELIABLE_ROW_COLOR_WEAK};'] * len(row)
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

    if '同コース好走' in display_df.columns:
        def highlight_same_course_good_run(s):
            styles = []
            for v in s:
                color = SAME_COURSE_MARK_COLORS.get(v)
                styles.append(f'background-color:{color}; font-weight:bold;' if color else '')
            return styles
        styler = styler.apply(highlight_same_course_good_run, subset=['同コース好走'])

    if '単オッズ' in display_df.columns:
        styler = styler.format({'単オッズ': lambda v: '' if pd.isna(v) else f'{v:.1f}'})

    return styler

def render_horse_detail(row: pd.Series):
    st.markdown(f"#### {row.get('馬番', '')}番 {row.get('馬名', '')}")
    sections = group_previous_race_columns(row.index.tolist())
    if not sections:
        st.info("過去走のデータが見つかりませんでした。")
    else:
        for title, items in sections:
            with st.expander(title, expanded=True):
                for label, col in items:
                    val = row.get(col, '-')
                    if pd.isna(val) or str(val).strip() == '':
                        val = '-'
                    st.markdown(f"**{label}**: {val}")

    render_prev_index_section(row)
    render_style_analysis_section(row)

# ==========================================================
# 過去走データ（TARGETが出力する「過去5走分込み」形式のCSV対応）
# ==========================================================
# 出馬表CSVが「今走」の列に加えて1走前〜5走前の列をまとめて含む場合、
# 同じ項目名（騎手・場所・距離・斤量・人気・FU2・S指数・F指数・arms2・
# レースID(新)など）が「今走」欄でも使われているため、pandasの重複列名
# 自動リネームにより「N走前」の実際の列名は以下のいずれかになる。
#   ・今走欄にも同名の列がある項目 → f"{項目名}.{N}"
#   ・今走欄には無い項目（着順・通過順など過去走特有の項目） →
#       1走前は項目名そのまま、2走前以降は f"{項目名}.{N-1}"
PAST_RACE_COLS_CLASH_WITH_TODAY = {
    '騎手', '場所', '距離', '斤量', '人気', 'FU2', 'S指数', 'F指数',
    'arms2', 'レースID(新)', 'B',
}

def past_race_col(base_name: str, walk_no: int) -> str:
    """出馬表CSVに含まれる「walk_no走前」のbase_name列の実際の列名を返す。"""
    if base_name in PAST_RACE_COLS_CLASH_WITH_TODAY:
        return f"{base_name}.{walk_no}"
    return base_name if walk_no == 1 else f"{base_name}.{walk_no - 1}"

# 各指数について、「同じ前走レース内での順位」が入っている列（TARGET側の出力名）
PAST_INDEX_RANK_BASE = {'FU2': '順A', 'S指数': '順B', 'F指数': '順C'}

def _clean_walk_value(v, header_name):
    """出馬表CSVでレース区切りのヘッダー行がそのままデータに紛れ込む
    （例：値が文字列「場所」になっている）ことがあるため、その場合は
    データなし扱いにする。"""
    if pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s in ('nan', 'NaN', header_name):
        return None
    return s

def get_walk_style(row: pd.Series, walk_no: int):
    """walk_no走前の脚質（決手）テキストを返す。無ければ None。"""
    return _clean_walk_value(row.get(past_race_col('決手', walk_no)), '決手')

def get_walk_finish(row: pd.Series, walk_no: int):
    """walk_no走前の着順（数値）を返す。無ければ None。"""
    v = _clean_walk_value(row.get(past_race_col('着順', walk_no)), '着順')
    return safe_float(v)

def get_walk_race_name(row: pd.Series, walk_no: int):
    """walk_no走前のレース名を返す。無ければ None。"""
    col = f'ﾚｰｽ名･{walk_no}走前'
    return _clean_walk_value(row.get(col), col)

def get_walk_date(row: pd.Series, walk_no: int):
    """walk_no走前の日付（文字列）を返す。無ければ None。"""
    col = f'日付S･{walk_no}前'
    return _clean_walk_value(row.get(col), col)

def normalize_surface(v):
    """芝・ダート区分の表記ゆれ（今走欄「ダート」/過去走欄「ダ」、
    障害レースの細区分など）を吸収して大まかな区分にそろえる。"""
    if v is None:
        return None
    if '障' in v:
        return '障害'
    if 'ダ' in v:
        return 'ダート'
    if '芝' in v:
        return '芝'
    return v

def get_today_course(row: pd.Series):
    """今走の(場所, 芝ダ区分, 距離)を返す。値が欠けていればNoneを含む。"""
    venue = _clean_walk_value(row.get('場所'), '場所')
    surface = normalize_surface(_clean_walk_value(row.get('芝・ダート'), '芝・ダート'))
    distance = _clean_walk_value(row.get('距離'), '距離')
    return (venue, surface, distance)

def get_walk_course(row: pd.Series, walk_no: int):
    """walk_no走前の(場所, 芝ダ区分, 距離)を返す。値が欠けていればNoneを含む。"""
    venue = _clean_walk_value(row.get(past_race_col('場所', walk_no)), '場所')
    surface = normalize_surface(_clean_walk_value(row.get(past_race_col('芝・ダ', walk_no)), '芝・ダ'))
    distance = _clean_walk_value(row.get(past_race_col('距離', walk_no)), '距離')
    return (venue, surface, distance)

def is_same_course(row: pd.Series, walk_no: int) -> bool:
    """walk_no走前が今走と「場所・芝ダート区分・距離」すべて完全一致するか。"""
    today = get_today_course(row)
    if any(v is None for v in today):
        return False
    past = get_walk_course(row, walk_no)
    if any(v is None for v in past):
        return False
    return today == past

# 脚質安定性の判定しきい値（重み付き最頻値の得票率）
STYLE_STABILITY_THRESHOLDS = (0.6, 0.4)  # (安定, やや不安定) の境界

def compute_style_stability(row: pd.Series, num_walks: int = RECENT_WALKS):
    """直近num_walks走の脚質（決手）から、最も多い脚質とその安定度を求める。
    今走と同コース（完全一致）の走は2票分として重み付けする。
    有効データが2走未満の場合は安定度を判定せず「データ不足」とする。
    sequenceは古い→新しい順（例：num_walks走前→1走前）。"""
    votes = {}
    sequence = []
    valid_count = 0
    for walk_no in range(num_walks, 0, -1):
        style = get_walk_style(row, walk_no)
        sequence.append(style or '-')
        if style is None:
            continue
        valid_count += 1
        weight = 2.0 if is_same_course(row, walk_no) else 1.0
        votes[style] = votes.get(style, 0.0) + weight

    if valid_count < 2:
        return {'mode': None, 'ratio': None, 'label': 'データ不足', 'sequence': sequence}

    total_weight = sum(votes.values())
    mode_style = max(votes, key=votes.get)
    ratio = votes[mode_style] / total_weight
    if ratio >= STYLE_STABILITY_THRESHOLDS[0]:
        label = '安定'
    elif ratio >= STYLE_STABILITY_THRESHOLDS[1]:
        label = 'やや不安定'
    else:
        label = '不安定'
    return {'mode': mode_style, 'ratio': ratio, 'label': label, 'sequence': sequence}

# 「好走」とみなす着順のしきい値（3着以内）
GOOD_FINISH_THRESHOLD = 3

def compute_good_run_style(row: pd.Series, num_walks: int = EXTENDED_WALKS):
    """好走（着順3着以内）だった走に絞って、最も多い脚質を求める。
    好走が2走未満しか無い場合は判断材料として不十分なため None を返す。"""
    votes = {}
    good_total = 0
    for walk_no in range(1, num_walks + 1):
        finish = get_walk_finish(row, walk_no)
        if finish is None or finish > GOOD_FINISH_THRESHOLD:
            continue
        style = get_walk_style(row, walk_no)
        if style is None:
            continue
        good_total += 1
        votes[style] = votes.get(style, 0) + 1

    if good_total < 2 or not votes:
        return None

    mode_style = max(votes, key=votes.get)
    return {'mode': mode_style, 'count': votes[mode_style], 'good_total': good_total}

def compute_same_course_good_run(row: pd.Series, num_walks: int = EXTENDED_WALKS) -> bool:
    """過去num_walks走の中に、今走と同コース（場所・芝ダート区分・距離が
    完全一致）かつ好走（3着以内）だった走があるかどうかを返す。
    過去走データが無いCSV（旧形式）でもFalseを返すだけで例外にはならない。"""
    for walk_no in range(1, num_walks + 1):
        if not is_same_course(row, walk_no):
            continue
        finish = get_walk_finish(row, walk_no)
        if finish is not None and finish <= GOOD_FINISH_THRESHOLD:
            return True
    return False

def compute_same_course_win_count(row: pd.Series, num_walks: int = EXTENDED_WALKS) -> int:
    """過去num_walks走の中で、今走と同コース（場所・芝ダート区分・距離が
    完全一致）かつ1着（勝利）だった回数を返す。"""
    count = 0
    for walk_no in range(1, num_walks + 1):
        if not is_same_course(row, walk_no):
            continue
        finish = get_walk_finish(row, walk_no)
        if finish is not None and finish == 1:
            count += 1
    return count

# 出馬表の「同コース好走」欄に表示するマーク。
# 〇：同コースで3着以内の実績はあるが勝利（1着）は無い
# ◎：同コースでの勝利（1着）が1回
# ☆：同コースでの勝利（1着）が2回以上（複数回の勝利実績＝本当に得意）
SAME_COURSE_MARK_GOOD = '〇'
SAME_COURSE_MARK_WIN = '◎'
SAME_COURSE_MARK_MULTI_WIN = '☆'
SAME_COURSE_MARK_COLORS = {
    SAME_COURSE_MARK_GOOD: '#fff3cd',
    SAME_COURSE_MARK_WIN: '#ffe0a3',
    SAME_COURSE_MARK_MULTI_WIN: '#ffd700',
}

def get_same_course_mark(row: pd.Series, num_walks: int = EXTENDED_WALKS) -> str:
    """出馬表の「同コース好走」列に表示するマークを返す
    （SAME_COURSE_MARK_*の優先順：☆ > ◎ > 〇）。
    該当なし、または過去走データが無いCSV（旧形式）の場合は空文字を返す。"""
    win_count = compute_same_course_win_count(row, num_walks)
    if win_count >= 2:
        return SAME_COURSE_MARK_MULTI_WIN
    if win_count == 1:
        return SAME_COURSE_MARK_WIN
    if compute_same_course_good_run(row, num_walks):
        return SAME_COURSE_MARK_GOOD
    return ''

# 指数推移で上昇/下降と判定する変化率のしきい値
INDEX_TREND_THRESHOLD = 0.10

def compute_index_trend(row: pd.Series, idx_name: str, num_walks: int = RECENT_WALKS):
    """今走のidx_name（F指数/S指数/FU2）の値を、直近num_walks走の平均と比較し、
    上昇/下降/横ばいを判定する。今走の値または比較対象が無ければ None。"""
    today_val = safe_float(row.get(idx_name))
    if today_val is None:
        return None

    past_values = []
    for walk_no in range(1, num_walks + 1):
        info = get_past_index_info(row, idx_name, walk_no)
        if info is not None:
            v = safe_float(info['value'])
            if v is not None:
                past_values.append(v)

    if not past_values:
        return None

    avg = sum(past_values) / len(past_values)
    if avg == 0:
        return None
    pct_change = (today_val - avg) / avg

    if pct_change >= INDEX_TREND_THRESHOLD:
        label = '上昇'
    elif pct_change <= -INDEX_TREND_THRESHOLD:
        label = '下降'
    else:
        label = '横ばい'

    return {'today': today_val, 'avg': round(avg, 1), 'pct_change': pct_change, 'label': label}

def compute_pace_forecast(df: pd.DataFrame):
    """レース全体の予想展開から、信頼できる（脚質安定性が安定/やや不安定の）
    逃げ・先行馬の頭数を数え、レースのペースを予想する。
    reliable_umabanには該当馬の馬番（文字列）を入れる
    （カード側で該当馬をアイコン表示するために使う）。"""
    reliable_umaban = set()
    for _, row in df.iterrows():
        pos = row.get('予想展開', '')
        if pos not in ('逃げ', '先行'):
            continue
        stability = compute_style_stability(row)
        if stability['label'] in ('安定', 'やや不安定'):
            reliable_umaban.add(str(row.get('馬番', '')).strip())

    n = len(reliable_umaban)
    if n <= 1:
        label = 'スロー想定'
    elif n == 2:
        label = 'ミドル想定'
    else:
        label = 'ハイ想定'
    return {'label': label, 'reliable_umaban': reliable_umaban}

def _has_past_index_cols(columns, walk_no: int = 1) -> bool:
    col_set = set(columns)
    return all(past_race_col(name, walk_no) in col_set for name in TENKAI_BADGE_ORDER)

def get_past_index_info(row: pd.Series, idx_name: str, walk_no: int = 1):
    """出馬表CSVの1行から、walk_no走前のidx_name（F指数/S指数/FU2）の
    値と、その前走レース内での順位（1〜3位のみ色分け対象）を取り出す。
    値が無ければ None。"""
    value_col = past_race_col(idx_name, walk_no)
    val = row.get(value_col)
    if pd.isna(val) or str(val).strip() == '':
        return None
    rank_col = past_race_col(PAST_INDEX_RANK_BASE[idx_name], walk_no)
    rank = row.get(rank_col)
    rank_int = None
    if pd.notna(rank) and str(rank).strip() != '':
        try:
            rank_int = int(float(rank))
        except (TypeError, ValueError):
            rank_int = None
    return {'value': val, 'rank': rank_int}

def render_prev_index_section(row: pd.Series):
    """出馬表CSVに1走前の指数データ（TARGETの「過去5走分込み」形式）が
    含まれていれば、前走時点のFU2・S指数・F指数を表示する。今走の指数と
    同じく、同じ前走レース内で1〜3位だった場合のみ色を付ける。"""
    if not _has_past_index_cols(row.index):
        return

    with st.expander("前走時点の指数", expanded=True):
        for idx_name in TENKAI_BADGE_ORDER:
            info = get_past_index_info(row, idx_name, walk_no=1)
            if info is None:
                st.markdown(f"**{idx_name}**: 見つかりません")
                continue
            if info['rank'] in RANK_COLORS:
                bg, fg = RANK_COLORS[info['rank']]
                st.markdown(
                    f"**{idx_name}**: <span style='background:{bg};color:{fg};"
                    f"padding:2px 8px;border-radius:4px;font-weight:bold;'>"
                    f"{info['value']}</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"**{idx_name}**: {info['value']}")

INDEX_TREND_ARROWS = {'上昇': '↑', '下降': '↓', '横ばい': '→'}

def render_style_analysis_section(row: pd.Series):
    """脚質安定性・好走時の脚質・指数推移をまとめて表示する
    （TARGETの「過去N走分込み」形式のCSVでのみ有効）。"""
    if past_race_col('決手', 1) not in row.index:
        return

    with st.expander("脚質・指数の分析", expanded=True):
        stability = compute_style_stability(row)
        if stability['mode']:
            st.markdown(
                f"**脚質安定性**：{stability['label']}"
                f"（{stability['mode']} {stability['ratio']:.0%}）"
            )
        else:
            st.markdown(f"**脚質安定性**：{stability['label']}")
        st.caption("推移（古い→新しい）：" + " → ".join(stability['sequence']))

        good = compute_good_run_style(row)
        if good:
            st.markdown(
                f"**好走時の脚質**：{good['mode']}"
                f"（好走{good['good_total']}走中{good['count']}走）"
            )
        else:
            st.markdown("**好走時の脚質**：データ不足")

        for idx_name in TENKAI_BADGE_ORDER:
            trend = compute_index_trend(row, idx_name)
            if trend is None:
                continue
            arrow = INDEX_TREND_ARROWS[trend['label']]
            st.markdown(
                f"**{idx_name}推移**：今走{trend['today']:g} vs 過去平均{trend['avg']:g}"
                f"（{trend['pct_change']:+.0%} {arrow}{trend['label']}）"
            )

def build_card_analysis_html(row: pd.Series) -> str:
    """展開予想図カード用に、脚質安定性・好走時の脚質をコンパクトな1行に
    まとめる（馬詳細ダイアログの「脚質・指数の分析」の簡略版）。
    指数推移は今走バッジの横に矢印で表示するため、ここには含めない。
    過去走データが無ければ空文字を返す。"""
    if past_race_col('決手', 1) not in row.index:
        return ""

    stability = compute_style_stability(row)
    stability_text = stability['label']
    if stability['mode']:
        stability_text += f"({stability['mode']})"

    good = compute_good_run_style(row)
    good_text = f"好走:{good['mode']}" if good else "好走データ不足"

    return (
        "<div style='padding:0 6px 6px;color:#bbb;font-size:10px;line-height:1.6;'>"
        f"脚質: {stability_text} / {good_text}"
        "</div>"
    )

@st.dialog("馬詳細")
def show_horse_detail_dialog(row: pd.Series):
    """出馬表の行をクリックした際に、スクロール不要でその場にポップアップ表示する。"""
    render_horse_detail(row)

# ==========================================================
# 展開予想図（カード表示・スマホ幅対応）
# ==========================================================
PREV_LABEL_SHORT = {'FU2': 'FU2', 'S指数': 'S', 'F指数': 'F'}
# 展開予想図カードでのバッジ表示順（今走・前走とも共通。位置を揃えるため同じ順序を使う）
TENKAI_BADGE_ORDER = ['FU2', 'S指数', 'F指数']

# 信頼できる先行馬アイコン。カードのヘッダー背景色（脚質カテゴリごとに異なる）に
# 対しても視認できるよう、白背景の丸バッジで包んで常に目立たせる。
# 脚質安定性が「安定」なら🔥🔥、「やや不安定」なら🔥で強弱を付ける。
def _reliable_icon_html(fire_count: int) -> str:
    return (
        "<span style='background:#fff;border-radius:50%;display:inline-block;"
        "line-height:1;padding:1px 3px;font-size:10px;margin-left:3px;"
        f"box-shadow:0 0 0 1px #333;'>{'🔥' * fire_count}</span>"
    )

RELIABLE_ICON_STRONG_HTML = _reliable_icon_html(2)  # 脚質安定性「安定」
RELIABLE_ICON_WEAK_HTML = _reliable_icon_html(1)    # 脚質安定性「やや不安定」

def render_tenkai_view(df: pd.DataFrame):
    st.markdown(
        "<p style='color:#aaaaaa;font-size:13px;'>"
        "逃 → 先 → 先差 → 差 → 追　/　同じ段では左（上）ほど前寄り</p>",
        unsafe_allow_html=True,
    )

    has_style_data = past_race_col('決手', 1) in df.columns
    pace = compute_pace_forecast(df) if has_style_data else None
    if pace is not None:
        st.markdown(
            f"<div style='background:#1a1a2e;color:white;font-weight:bold;"
            f"padding:8px 12px;border-radius:6px;margin-bottom:10px;'>"
            f"推定ペース：{pace['label']}"
            f"（🔥🔥＝信頼度高い先行馬 / 🔥＝信頼できる先行馬）</div>",
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
            for idx_name in TENKAI_BADGE_ORDER:
                val = row.get(idx_name)
                rank = row.get(f"{idx_name}_rank")
                name_short = PREV_LABEL_SHORT[idx_name]
                if pd.isna(val) or val == "":
                    badges_html += (
                        "<span style='display:inline-block;min-width:40px;text-align:center;"
                        "background:#111;color:white;border:1px solid #444;"
                        "border-radius:3px;padding:2px 5px;font-size:11px;margin-right:2px;'>-</span>"
                    )
                    continue
                r = int(rank) if pd.notna(rank) else 99
                bg_c, fg_c = RANK_COLORS.get(r, ("#111111", "white"))
                trend = compute_index_trend(row, idx_name) if has_style_data else None
                arrow = INDEX_TREND_ARROWS[trend['label']] if trend else ""
                label = f"{name_short} {val}{arrow}"
                badges_html += (
                    f"<span style='display:inline-block;min-width:40px;text-align:center;"
                    f"background:{bg_c};color:{fg_c};border:1px solid #444;"
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

            # 信頼できる（脚質が安定した）逃げ・先行馬には馬名の横にアイコンを付ける。
            # 脚質安定性が「安定」なら🔥🔥、「やや不安定」なら🔥で強弱を付ける。
            reliable_icon = ""
            if pace is not None and str(row.get('馬番', '')).strip() in pace['reliable_umaban']:
                icon_stability = compute_style_stability(row)
                if icon_stability['label'] == '安定':
                    reliable_icon = f" {RELIABLE_ICON_STRONG_HTML}"
                elif icon_stability['label'] == 'やや不安定':
                    reliable_icon = f" {RELIABLE_ICON_WEAK_HTML}"

            analysis_html = build_card_analysis_html(row) if has_style_data else ""

            cards_html += (
                "<div style='background:#2a1a1a;border:1px solid #555;border-radius:4px;"
                "min-width:160px;max-width:200px;'>"
                f"<div style='background:{cat_color};color:white;font-weight:bold;"
                f"font-size:12px;padding:3px 6px;'>{waku_badge}{row.get('馬番', '')} {row.get('馬名', '')}{reliable_icon}</div>"
                f"<div style='color:lightgray;font-size:11px;padding:3px 6px;'>前走: {pass_str}</div>"
                f"<div style='padding:3px 6px 6px;'>{badges_html}</div>"
                f"{analysis_html}"
                "</div>"
            )
        cards_html += "</div>"
        st.markdown(cards_html, unsafe_allow_html=True)

# ==========================================================
# 近走成績（過去N走を表形式で一覧表示）
# ==========================================================
def _numeric_or_original(series: pd.Series) -> pd.Series:
    """列の大半の値が数値に変換できる場合は数値型（整数のみならInt64）に
    変換して返す。そうでなければ元のSeriesをそのまま返す。
    dtype=strで読み込んだ列や、'-'を欠損として含む列を、表の列見出し
    クリックでの並べ替えが文字列比較（「10」が「2」より前に来る等）に
    ならないようにするために使う。"""
    converted = pd.to_numeric(series, errors='coerce')
    as_str = series.astype(str).str.strip()
    non_empty = series.notna() & (as_str != '') & (as_str != '-')
    if non_empty.sum() > 0 and converted.notna().sum() >= non_empty.sum() * 0.9:
        if (converted.dropna() % 1 == 0).all():
            return converted.astype('Int64')
        return converted
    return series

def build_recent_races_table(row: pd.Series, num_walks: int):
    """指定した馬の直近num_walks走を、新しい→古い順（1走前が先頭）の
    DataFrameにまとめる。レース名が取得できない走（データが無い）は
    スキップする。"""
    records = []
    for walk_no in range(1, num_walks + 1):
        race_name = get_walk_race_name(row, walk_no)
        if race_name is None:
            continue
        venue, surface, distance = get_walk_course(row, walk_no)
        finish = get_walk_finish(row, walk_no)
        info_fu2 = get_past_index_info(row, 'FU2', walk_no)
        info_s = get_past_index_info(row, 'S指数', walk_no)
        info_f = get_past_index_info(row, 'F指数', walk_no)
        records.append({
            '走': f"{walk_no}走前",
            '日付': get_walk_date(row, walk_no) or '-',
            'レース名': race_name,
            '場所': venue or '-',
            '芝ダ': surface or '-',
            '距離': distance or '-',
            '着順': int(finish) if finish is not None else None,
            '脚質': get_walk_style(row, walk_no) or '-',
            'FU2': info_fu2['value'] if info_fu2 else '-',
            'S指数': info_s['value'] if info_s else '-',
            'F指数': info_f['value'] if info_f else '-',
            '同コース': is_same_course(row, walk_no),
        })
    hist_df = pd.DataFrame(records)
    for col in ('FU2', 'S指数', 'F指数', '距離'):
        if col in hist_df.columns:
            hist_df[col] = _numeric_or_original(hist_df[col])
    return hist_df

def render_recent_races_tab(df_race: pd.DataFrame):
    """選択した馬の過去走を表形式で一覧表示する
    （TARGETの「過去N走分込み」形式のCSVでのみ有効）。"""
    if past_race_col('決手', 1) not in df_race.columns:
        st.info("この出馬表CSVには過去走データが含まれていません。")
        return

    horse_labels = [
        f"{row.get('馬番', '')} {row.get('馬名', '')}"
        for _, row in df_race.iterrows()
    ]
    if not horse_labels:
        st.info("表示できる馬がいません。")
        return

    selected = st.selectbox("馬を選択", options=horse_labels)
    row = df_race.iloc[horse_labels.index(selected)]

    num_walks = detect_available_walks(df_race)
    if num_walks == 0:
        st.info("過去走データが見つかりませんでした。")
        return

    hist_df = build_recent_races_table(row, num_walks)
    if hist_df.empty:
        st.info("この馬の過去走データが見つかりませんでした。")
        return

    def highlight_row(r):
        # rはdisplay_df（「同コース」列を除いた列数）の行として渡されるため、
        # 判定に必要な値は元のhist_dfをインデックスで引いて取得する
        # （返すスタイル配列の長さはrの列数=display_dfの列数に合わせる）。
        idx = r.name
        style = ''
        if hist_df.loc[idx, '同コース']:
            style += 'background-color:#fff3cd;'
        finish = hist_df.loc[idx, '着順']
        if finish is not None and finish <= GOOD_FINISH_THRESHOLD:
            style += 'font-weight:bold;color:#1a53ff;'
        return [style] * len(r)

    display_df = hist_df.drop(columns=['同コース'])
    styler = display_df.style.apply(highlight_row, axis=1)
    # FU2/S指数/F指数/距離は並べ替えを数値として行うためInt64/float型に
    # 変換済み（_numeric_or_original）。データが無い走はNA（<NA>表示）に
    # なってしまうため、表示上は元通り「-」に戻す。
    na_fallback_cols = [c for c in ('FU2', 'S指数', 'F指数', '距離') if c in display_df.columns]
    if na_fallback_cols:
        styler = styler.format({c: lambda v: '-' if pd.isna(v) else v for c in na_fallback_cols})
    st.caption("背景色＝今走と同コース（場所・芝ダート・距離が完全一致） / 太字青字＝3着以内")
    st.dataframe(styler, use_container_width=True, hide_index=True)

def render_horse_quick_select(df_race: pd.DataFrame, race_key):
    """馬名ボタンをクリックすると、その馬の前走詳細をポップアップ表示する。
    （出馬表テーブルの行選択チェックボックス操作の代わりに、直接クリックで
    開けるようにするためのUI。race_keyはボタンのkeyをレースごとに一意に
    するために使う。）"""
    rows = df_race.reset_index(drop=True)
    if rows.empty:
        return

    st.caption("馬名をクリックすると、その馬の前走詳細がポップアップで表示されます。")
    cols_per_row = 6
    for start in range(0, len(rows), cols_per_row):
        chunk = rows.iloc[start:start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, (i, row) in zip(cols, chunk.iterrows()):
            label = f"{row.get('馬番', '')} {row.get('馬名', '')}"
            if col.button(label, key=f"horsebtn_{race_key}_{i}", use_container_width=True):
                show_horse_detail_dialog(row)

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
    render_race_info(selected_race, df_race, race_options)

    all_cols = [
        c for c in df_race.columns
        if not c.endswith('_rank') and not c.endswith('_過去走由来')
        and c not in ('先行順位', RACE_KEY_COL)
    ]
    default_cols = [c for c in [
        '枠番', '馬番', '馬名', '騎手', '人気', '単オッズ', '推奨',
        '予想展開', '前走通過順', '同コース好走', 'F指数', 'S指数', 'FU2',
    ] if c in all_cols]

    tab_table, tab_tenkai, tab_recent = st.tabs(["📋 出馬表", "🗺️ 展開予想図", "📖 近走成績"])

    with tab_table:
        with st.popover("⚙️ 表示する項目"):
            display_columns = st.multiselect("表示する項目", options=all_cols, default=default_cols)
        if not display_columns:
            st.warning("表示する項目を1つ以上選んでください。")
        else:
            display_df = build_display_dataframe(df_race, display_columns)
            styler = style_dataframe(display_df, df_race)

            # 行数分の高さを確保し、テーブル内部のスクロールバーが出ないようにする
            # （ヘッダー約38px＋1行約35px、Streamlitのデータフレーム標準の目安）。
            table_height = 38 + 35 * len(display_df) + 3

            st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                height=table_height,
            )

            # チェックボックスでの行選択ではなく、馬名ボタンのクリックで
            # 詳細ポップアップを開けるようにする。
            render_horse_quick_select(df_race, selected_race['key'] if selected_race else None)

    with tab_tenkai:
        render_tenkai_view(df_race)

    with tab_recent:
        render_recent_races_tab(df_race)

if __name__ == "__main__":
    main()
