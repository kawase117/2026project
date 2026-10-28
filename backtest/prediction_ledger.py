"""予測文書(document/reviews/*-prediction.md)の名指しを凍結し、翌朝に採点する台帳。

なぜ要るか:
    予測文書は自由記述で、どの台・機種を推したかが構造化されていない。そのため
    「予測が無作為に座るより良かったか」を forward ルールと同じ物差しで測れず、
    総合採点表(backtest.scoreboard)から抜けていた(2026-10-16)。

何を凍結するか(1ホール×1対象日=1ファイル):
    - models       : 「判断」の行に出てくる機種(model_alias で正式名に当てたもの)
    - avoid_models : 「避ける」の行に出てくる機種
    - units        : 「判断」の行に出てくる台番号(その日に存在する台に限る)
    - jug_units    : 「ジャグラー候補」表の台番号
    抽出は機械的に行い、照合できなかった語は unresolved に残す(取りこぼしを見えるように)。

事前性(timing):
    凍結時刻が 対象日10:00 JST より前なら pre_open、当日中なら same_day、翌日以降なら after。
    過去文書の取り込み(backfill)では凍結時刻の代わりに git の初出コミット時刻を使う
    (timing_basis=git_first_commit)。コミットは書いた時刻の上限でしかないので、
    after でも中身は前日までのデータで書かれていることが多い。採点表では件数を併記する。
    今後は予測文書を書いた直後に freeze-doc を実行し、timing_basis=frozen_at で残す。

採点(forward と同じ定義):
    当日の全台平均差枚(day_mean)を無作為に座った場合の期待値とし、
    名指し機種の台合計差枚/台数 − day_mean を edge とする(機種平均を機種間で単純平均しない)。
    避ける機種は day_mean − 機種の台平均 を edge とする(正なら「避けて正解」)。

使い方:
    venv\\Scripts\\python.exe -m backtest.prediction_ledger extract document/reviews/2026-10-15-prediction.md
    venv\\Scripts\\python.exe -m backtest.prediction_ledger freeze-doc document/reviews/2026-10-17-prediction.md
    venv\\Scripts\\python.exe -m backtest.prediction_ledger backfill      # 過去文書をgit時刻つきで取り込む
    venv\\Scripts\\python.exe -m backtest.prediction_ledger score-due     # 対象日のデータがある未採点を採点
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest import model_alias
from backtest.prediction_rb import rb_result, rb_s1_result, rb_machine_result, family_offsets

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
REVIEWS_DIR = ROOT / "document" / "reviews"
PRED_DIR = Path(__file__).resolve().parent / "predictions"
LEDGER_NAME = "LEDGER.jsonl"
OPEN_HOUR = 10

# 実績DB名 → 予測文書での呼び方。
HALLS: dict[str, tuple[str, ...]] = {
    "マルハンメガシティ2000-蒲田7": ("蒲田7", "蒲田七"),
    "マルハンメガシティ2000-蒲田1": ("蒲田1", "蒲田一"),
    "楽園蒲田店": ("楽園蒲田", "楽園"),
    "レイトギャップ平和島": ("平和島",),
    "みとや大森町店": ("みとや",),
    "金時蒲田東口店": ("金時蒲田東口", "金時東口"),
    "金時京急蒲田店": ("金時京急蒲田", "金時京急"),
    "ヒロキ東口店": ("ヒロキ東口",),
    "ヒロキ蒲田西口店": ("ヒロキ蒲田西口", "ヒロキ西口"),
    "ヒロキMAX蒲田店": ("ヒロキMAX蒲田", "ヒロキMAX"),
    "ARROW池上店": ("ARROW池上", "ARROW"),
    "ザ-シティ-ベルシティ雑色店": ("雑色",),
}
HALL_KEY = {
    "マルハンメガシティ2000-蒲田7": "kamata7",
    "マルハンメガシティ2000-蒲田1": "kamata1",
    "楽園蒲田店": "rakuen",
    "レイトギャップ平和島": "heiwajima",
    "みとや大森町店": "mitoya",
    "金時蒲田東口店": "kinji_higashiguchi",
    "金時京急蒲田店": "kinji_keikyu",
    "ヒロキ東口店": "hiroki_higashiguchi",
    "ヒロキ蒲田西口店": "hiroki_nishiguchi",
    "ヒロキMAX蒲田店": "hiroki_max",
    "ARROW池上店": "arrow",
    "ザ-シティ-ベルシティ雑色店": "zassiki",
}
# 予測文書には出ないが、RB機種候補の自動凍結(rbauto)だけが使うホール。HALLS と HALL_KEY の一致を要求する
# 既存テスト(test_hiroki_halls_registered)があるので、HALL_KEY には足さずここで持つ。
RB_AUTO_EXTRA_KEYS = {"BIGディッパー戸越銀座店": "big_dipper"}

DOC_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})-prediction\.md$")
# 区切り記号で切った断片がそのまま機種名に当たらないときだけ、助詞で更に分ける
# (「分散先はカバネリ海門」→「分散先」「カバネリ海門」)。先に丸ごと試すのは
# 「からくりサーカス2」「甲鉄城のカバネリ」のように助詞と同じ字を含む名前を壊さないため。
_PARTICLES = re.compile(r"の|で|は|を|が|と|も|や|に|から|まで|より")
_SPLIT = re.compile(r"[・、,，。:：;；/／()（）「」『』\[\]【】|｜\s→=＝]+")
# 台番号(3桁以上)と差枚(±付き)だけを落とす。「からくり2」「新鬼武者3」の版数は残す。
_TRAILING_NUM = re.compile(r"(?:[+\-−]\s*[\d,]+|\d{3,})$")
# 2文字の語は機種名(獣王・吉宗・北斗)のこともあるので照合に回すが、文中の一般語は弾く。
_STOPWORDS = {
    "判断",
    "温度",
    "根拠",
    "確度",
    "並び",
    "母体",
    "機種",
    "台数",
    "上位",
    "下位",
    "平均",
    "前回",
    "位置",
    "回転",
    "回転数",
    "開店",
    "分散",
    "分散先",
    "候補",
    "下表",
    "上表",
    "本線",
    "全台",
    "全系",
    "単品",
    "末尾",
    "角番",
    "設定",
    "高設定",
    "注意",
    "参考",
    "根拠薄",
    "狙い",
    "狙い台",
    "ジャグラー",
}
_UNIT = re.compile(r"(?<!\d)(\d{2,4})(?!\d)")


def hall_of(text: str) -> str | None:
    """見出し・表のセルからホールを特定する。複数に当たるときは None。"""
    t = unicodedata.normalize("NFKC", text)
    hits = {hall for hall, words in HALLS.items() if any(w in t for w in words)}
    return hits.pop() if len(hits) == 1 else None


def _ro(hall: str) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % (DB_DIR / f"{hall}.db"), uri=True)


def roster(hall: str, target_date: str) -> tuple[str | None, dict[str, set[int]]]:
    """対象日より前の最終収録日の {機種名: 台番号の集合}。"""
    with _ro(hall) as con:
        last = con.execute("SELECT MAX(date) FROM machine_detailed_results WHERE date < ?", (target_date,)).fetchone()[
            0
        ]
        if not last:
            return None, {}
        out: dict[str, set[int]] = {}
        for name, num in con.execute(
            "SELECT machine_name, machine_number FROM machine_detailed_results WHERE date = ?", (last,)
        ):
            out.setdefault(name, set()).add(int(num))
    return last, out


def _clean(tok: str) -> str | None:
    tok = _TRAILING_NUM.sub("", tok.strip().strip("*")).strip()
    key = model_alias.norm(tok)
    # 数字だけの語(「直近 30 日」の 30)は、名前に数字を含む機種(沖ドキ!GOLD‐30)に当ててはいけない
    if len(key) < 2 or key.isdigit() or tok in _STOPWORDS:
        return None
    return tok


_ALIAS_KEYS = {model_alias.norm(a) for a in model_alias.ALIASES}


_HIRAGANA_ONLY = re.compile(r"^[ぁ-ゟ]+$")
# 本文に正式名そのものが丸ごと入っているかを見るときの最小の長さ(norm後)。これより短い名前は
# 一般語に紛れやすいので、従来どおり断片ごとの照合に任せる。
_MIN_FULL_NAME_LEN = 3
_MARK = ""


def _loose_short_match(tok: str, hits: list[str]) -> bool:
    """2文字の語が正式名の途中や語尾に部分一致しただけのとき True。

    「根拠はなく」の「なく」→『うみねこのなく頃に』、「材料がない」の「ない」→『…夢を見ない』。
    略称表にある語はそのまま通す。表にない2文字は、ひらがなだけなら一般語とみなして弾く。
    それ以外(獣王・吉宗)は正式名の先頭か語尾に当たるときだけ通す。
    """
    key = model_alias.norm(tok)
    if len(key) > 2 or key in _ALIAS_KEYS:
        return False
    if _HIRAGANA_ONLY.match(key):
        return True
    return not all(model_alias.norm(n).startswith(key) or model_alias.norm(n).endswith(key) for n in hits)


def _norm_with_index(text: str) -> tuple[str, list[int]]:
    """model_alias.norm と同じ表記ゆれの吸収をしつつ、各文字が元の文字列の何文字目かを返す。"""
    chars, idx = [], []
    for i, ch in enumerate(text):
        for c in model_alias.norm(ch):
            chars.append(c)
            idx.append(i)
    return "".join(chars), idx


def _mask_full_names(text: str, names: list[str]) -> tuple[str, list[str]]:
    """本文に丸ごと書かれた正式名を先に取り、その範囲を「、」に置き換える。

    長い名前から順に取るので、『甲鉄城のカバネリ 海門(うなと)決戦』と書いてあれば、それを含む
    短い『甲鉄城のカバネリ』は(別の場所に書かれていない限り)拾わない。範囲を消すので、
    「-30」の差枚扱いや、「ZERO」のような断片が残って別機種に当たることもない。
    """
    normed, idx = _norm_with_index(text)
    cands = sorted(
        ((model_alias.norm(n), n) for n in names if len(model_alias.norm(n)) >= _MIN_FULL_NAME_LEN),
        key=lambda kn: -len(kn[0]),
    )
    spans: list[tuple[int, int]] = []
    found: list[str] = []
    span_name: dict[tuple[int, int], str] = {}
    for key, name in cands:
        start = normed.find(key)
        while start != -1:
            end = start + len(key)
            # 名前の直後に版数・型番がくっついているときは別機種なので取らない
            # (「からくりサーカス2」の本文から『からくりサーカス』、「マイジャグラーVI」から『マイジャグラーV』)。
            # 空白や括弧は norm で消えるので、見るのは元の文字列の次の1文字。
            at = idx[end - 1] + 1
            nxt = text[at] if at < len(text) else ""
            glued = bool(nxt) and (
                (nxt.isdigit() and not key[-1].isdigit())
                or (nxt.isascii() and nxt.isalpha() and key[-1].isascii() and key[-1].isalpha())
            )
            overlap = any(start < e and s < end for s, e in spans)
            if not glued and not overlap:
                spans.append((start, end))
                span_name[(start, end)] = name
            start = normed.find(key, start + 1)
    # 取った範囲は、本文での並びを保てるよう目印(私用領域の文字+通し番号)に置き換える
    out = list(text)
    for n, span in enumerate(sorted(spans)):
        first, last = idx[span[0]], idx[span[1] - 1]
        for i in range(first, last + 1):
            out[i] = ""
        out[first] = f"、{_MARK}{n}{_MARK}、"
        found.append(span_name[span])
    return "".join(out), found


def match_models(line: str, names: list[str]) -> tuple[list[str], list[str]]:
    matched, unresolved = [], []

    def take(r):
        for n in r["names"]:
            if n not in matched:
                matched.append(n)

    text, full = _mask_full_names(unicodedata.normalize("NFKC", line), names)
    for chunk in _SPLIT.split(text):
        if chunk.startswith(_MARK):
            take({"names": [full[int(chunk.strip(_MARK))]]})
            continue
        whole = _clean(chunk)
        if whole is None:
            continue
        r = model_alias.resolve_part(whole, names)
        if r["status"] == "ok" and not _loose_short_match(whole, r["names"]):
            take(r)
            continue
        for piece in _PARTICLES.split(whole):
            tok = _clean(piece)
            if tok is None:
                continue
            r = model_alias.resolve_part(tok, names)
            if r["status"] == "ok" and not _loose_short_match(tok, r["names"]):
                take(r)
            elif r["status"] == "ambiguous":
                unresolved.append(tok)
    return matched, unresolved


def match_units(line: str, numbers: set[int]) -> list[int]:
    t = unicodedata.normalize("NFKC", line)
    t = re.sub(r"[+\-−]\s*[\d,]+", " ", t)  # 差枚(+1,505 など)を台番号と取り違えない
    t = re.sub(r"\d+\s*[/／]\s*\d+", " ", t)  # 「超え20/30」「1/299」
    t = re.sub(r"\d[\d,]*\s*(?:G|g|台|日|回|枚|%|位)", " ", t)
    out = []
    for m in _UNIT.findall(t):
        n = int(m)
        if n in numbers and n not in out:
            out.append(n)
    return out


# 避ける機種の行は、行頭のラベル「避ける:」「避ける機種:」「**避ける:**」に限る。
# 「外挿は避けるべき」のような動詞の「避ける」を拾わないため(2026-10-29 ARROW)。
_AVOID_LABEL = re.compile(r"^[\s\-*>]*\**\s*避ける(?:機種|台|候補)?\s*\**\s*[:：]")
# 表の見立てのセルが「**避ける。**」のときも避ける行とする(2026-10-14 みとや)。
_AVOID_CELL = re.compile(r"^\**\s*避ける\s*[。.:：]?\s*\**\s*(?:$|[^側候べ])")
# 文末が打ち消し・見送りの文は、その文の機種・台を推さない(2026-10-29 金時京急「…固定を見込まない」)。
# 日本語は文末で肯否が決まるので、「絞る根拠はなく、分散先はカバネリ海門」は推す側に残る。
# 「避け」を含む文も推さない(ラベルでない「避ける」は避ける行にもしない)。
_NEGATED_END = re.compile(r"(?:ない|なし|無い|無し|ません|控える|見送る|見送り)$")
_SENT_TRAIL = "。．.）)」』】*  "
# 下のジャグラー候補表を指すだけの節。表は jug_units で別に採点するので、その節の機種は推さない
# (2026-10-29 金時東口「ジャグラー候補(…ガールズ 642、ミスター 700)を開店後のRBで確認する」)。
_JUG_TABLE_REF = re.compile(r"ジャグラー候補|下表")


def is_avoid_line(line: str) -> bool:
    if _AVOID_LABEL.match(line):
        return True
    if line.lstrip().startswith("|"):
        return any(_AVOID_CELL.match(c.strip()) for c in line.strip().strip("|").split("|")[1:])
    return False


def _clauses(sent: str) -> list[str]:
    """読点で節に分ける。括弧の中の読点(「(ガールズ 642、ミスター 700)」)では切らない。"""
    out, buf, depth = [], "", 0
    for ch in sent:
        if ch in "(（「『【[":
            depth += 1
        elif ch in ")）」』】]" and depth:
            depth -= 1
        if ch in "、，," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    return out + [buf]


def push_parts(line: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """判断の行を ([(節, 機種も拾うか)], 推さない文) に振り分ける。

    推さない文: 文末が打ち消し・見送り、または「避け」を含む文。機種も台番号も拾わない。
    ジャグラー候補表を指す節は台番号だけ拾う(jug_units と重なれば後で除く)。
    """
    parts, skip = [], []
    for sent in re.split(r"(?<=[。．])", line):
        if not sent.strip():
            continue
        if "避け" in sent or _NEGATED_END.search(sent.strip().rstrip(_SENT_TRAIL)):
            skip.append(sent)
            continue
        parts += [(clause, not _JUG_TABLE_REF.search(clause)) for clause in _clauses(sent)]
    return parts, skip


def _sections(md: str) -> list[tuple[str, list[str]]]:
    """## 見出しごとに本文行をまとめる(### は親の ## に含める)。"""
    out: list[tuple[str, list[str]]] = []
    for line in md.splitlines():
        if line.startswith("## "):
            out.append((line[3:].strip(), []))
        elif out:
            out[-1][1].append(line)
    return out


