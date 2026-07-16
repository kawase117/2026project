---
name: env-check
description: セッション冒頭でpython実行パス・DB接続を点検する軽量スキル。python/python3のWindows Storeエイリアス誤爆や、分析時間に環境トラブルが食い込むのを防ぐために使う。
---

# Env Check Skill

## トリガー
- セッション開始直後、コード実行やDBアクセスを含む作業に入る前
- 「pythonが見つからない」「モジュールがない」等のエラーに遭遇したとき

## 背景
`python`/`python3`コマンドがWindows Storeのダミーエイリアスに解決されて失敗する事象が複数セッションで再発していた(559c52dc, 0048da32等)。都度その場で `py -3` やvenvパスへのフォールバックを試行しており、これが分析作業の集中を削いでいた(詳細: `document/mirror_evidence.md` セクション4)。CLAUDE.mdにも恒久的な固定ルールを追記済み。

## やること
1. `venv\Scripts\python.exe --version` が通るか確認する(通らなければ `py -3 -m venv venv` で作り直しを提案)
2. DB接続確認: `database/`配下の主要DBファイルへの読み取りアクセスを軽く確認する(実際のクエリは投げず、ファイル存在とサイズ程度)
3. 問題があればこの時点で解決し、以降のセッション中で `python`/`python3` の裸コマンドは使わず、必ず `venv\Scripts\python.exe` または `py -3` を使う

## 出力
- 「環境OK、venv経由で実行可能」または「要修正: (具体的な問題)」の一行サマリ
- 問題があった場合のみ詳細を報告し、無ければセッション冒頭で長々と報告しない
