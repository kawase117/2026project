"""Re-export module for backward compatibility. Use split modules directly."""

from ml.experiments._pipeline_config import (
    WINDOWS,
    TARGET_COLUMNS,
    META_COLUMNS,
    FORECAST_EXCLUDED_COLUMNS,
    ABLATION_WORST_FEATURE_KEYWORDS,
    ABLATION_WORST_RECENCY_PREFIXES,
    ABLATION_WORST_STREAK_PREFIXES,
    ABLATION_WORST_RATE_KEYWORDS,
    ABLATION_MOMVOL_FEATURE_PREFIXES,
    ABLATION_SAME_DAY_OF_MONTH_PREFIXES,
    ABLATION_SAME_WEEKDAY_PREFIXES,
    ABLATION_RANK1_SPECIAL_PREFIXES,
    ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS,
    ABLATION_EVENT_FEATURE_COLUMNS,
    FEATURE_CATALOG_SECTION_ORDER,
    PLANNED_MACHINE_NUMBER_FEATURES,
    PipelineConfig,
    DatasetSpec,
    FoldWindow,
    FoldEvaluation,
    FoldTargetEncoder,
)

from ml.experiments._pipeline_cv import (
    ExpandingWindowSplitter,
    SlidingWindowSplitter,
)

from ml.experiments._pipeline_features import (
    StoreOptimizedFeatureBuilder,
    _render_overview_feature_catalog_markdown,
)

from ml.experiments._pipeline_engine import (
    StoreOptimizedTrainingEngine,
)

__all__ = [
    # Constants
    "WINDOWS",
    "TARGET_COLUMNS",
    "META_COLUMNS",
    "FORECAST_EXCLUDED_COLUMNS",
    "ABLATION_WORST_FEATURE_KEYWORDS",
    "ABLATION_WORST_RECENCY_PREFIXES",
    "ABLATION_WORST_STREAK_PREFIXES",
    "ABLATION_WORST_RATE_KEYWORDS",
    "ABLATION_MOMVOL_FEATURE_PREFIXES",
    "ABLATION_SAME_DAY_OF_MONTH_PREFIXES",
    "ABLATION_SAME_WEEKDAY_PREFIXES",
    "ABLATION_RANK1_SPECIAL_PREFIXES",
    "ABLATION_EVENT_DISTANCE_REDESIGN_COLUMNS",
    "ABLATION_EVENT_FEATURE_COLUMNS",
    "FEATURE_CATALOG_SECTION_ORDER",
    "PLANNED_MACHINE_NUMBER_FEATURES",
    # Config classes
    "PipelineConfig",
    "DatasetSpec",
    "FoldWindow",
    "FoldEvaluation",
    "FoldTargetEncoder",
    # CV splitters
    "ExpandingWindowSplitter",
    "SlidingWindowSplitter",
    # Feature builder
    "StoreOptimizedFeatureBuilder",
    # Training engine
    "StoreOptimizedTrainingEngine",
    # Reporting functions
    "_render_overview_feature_catalog_markdown",
]