def extract(md: str, target_date: str) -> list[dict]:
    """予測文書から、ホールごとの名指しを取り出す。"""
    specs: dict[str, dict] = {}
    cache: dict[str, tuple[str | None, dict[str, set[int]]]] = {}

    def spec(hall: str) -> dict | None:
        if hall not in cache:
            try:
                cache[hall] = roster(hall, target_date)
            except sqlite3.Error:
                cache[hall] = (None, {})
        if cache[hall][0] is None:
            return None
        return specs.setdefault(
            hall,
            {
                "hall": hall,
                "target_date": target_date,
                "data_asof": cache[hall][0],
                "picks": {"models": [], "avoid_models": [], "units": [], "jug_units": []},
                "unresolved": [],
                # 判断の行にあるが、打ち消しの文やジャグラー候補表を指す文なので推さなかった名前(確認用)
                "skipped": [],
            },
        )

    for title, lines in _sections(md):
        if "ジャグラー候補" in title:
            for line in lines:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 3 or set(cells[0]) <= set("-: "):
                    continue
                hall = hall_of(cells[0])
                s = spec(hall) if hall else None
                if s is None:
                    continue
                numbers = set().union(*cache[hall][1].values())
                for u in match_units(cells[-1].split("。")[0], numbers):
                    if u not in s["picks"]["jug_units"]:
                        s["picks"]["jug_units"].append(u)
            continue
        hall = hall_of(title)
        s = spec(hall) if hall else None
        if s is None:
            continue
        by_name = cache[hall][1]
        names = list(by_name)
        numbers = set().union(*by_name.values())
        in_judgement = False
        for line in lines:
            if line.startswith("### "):
                in_judgement = "判断" in line
                continue
            stripped = line.strip()
            is_judgement = in_judgement or stripped.startswith(("判断", "**判断", "- 判断"))
            if is_avoid_line(stripped):
                models, unres = match_models(stripped, names)
                s["picks"]["avoid_models"] += [m for m in models if m not in s["picks"]["avoid_models"]]
                s["unresolved"] += unres
            elif is_judgement:
                parts, skip = push_parts(stripped)
                for part, take_models in parts:
                    models, unres = match_models(part, names)
                    if take_models:
                        s["picks"]["models"] += [m for m in models if m not in s["picks"]["models"]]
                        s["unresolved"] += unres
                    elif models:
                        s["skipped"].append({"text": part.strip(), "models": models, "units": []})
                    s["picks"]["units"] += [u for u in match_units(part, numbers) if u not in s["picks"]["units"]]
                for sent in skip:
                    models, _ = match_models(sent, names)
                    units = match_units(sent, numbers)
                    if models or units:
                        s["skipped"].append({"text": sent.strip(), "models": models, "units": units})
    for s in specs.values():
        s["picks"]["models"] = [m for m in s["picks"]["models"] if m not in s["picks"]["avoid_models"]]
        # 「判断」の行が下のジャグラー候補表を指しているだけの台は、ジャグ候補として1回だけ数える。
        s["picks"]["units"] = [u for u in s["picks"]["units"] if u not in s["picks"]["jug_units"]]
        s["unresolved"] = sorted(set(s["unresolved"]))
    return [s for s in specs.values() if any(s["picks"].values())]


