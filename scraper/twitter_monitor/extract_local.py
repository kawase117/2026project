"""Extract machine names and numbers with a local Ollama vision model.

The cloud path (extract_answers.py) is capped by a Codex usage quota that ran dry
after 137 images in one day, so the bulk backlog cannot go through it. A local
model has no quota, and measured against Codex-verified images it is accurate
enough to trust:

    qwen2.5vl:3b   9.8 s/image   recall 96.2%   precision 100.0%
    qwen2.5vl:7b  34.2 s/image   recall 93.1%   precision 100.0%

The 7B model is slower and *worse* here because only ~6 GB of the 8 GB VRAM is
free, so `ollama ps` reports a 15%/85% CPU/GPU split for it while the 3B model
fits entirely on the GPU. Model choice is therefore a flag, not a constant.

Two deliberate differences from the CLI:
  * the HTTP API is used, because `ollama run` injects terminal control codes
    into stdout that corrupt the JSON;
  * `format` carries the JSON schema so the model is constrained rather than
    merely asked to emit JSON.
"""

import argparse
import base64
import json
import sqlite3
import time
import urllib.error
import urllib.request

from config import ACCOUNTS, DB_PATH
from extract_answers import (
    SCHEMA_PATH,
    complete_date_hint,
    initialize_extractions_tables,
    store_failure,
    store_success,
    validate_extraction,
)

DEFAULT_MODEL = "qwen2.5vl:3b"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_PRIORITY_HALLS = "kamata7_kamata1,rakuen_kamata"
REQUEST_TIMEOUT = 600

PROMPT = """この画像はパチスロホールの予告・答え合わせ投稿です。
どの機種の、どの台番号に設定が入っていたかを構造化して抽出してください。
画像に根拠のある機種名と台番号だけを entries に入れ、台番号は先頭ゼロを保った文字列にしてください。

1枚の画像に複数店舗の表が並んでいることがあります。各 entry の hall_hint には
その機種が属する店舗名を、画像の表記のまま入れてください。店舗が1つだけなら全 entry に同じ値を、
読み取れなければ null を入れてください。トップレベルの hall_hint は画像全体の見出しです。

date_hint は対象営業日です。年が読めれば YYYY-MM-DD、月日だけなら M/D、読めなければ null。
年を推測してはいけません。note は「全台系」などの補足のみ、なければ null。"""


def load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def call_ollama(model: str, image_path: str, schema: dict) -> tuple[dict, str]:
    """Send one image and return the parsed response plus its raw text."""
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    payload = json.dumps(
        {
            "model": model,
            "prompt": PROMPT,
            "images": [encoded],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    raw = body.get("response", "")
    if not raw:
        raise RuntimeError("empty response from %s" % model)
    return validate_extraction(json.loads(raw)), raw


def parse_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def select_pending(connection, handles, halls, priority_halls, limit, redo_failed, max_height=None):
    """Candidate images only: prefilter.py already dropped the photographic ones."""
    selected = set(handles)
    if halls:
        hall_handles = {h for h, d in ACCOUNTS.items() if d["hall"] in halls}
        selected = selected & hall_handles if selected else hall_handles

    conditions = [
        "st.has_image = 1",
        "f.is_candidate = 1",
        "NOT EXISTS (SELECT 1 FROM extractions ok WHERE ok.image_path = ti.image_path AND ok.status = 'success')",
    ]
    parameters = []
    if max_height is not None:
        # Tall dense tables make the 3B model run away enumerating consecutive
        # numbers until it hits the token limit: measured recall 67.5% and
        # precision 82.4% even when tiled, versus 96.2%/100% below this size.
        conditions.append("f.height < ?")
        parameters.append(max_height)
    if not redo_failed:
        conditions.append("NOT EXISTS (SELECT 1 FROM extractions a WHERE a.image_path = ti.image_path)")
    if handles or halls:
        if not selected:
            return []
        conditions.append("st.handle IN (%s)" % ", ".join("?" for _ in selected))
        parameters.extend(sorted(selected))

    priority = sorted(h for h, d in ACCOUNTS.items() if d["hall"] in priority_halls)
    order = ""
    if priority:
        order = "CASE WHEN st.handle IN (%s) THEN 0 ELSE 1 END," % ", ".join("?" for _ in priority)
        parameters.extend(priority)

    sql = """
        SELECT ti.tweet_id, ti.image_path, st.handle, st.posted_at_jst
        FROM tweet_images ti
        JOIN seen_tweets st ON st.tweet_id = ti.tweet_id
        JOIN image_features f ON f.image_path = ti.image_path
        WHERE %s
        ORDER BY %s st.posted_at_jst DESC, ti.id DESC
    """ % (" AND ".join(conditions), order)
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(limit)
    return connection.execute(sql, parameters).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="ローカルOllamaのVisionモデルで画像から機種名・台番号を抽出します。")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="使用するOllamaモデル (既定: %s)" % DEFAULT_MODEL)
    parser.add_argument("--handles", help="対象アカウントをカンマ区切りで指定")
    parser.add_argument("--halls", help="config.pyのhall値で限定")
    parser.add_argument("--priority-halls", default=DEFAULT_PRIORITY_HALLS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--redo-failed", action="store_true")
    parser.add_argument("--max-height", type=int, default=None, help="この高さ以上の画像を除外します (例: 1800)")
    args = parser.parse_args()

    schema = load_schema()
    connection = sqlite3.connect(DB_PATH, timeout=60)
    initialize_extractions_tables(connection)
    try:
        connection.execute("SELECT 1 FROM image_features LIMIT 1")
    except sqlite3.OperationalError:
        print("image_features がありません。先に prefilter.py を実行してください。")
        return 1

    rows = select_pending(
        connection,
        parse_csv(args.handles),
        parse_csv(args.halls),
        parse_csv(args.priority_halls),
        args.limit,
        args.redo_failed,
        args.max_height,
    )
    print("対象 %d枚  model=%s" % (len(rows), args.model))

    ok = failed = entries = 0
    started = time.time()
    try:
        for index, (tweet_id, image_path, handle, posted_at) in enumerate(rows, 1):
            try:
                parsed, raw = call_ollama(args.model, image_path, schema)
                complete_date_hint(parsed.get("date_hint"), posted_at)
                store_success(connection, tweet_id, image_path, handle, posted_at, parsed, raw)
                entries += sum(len(entry.get("machine_numbers") or []) for entry in parsed.get("entries") or [])
                ok += 1
            except (urllib.error.URLError, ConnectionError) as error:
                print("  Ollamaに接続できません: %s" % error)
                return 1
            except Exception as error:
                store_failure(connection, tweet_id, image_path, handle, error)
                failed += 1
            connection.commit()
            if index % 25 == 0:
                rate = (time.time() - started) / index
                remaining = (len(rows) - index) * rate / 3600
                print(
                    "  %d/%d  成功%d 失敗%d 台番号%d件  %.1f秒/枚  残り約%.1f時間"
                    % (index, len(rows), ok, failed, entries, rate, remaining),
                    flush=True,
                )
    except KeyboardInterrupt:
        connection.commit()
        print("\n中断しました。取得済みは保存されています。")
    finally:
        connection.close()

    elapsed = time.time() - started
    print(
        "\n完了: 成功%d 失敗%d 台番号%d件  所要%.1f分 (%.1f秒/枚)"
        % (ok, failed, entries, elapsed / 60, elapsed / max(ok + failed, 1))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
