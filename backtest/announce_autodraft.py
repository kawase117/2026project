"""ホール予告の半自動下ごしらえ(検出→dbmax/match-name/baserate/named-context→claims案)。

announce-prep スキルの手順 -1〜4.5 を自動実行し、`backtest/announce/<id>.json.draft` を
書き出す。**register は実行しない**(ユーザー方針: 検出・下ごしらえ・claims案の作成までは
自動、register の実行だけは都度人が確認する)。

なぜ .draft 拡張子か:
    `register` はパスに書き戻すだけで、announce_id からファイル名を決めない
    (announce.py:1098 `path.write_text(...)`)。`.json.draft` のまま register に
    渡すと変な拡張子のまま凍結されてしまうため、確認後に `.draft` を外してから
    register する運用にする(本モジュールは rename も register も行わない)。

なぜ claims の type を自動で厳密に決めないか:
    「全台系」「1/2⑤⑥」等の区別は本文の文脈次第で、zentaikei_count は n_models、
    model_named_ratio は ratio という追加の数値が要る。誤って型を確定させると
    announce-prep スキルが禁じる「自動確定」になるため、本文中に「全」「1/2」等の
    手がかりがあれば suggested として注記するだけに留め、type は最も安全な
    model_named 固定にする。人間が最終確認して直すこと。

使い方:
    venv\\Scripts\\python.exe -m backtest.announce_autodraft draft --date 20260927
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper" / "twitter_monitor"))
import hall_aliases  # noqa: E402

from backtest import announce as ann  # noqa: E402

STATE_DB = Path(__file__).resolve().parent.parent / "scraper" / "twitter_monitor" / "state.db"
DRAFT_DIR = ann.ANNOUNCE_DIR

# 既存の登録ファイルで使われているホール→slug対応(新規ホールは正規化した英数字にフォールバック)
HALL_SLUGS = {
    "マルハンメガシティ2000-蒲田7": "kamata7",
    "マルハンメガシティ2000-蒲田1": "kamata1",
    "楽園蒲田店": "rakuen",
    "レイトギャップ平和島": "heiwajima",
    "ヒロキ東口店": "hiroki",
    "みとや大森町店": "mitoya_omori",
    "ARROW池上店": "arrow",
    "金時京急蒲田店": "kinji_keikyu",
    "金時蒲田東口店": "kinji_higashiguchi",
    "ザ-シティ-ベルシティ雑色店": "zassiki",
}

LEADING_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
ZENTAIKEI_HINT_RE = re.compile(r"全(?:台|機種|[⑤⑥\d])")
RATIO_HINT_RE = re.compile(r"1/(\d)|ニブイチ|ハンブンコ")


def _slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, re.sub(r"[^0-9A-Za-z]+", "_", hall).strip("_") or "hall")


def _guess_target_date(text: str, posted_at: datetime) -> str:
    """本文先頭の「9/26」等を優先し、無ければ投稿日+1(夜投稿の通例)を使う。"""
    m = LEADING_DATE_RE.search(text[:20])
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        year = posted_at.year
        if posted_at.month == 12 and mo == 1:
            year += 1
        try:
            return date(year, mo, da).strftime("%Y%m%d")
        except ValueError:
            pass
    base = posted_at.date()
    if posted_at.hour < 12:
        return base.strftime("%Y%m%d")
    return (base + timedelta(days=1)).strftime("%Y%m%d")


def _existing_draft_or_registered(hall: str, target_date: str, handle: str) -> list[str]:
    # アカウント単位で判定する。ホール×日付だけだと、先に別アカウント(例: minnade777judge)の
    # 下書きができた時点で、本命アカウント(kawasakislot等)の予告が黙って捨てられる。
    slug = _slug(hall)
    hits = list(DRAFT_DIR.glob(f"{slug}__{target_date}__{handle}.json"))
    hits += list(DRAFT_DIR.glob(f"{slug}__{target_date}__{handle}.json.draft"))
    return [str(p.name) for p in hits]


def _fetch_recent_tweets(since_hours: int) -> list[dict]:
    con = sqlite3.connect(str(STATE_DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cutoff = (datetime.now().astimezone() - timedelta(hours=since_hours)).isoformat()
    cur.execute(
        "SELECT tweet_id, handle, tweet_text, posted_at_jst, full_text FROM seen_tweets "
        "WHERE posted_at_jst >= ? ORDER BY posted_at_jst ASC",
        (cutoff,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _build_claims(hall: str, text: str) -> tuple[list[dict], list[dict]]:
    """(confirmed_claims, needs_review) を返す。confirmed は score==1.0 のみ claims 化。"""
    matches = ann.match_machine_names(hall, text)
    confirmed = [m for m in matches if m["score"] >= 1.0]
    review = [m for m in matches if m["score"] < 1.0]

    claims = []
    for m in confirmed:
        name = m["machine_name"]
        idx = text.find(name)
        window = text[max(0, idx - 15) : idx + len(name) + 15] if idx >= 0 else ""
        hints = []
        if ZENTAIKEI_HINT_RE.search(window):
            hints.append("全台系の可能性(zentaikei_countならn_models必須/model_namedのままでも可)")
        rm = RATIO_HINT_RE.search(window)
        if rm:
            hints.append(f"1/{rm.group(1) or '2'}系の可能性(model_named_ratioならratio指定が必要)")
        note = "自動下ごしらえ: 本文の部分一致で検出。type/claims内容は要人間確認。"
        if hints:
            note += " ヒント: " + " / ".join(hints)
        claims.append({"type": "model_named", "machine_name": name, "note": note})
    return claims, review


def draft_for_date(target_date: str, since_hours: int = 30, dry_run: bool = False) -> list[dict]:
    tweets = _fetch_recent_tweets(since_hours)
    written = []
    seen_keys: set[tuple[str, str]] = set()

    for row in tweets:
        text = row.get("full_text") or row.get("tweet_text") or ""
        if not text:
            continue
        posted_raw = row["posted_at_jst"]
        try:
            posted_at = datetime.fromisoformat(posted_raw)
        except ValueError:
            continue

        halls = hall_aliases.plausible_halls(text, posted_at.date())
        halls &= set(HALL_SLUGS.keys())
        if not halls:
            continue

        guessed_date = _guess_target_date(text, posted_at)
        if guessed_date != target_date:
            continue

        for hall in halls:
            key = (hall, row["handle"])
            if key in seen_keys:
                continue
            seen_keys.add(key)

            try:
                db_max = ann.db_max_date(hall)
            except FileNotFoundError:
                continue
            if target_date <= db_max:
                continue  # 事後登録になるので候補から外す

            existing = _existing_draft_or_registered(hall, target_date, row["handle"])
            if existing:
                continue

            claims, review = _build_claims(hall, text)

            try:
                baserate = ann.baserate(hall, before=db_max, days=90, min_machines=3, pct=0.95, threshold=1800.0)
            except ValueError as e:
                baserate = {"error": str(e)}

            named_ctx = None
            if claims:
                try:
                    named_ctx = ann.named_context(
                        hall,
                        [c["machine_name"] for c in claims],
                        as_of=db_max,
                        days=30,
                        min_machines=3,
                        threshold=1800.0,
                    )
                except ValueError as e:
                    named_ctx = {"error": str(e)}

            slug = _slug(hall)
            announce_id = f"{slug}__{target_date}__{row['handle']}"
            draft = {
                "announce_id": announce_id,
                "hall": hall,
                "target_date": target_date,
                "source": {
                    "account": row["handle"],
                    "url": row.get("tweet_url") or "",
                    "posted_at": posted_at.isoformat(),
                    "kind": "予告",
                },
                "raw_text": text,
                "posted_at_note": "自動下ごしらえ(announce_autodraft.py)による生成。register前に人間の確認が必要。",
                "weakness_note": "",
                "prior_check_note": (
                    f"baserate(90日,閾値1800): {json.dumps(baserate, ensure_ascii=False)}"
                    + (f" / named_context: {json.dumps(named_ctx, ensure_ascii=False)}" if named_ctx else "")
                ),
                "zentaikei": {"metric": "gratio_mean_diff", "threshold": 1800.0, "min_machines": 3},
                "claims": claims,
                "unscored_claims": [
                    {
                        "text": f"{m['machine_name']}(部分一致score={m['score']})",
                        "reason": "match_machine_namesのあいまい照合(score<1.0)。自動確定しない。",
                        "frozen_scoring_procedure": "",
                    }
                    for m in review
                ],
                "needs_manual_review": True,
                "no_confirmed_machines": not claims,
                "result": None,
                "announce_digest": None,
            }

            out_path = DRAFT_DIR / f"{announce_id}.json.draft"
            if not dry_run:
                out_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append({"path": str(out_path), "hall": hall, "n_claims": len(claims), "n_review": len(review)})

    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ホール予告の半自動下ごしらえ(検出→下ごしらえ→claims案)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft", help="指定target_dateの予告候補を検出しdraftを書き出す")
    p_draft.add_argument("--date", required=True, help="target_date (YYYYMMDD)")
    p_draft.add_argument("--since-hours", type=int, default=30, help="何時間前までのツイートを見るか")
    p_draft.add_argument("--dry-run", action="store_true", help="ファイルを書かず検出結果だけ表示")

    args = p.parse_args(argv)

    if args.cmd == "draft":
        results = draft_for_date(args.date, since_hours=args.since_hours, dry_run=args.dry_run)
        if not results:
            print(f"target_date={args.date}: 検出された新規予告候補は無し", file=sys.stderr)
        for r in results:
            flag = "claims空(手動補完必須)" if r["n_claims"] == 0 else f"claims={r['n_claims']}件"
            print(f"[{r['hall']}] {r['path']} ({flag}, review候補={r['n_review']}件)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