# ---------------------------------------------------------------- 凍結


def timing_of(frozen_at: datetime, target_date: str) -> str:
    day = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    if frozen_at < day.replace(hour=OPEN_HOUR):
        return "pre_open"
    if frozen_at < day + timedelta(days=1):
        return "same_day"
    return "after"


def _digest(obj: dict) -> str:
    body = {k: obj[k] for k in ("hall", "target_date", "picks", "frozen_at")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def freeze(
    spec: dict,
    frozen_at: datetime,
    basis: str,
    source_doc: str,
    pred_dir: Path = PRED_DIR,
    revision: str | None = None,
    reason: str = "",
) -> Path | None:
    """1ホール×1日の名指しを凍結する。既にあれば上書きしない(None を返す)。"""
    pred_dir.mkdir(parents=True, exist_ok=True)
    original_id = f"{spec['target_date']}__{HALL_KEY.get(spec['hall'], spec['hall'])}"
    pid = f"{original_id}__{revision}" if revision else original_id
    path = pred_dir / f"{pid}.json"
    if path.exists():
        return None
    obj = {
        "prediction_id": pid,
        **spec,
        "source_doc": source_doc,
        "frozen_at": frozen_at.isoformat(timespec="seconds"),
        "timing_basis": basis,
        "timing": timing_of(frozen_at, spec["target_date"]),
        "result": None,
    }
    if revision:
        obj.update(revision_of=original_id, revision=revision, revision_reason=reason)
    obj["digest"] = _digest(obj)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    with (pred_dir / LEDGER_NAME).open("a", encoding="utf-8") as fh:
        rec = {"prediction_id": pid, "digest": obj["digest"], "frozen_at": obj["frozen_at"], "timing": obj["timing"]}
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def freeze_rb_auto(
    hall: str, target_date: str, picks: dict, extra: dict, frozen_at: datetime, pred_dir: Path = PRED_DIR
) -> Path | None:
    """人の予測と独立したRB自動候補を一度だけ凍結する。"""
    pred_dir.mkdir(parents=True, exist_ok=True)
    pid = f"{target_date}__{HALL_KEY.get(hall) or RB_AUTO_EXTRA_KEYS.get(hall, hall)}__rbauto"
    path = pred_dir / f"{pid}.json"
    if path.exists():
        return None
    obj = {
        "prediction_id": pid,
        "hall": hall,
        "target_date": target_date,
        "picks": picks,
        "frozen_at": frozen_at.isoformat(timespec="seconds"),
        "timing": timing_of(frozen_at, target_date),
        "timing_basis": "frozen_at",
        "source": "rb_auto",
        "data_asof": extra.get("data_asof"),
        "lag_days": extra.get("lag_days"),
        "rb_auto": extra,
        "result": None,
    }
    obj["digest"] = _digest(obj)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    with (pred_dir / LEDGER_NAME).open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"prediction_id": pid, "digest": obj["digest"], "frozen_at": obj["frozen_at"], "timing": obj["timing"]},
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


