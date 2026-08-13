"""事前登録（pre-registration）フォーマットの定義・検証・凍結。

思想:
    このプロジェクトの instinct は 1400 本近くあるが confirmed=0。原因は
    「過去データを見て見つけたルール」を「同じ過去データ」で確認する
    自己参照ループから抜けられていないこと。

    事前登録は、その自己参照を切るための仕組み。ルールを *先に* 宣言して
    ハッシュで凍結し、それ以降パラメータをいじれなくする。バックテストで
    落ちたルールは落ちたまま記録し、当てにいって書き換えることを禁じる。

    なおバックテストは confirmed にはならない（in-sample の呪い）。これは
    実弾を撃つ前に「未来データに効かないルール」を落とすフィルタである。
    確証はフォワードテスト（未来の日付を事前登録して待つ）でのみ得られる。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ルールが参照してよい台属性。ここに無い列は eligibility に書けない。
ALLOWED_FILTER_FIELDS = {
    "jug_flag",
    "hana_flag",
    "oki_flag",
    "bt_flag",
    "machine_name",
    "last_digit",
    "is_zorome",
    "section",
    "rank_from_aisle",
    "rank_from_min",
    "rank_from_max",
}

ALLOWED_SCORES = {
    "hist_mean_diff",  # lookback 期間の平均差枚
    "hist_hit104_rate",  # lookback 期間の機械割104%超え率
    "hist_mean_rb_prob",  # lookback 期間の平均RB確率（生値。機種横断だと機種差を拾う）
    "hist_mean_rb_prob_model_z",  # 同上を機種内標準化してから平均（機種差を除去）
    "hist_model_gratio_mean_diff",  # 機種粒度: G比（機種平均回転数/プール平均回転数）×平均差枚
    "none",  # スコアリングせず eligible 全体（＝フィルタのみの効果を見る）
}

# selection_unit の許容値。"machine_number"（既定）は台単位で選ぶ通常のルール。
# "machine_model" は機種単位でスコアし、該当機種の設置台を全部買うルール
# （例: k7_monday_model_gratio_top2）。
ALLOWED_SELECTION_UNITS = {"machine_number", "machine_model"}


@dataclass
class PreRegistration:
    """1本の予測ルールの事前登録。

    Attributes:
        rule_id: 一意な識別子。ファイル名と一致させる。
        hall: db/<hall>.db のホール名。
        hypothesis: 何を主張しているかを1文で。後から読んで意味が分かること。
        source_instinct: 根拠となった instinct の id（自己参照の出所を明示する）。
        universe: 比較の母集団。「このルールが無ければ選んでいたであろう台の集合」。
            例: ジャグ全台。baseline（同日平均）はこの集合から計算する。
        eligibility: universe をさらに絞る条件。{field: value | [values] | {"min":..,"max":..}}
            universe と同一にすると baseline と一致しエッジが定義上ゼロになるので、
            必ず universe より狭く（または score で順位付けして）指定すること。
        entry_days: エントリーする日の条件。dd / weekday を集合で指定。空なら全日。
        score: ALLOWED_SCORES のいずれか。
        lookback_days: score 計算に使う過去日数。対象日は必ず含めない。
        min_history_days: 履歴がこの日数未満の台は選ばない。
        top_n: 1日に選ぶ台数。
        min_games: スコア計算に使う *履歴* 行に要求する回転数下限。過少稼働日を
            設定判断の材料から外すためのもの。選択時点で既知の情報しか使わない。
        min_games_today: 対象日のプールに要求する回転数下限。既定 0。
            これを 0 より大きくすると「当日どれだけ回ったか」という選択時点では
            知り得ない情報でプールを絞ることになり、結果が甘い方向に歪む。
            0 以外にするのは、その歪みを承知で感度を見るときだけ。
        eval_start / eval_end: 評価期間（YYYYMMDD）。
        success_criterion: 何をもって成功とするか。事前に書く。後から変えない。
        selection_unit: "machine_number"（既定）は台単位で選ぶ。"machine_model" は
            機種単位でスコアし、該当機種の設置台を全部買う。
        min_machines_per_model: selection_unit="machine_model" のとき、この台数
            未満しか設置されていない機種は候補から除外する。
    """

    rule_id: str
    hall: str
    hypothesis: str
    source_instinct: str
    eval_start: str
    eval_end: str
    success_criterion: str
    universe: dict[str, Any] = field(default_factory=dict)
    eligibility: dict[str, Any] = field(default_factory=dict)
    entry_days: dict[str, list[int]] = field(default_factory=dict)
    score: str = "none"
    lookback_days: int = 30
    min_history_days: int = 5
    top_n: int = 3
    min_games: int = 1000
    min_games_today: int = 0
    selection_unit: str = "machine_number"
    min_machines_per_model: int = 1

    def validate(self) -> None:
        if self.score not in ALLOWED_SCORES:
            raise ValueError(f"unknown score: {self.score!r} (allowed: {sorted(ALLOWED_SCORES)})")
        if self.selection_unit not in ALLOWED_SELECTION_UNITS:
            raise ValueError(
                f"unknown selection_unit: {self.selection_unit!r} (allowed: {sorted(ALLOWED_SELECTION_UNITS)})"
            )
        if self.min_machines_per_model < 1:
            raise ValueError("min_machines_per_model は 1 以上")
        bad = set(self.eligibility) - ALLOWED_FILTER_FIELDS
        if bad:
            raise ValueError(f"eligibility に未許可のフィールド: {sorted(bad)}")
        bad_u = set(self.universe) - ALLOWED_FILTER_FIELDS
        if bad_u:
            raise ValueError(f"universe に未許可のフィールド: {sorted(bad_u)}")
        if self.score == "none" and self.eligibility == self.universe:
            raise ValueError(
                "score='none' で eligibility == universe だとエッジが定義上ゼロになる。"
                "eligibility を universe より狭くするか、score を指定すること。"
            )
        bad_days = set(self.entry_days) - {"dd", "weekday"}
        if bad_days:
            raise ValueError(f"entry_days に未許可のキー: {sorted(bad_days)}")
        if self.top_n < 1:
            raise ValueError("top_n は 1 以上")
        if self.lookback_days < 1:
            raise ValueError("lookback_days は 1 以上")
        if not (len(self.eval_start) == len(self.eval_end) == 8):
            raise ValueError("eval_start / eval_end は YYYYMMDD 形式")
        if self.eval_start >= self.eval_end:
            raise ValueError("eval_start < eval_end であること")

    def freeze_hash(self) -> str:
        """ルール定義の凍結ハッシュ。

        hypothesis / success_criterion を含む全フィールドを対象にする。
        パラメータを1文字でも変えればハッシュが変わり、結果ファイルと
        突き合わせたときに「後から書き換えた」ことが検出できる。
        """
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def load(cls, path: str | Path) -> "PreRegistration":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        reg = cls(**data)
        reg.validate()
        return reg

    def save(self, path: str | Path) -> None:
        self.validate()
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
