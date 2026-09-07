#!/usr/bin/env bash
# 蒲田7(9/4-9/5)とARROW池上(9/5-9/6)の欠落を埋める。
#
# 403 は数時間持続するので、待ってから試し、失敗したら間隔を空けて再試行する。
# 範囲は 8/30-9/6 と広めに渡すが、JSON がある日はスクレイパー側で開かれない
# （2026-09-07 に入れた変更）ので、実際に取りに行くのは欠けている4日だけ。
# この実行はその変更の実地確認も兼ねる。
set -u
cd "$(dirname "$0")"
PY=../venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8

run_hall () {
  local config="$1" label="$2"
  "$PY" -u anaslo_scraper_auto_multi.py --config "$config" \
      --start-date 20260830 --end-date 20260906 2>&1 \
    | grep -E "SKIP|\[OK\] 2026|WARN\]|ERROR\]|ABORT|成功: |失敗: "
  return 0
}

blocked () { grep -q "ABORT\|403" "$1"; }

echo "[$(date +%H:%M)] 最初の待機 (90分)"
sleep 5400

for attempt in 1 2 3; do
  echo ""
  echo "############ 試行 $attempt  [$(date +%H:%M)] ############"
  log=/tmp/fill_k7_$attempt.log
  run_hall hall_probe_k7.json "蒲田7" | tee "$log"
  sleep 240
  log2=/tmp/fill_arrow_$attempt.log
  run_hall hall_probe_arrow.json "ARROW池上" | tee "$log2"

  if ! blocked "$log" && ! blocked "$log2"; then
    echo "[$(date +%H:%M)] 両ホールとも遮断なし。終了"
    break
  fi
  if [ "$attempt" -lt 3 ]; then
    echo "[$(date +%H:%M)] 遮断された。60分待って再試行"
    sleep 3600
  fi
done

echo ""
echo "=== 最終状態 ==="
for h in マルハンメガシティ2000-蒲田7 arrow池上店; do
  echo "--- $h ---"
  ls "../data/$h" 2>/dev/null | grep 202609 | sort
done