RB_DIP_SUFFIX = {"rb_dip": "rbdip", "rb_dip_ctrl": "rbdipctrl"}


def freeze_rb_dip(
    hall: str,
    target_date: str,
    picks: dict,
    extra: dict,
    frozen_at: datetime,
    kind: str,
    pred_dir: Path = PRED_DIR,
) -> Path | None:
    """長期が強い台の直近の凹み(rb_dip)と、対照の好調な台(rb_dip_ctrl)を、別エントリで一度だけ凍結する。"""
    if kind not in RB_DIP_SUFFIX:
        raise ValueError(f"kind は rb_dip / rb_dip_ctrl のみ: {kind}")
    pred_dir.mkdir(parents=True, exist_ok=True)
    pid = f"{target_date}__{HALL_KEY.get(hall) or RB_AUTO_EXTRA_KEYS.get(hall, hall)}__{RB_DIP_SUFFIX[kind]}"
    path = pred_dir / f"{pid}.json"
    if path.exists():
        return None
    obj = {
        "prediction_id": pid,
        "hall": hall,
        "target_date": target_date,
        "picks": picks,
        "frozen_at": frozen_at.isoformat(timespec="seconds"),
        "timing": timing_of(frozen_at, target_date),
        "timing_basis": "frozen_at",
        "source": kind,
        "data_asof": extra.get("data_asof"),
        "lag_days": extra.get("lag_days"),
        "rb_dip": extra,
        "result": None,
    }
    obj["digest"] = _digest(obj)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    with (pred_dir / LEDGER_NAME).open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "prediction_id": pid,
                    "digest": obj["digest"],
                    "frozen_at": obj["frozen_at"],
                    "timing": obj["timing"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return path


def target_of_doc(path: Path) -> str:
    m = DOC_NAME.search(path.name)
    if not m:
        raise ValueError(f"{path.name} は YYYY-MM-DD-prediction.md ではない")
    return "".join(m.groups())


def git_first_commit(path: Path) -> datetime | None:
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%cI", "--", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    return datetime.fromisoformat(out[-1]).astimezone(JST) if out else None


def freeze_doc(
    path: Path,
    frozen_at: datetime,
    basis: str,
    pred_dir: Path = PRED_DIR,
    revision: str | None = None,
    halls: list[str] | None = None,
    reason: str = "",
) -> list[str]:
    if revision is not None and not re.fullmatch(r"rev[0-9]+", revision):
        raise ValueError("revision は rev1 形式で指定してください")
    if revision is not None and not halls:
        raise ValueError("revision には --hall が1つ以上必要です")
    selected = set()
    for name in halls or []:
        hall = name if name in HALLS else hall_of(name)
        if hall is None:
            raise ValueError(f"未知のホール名: {name}")
        selected.add(hall)
    target = target_of_doc(path)
    try:
        source = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        source = path.name
    msgs = []
    for spec in extract(path.read_text(encoding="utf-8"), target):
        if halls is not None and spec["hall"] not in selected:
            continue
        if revision:
            hall = spec["hall"]
            original_id = f"{target}__{HALL_KEY.get(hall, hall)}"
            original_path = pred_dir / f"{original_id}.json"
            revised_path = pred_dir / f"{original_id}__{revision}.json"
            if not original_path.exists():
                rejection = "元版が存在しない"
            elif json.loads(original_path.read_text(encoding="utf-8")).get("result") is not None:
                rejection = "元版は採点済み"
            elif revised_path.exists():
                rejection = "同名の改訂が既に存在する"
            elif timing_of(frozen_at, target) == "after":
                rejection = "対象日の翌日以降"
            else:
                rejection = None
            if rejection:
                msgs.append(f"改訂拒否 {target} {hall}: {rejection}")
                continue
        written = freeze(spec, frozen_at, basis, source, pred_dir, revision=revision, reason=reason)
        p = spec["picks"]
        msgs.append(
            f"{'凍結' if written else '既存のためスキップ'} {target} {spec['hall']}: 機種{len(p['models'])} "
            f"避ける{len(p['avoid_models'])} 台{len(p['units'])} ジャグ{len(p['jug_units'])} 未照合{len(spec['unresolved'])}"
        )
        for sk in spec.get("skipped", []):
            msgs.append(
                f"  推さなかった文({spec['hall']}): {'・'.join(sk['models'] + [str(u) for u in sk['units']])} ← {sk['text'][:60]}"
            )
    return msgs


# ---------------------------------------------------------------- 採点


def _edge(rows: list[tuple[int, str, float]], day_mean: float, sign: float = 1.0) -> dict | None:
    if not rows:
        return None
    mean = sum(d for _, _, d in rows) / len(rows)
    return {"n_machines": len(rows), "mean_diff": round(mean, 1), "edge": round(sign * (mean - day_mean), 1)}


def score(obj: dict) -> dict:
    if obj.get("result") is not None:
        raise ValueError("採点済み。作り直しは禁止。")
    if _digest(obj) != obj["digest"]:
        raise ValueError(f"{obj['prediction_id']}: 凍結後に書き換えられている(digest不一致)")
    with _ro(obj["hall"]) as con:
        rows = [
            (int(n), name, float(d))
            for n, name, d in con.execute(
                "SELECT machine_number, machine_name, diff_coins_normalized FROM machine_detailed_results "
                "WHERE date = ? AND diff_coins_normalized IS NOT NULL",
                (obj["target_date"],),
            )
        ]
        if not rows:
            raise ValueError(f"{obj['target_date']} {obj['hall']} のデータがDBにまだ無い")
        day_mean = sum(d for _, _, d in rows) / len(rows)
        p = obj["picks"]
        models, avoid = set(p["models"]), set(p["avoid_models"])
        units, jug = set(p["units"]), set(p["jug_units"])
        obj["result"] = {
            "day_mean": round(day_mean, 1),
            "universe_size": len(rows),
            "models": _edge([r for r in rows if r[1] in models], day_mean),
            "avoid_models": _edge([r for r in rows if r[1] in avoid], day_mean, sign=-1.0),
            "units": _edge([r for r in rows if r[0] in units], day_mean),
            "jug_units": _edge([r for r in rows if r[0] in jug], day_mean),
            "missing_units": sorted((units | jug) - {r[0] for r in rows}),
            "missing_models": sorted((models | avoid) - {r[1] for r in rows}),
        }
        try:
            obj["result"]["rb"] = rb_result(con, p, obj["target_date"])
        except Exception as exc:
            obj["result"]["rb"] = None
            obj["result"]["rb_error"] = str(exc)
        try:
            obj["result"]["rb_s1"] = rb_s1_result(con, p, obj["target_date"])
        except Exception as exc:
            obj["result"]["rb_s1"] = None
            obj["result"]["rb_s1_error"] = str(exc)
        if obj.get("source") == "rb_auto":
            try:
                obj["result"]["rb_machine"] = rb_machine_result(
                    con, p, obj["target_date"], family_offsets(DB_DIR, obj["target_date"])
                )
            except Exception as exc:
                obj["result"]["rb_machine"] = None
                obj["result"]["rb_machine_error"] = str(exc)
            try:
                from backtest.rb_candidates import day_level

                obj["result"]["rb_day"] = {
                    "flag": (obj.get("rb_auto") or {}).get("day_flag"),
                    "y_level": day_level(con, obj["target_date"]),
                }
            except Exception as exc:
                obj["result"]["rb_day"] = {"flag": (obj.get("rb_auto") or {}).get("day_flag"), "y_level": None}
                obj["result"]["rb_day_error"] = str(exc)
    return obj


def score_due(pred_dir: Path = PRED_DIR) -> list[str]:
    msgs = []
    for path in sorted(pred_dir.glob("*__*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("result") is not None:
            continue
        try:
            score(obj)
        except (ValueError, sqlite3.Error) as e:
            msgs.append(f"未採点 {path.name}: {e}")
            continue
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        r = obj["result"]
        msgs.append(
            f"採点 {path.name}: "
            + " / ".join(f"{k} {r[k]['edge']:+.0f}" for k in ("models", "avoid_models", "units", "jug_units") if r[k])
        )
    return msgs


def rescore_rb(pred_dir: Path = PRED_DIR) -> list[str]:
    """既採点ファイルに欠けているRB系列だけを独立に追加する。"""
    msgs = []
    for path in sorted(pred_dir.glob("*__*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        result = obj.get("result")
        needed = [k for k in ("rb", "rb_s1") if k not in (result or {})]
        if obj.get("source") == "rb_auto" and result and "rb_machine" not in result:
            needed.append("rb_machine")
        if not result or not needed:
            continue
        try:
            with _ro(obj["hall"]) as con:
                has_day = con.execute(
                    "SELECT 1 FROM machine_detailed_results WHERE date = ? LIMIT 1", (obj["target_date"],)
                ).fetchone()
                if not has_day:
                    msgs.append(f"スキップ {path.name}: 対象日の行がない")
                    continue
                added = []
                for key, calculate in (("rb", rb_result), ("rb_s1", rb_s1_result)):
                    if key in result:
                        continue
                    try:
                        result[key] = calculate(con, obj["picks"], obj["target_date"])
                        added.append(key)
                    except (sqlite3.Error, ValueError, ArithmeticError) as exc:
                        msgs.append(f"スキップ {path.name}: {key}採点失敗 ({exc})")
                if "rb_machine" in needed:
                    try:
                        result["rb_machine"] = rb_machine_result(
                            con, obj["picks"], obj["target_date"], family_offsets(DB_DIR, obj["target_date"])
                        )
                        added.append("rb_machine")
                    except Exception as exc:
                        result["rb_machine"] = None
                        result["rb_machine_error"] = str(exc)
                        added.append("rb_machine")
                    if "rb_day" not in result:
                        try:
                            from backtest.rb_candidates import day_level

                            level = day_level(con, obj["target_date"])
                        except Exception as exc:
                            level = None
                            result["rb_day_error"] = str(exc)
                        result["rb_day"] = {"flag": (obj.get("rb_auto") or {}).get("day_flag"), "y_level": level}
        except sqlite3.Error as exc:
            msgs.append(f"スキップ {path.name}: DBを読めない ({exc})")
            continue
        if not added:
            continue
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        msgs.append(f"RB採点 {path.name}: {', '.join(added)}")
    return msgs


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ex = sub.add_parser("extract", help="予測文書から名指しを抜き出して表示する(凍結しない)")
    p_ex.add_argument("doc")
    p_fr = sub.add_parser("freeze-doc", help="予測文書の名指しを今の時刻で凍結する(書いた直後に実行)")
    p_fr.add_argument("doc")
    p_fr.add_argument("--revision")
    p_fr.add_argument("--hall", action="append", nargs="+", dest="halls")
    p_fr.add_argument("--reason", default="")
    sub.add_parser("backfill", help="未凍結の過去の予測文書を git 初出時刻つきで取り込む")
    sub.add_parser("score-due", help="対象日のデータがある未採点の予測を採点する")
    sub.add_parser("rescore-rb", help="採点済み台帳へRB採点だけを後付けする")
    args = parser.parse_args(argv)

    if args.cmd == "extract":
        path = Path(args.doc).resolve()
        print(json.dumps(extract(path.read_text(encoding="utf-8"), target_of_doc(path)), ensure_ascii=False, indent=1))
    elif args.cmd == "freeze-doc":
        try:
            halls = [hall for group in args.halls for hall in group] if args.halls else None
            messages = freeze_doc(
                Path(args.doc).resolve(),
                datetime.now(JST),
                "frozen_at",
                revision=args.revision,
                halls=halls,
                reason=args.reason,
            )
        except ValueError as exc:
            p_fr.error(str(exc))
        for m in messages:
            print(m)
    elif args.cmd == "backfill":
        for path in sorted(REVIEWS_DIR.glob("*-prediction.md")):
            when = git_first_commit(path)
            if when is None:
                print(f"{path.name}: git 未登録のため取り込まない(コミット後に freeze-doc を使う)")
                continue
            for m in freeze_doc(path, when, "git_first_commit"):
                print(m)
    elif args.cmd == "score-due":
        for m in score_due():
            print(m)
    elif args.cmd == "rescore-rb":
        for m in rescore_rb():
            print(m)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
