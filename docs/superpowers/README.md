# Superpowers Documentation

Documentation of advanced analytical capabilities and implementations in the Pachinko Analyzer system.

---

## 2026-04-23 Cross-Metric Validation

A comprehensive analysis system to validate statistical hypotheses across multiple metrics and time periods.

### 計算方法解説書 (Explanation Guide)

**File:** `explanations/2026-04-23-cross-metric-validation-calculations.md`

**Audience:** Other LLMs, new developers, business stakeholders

**Purpose:** Understand what cross-metric validation does, why it matters, and how calculations work

**Size:** 804 lines

**Key Topics:**
- Relative performance analysis (相対パフォーマンス分析)
- Percentile-based group splitting with customizable ratios
- Consistency scoring across multiple training periods (6月/3月/1月)
- Statistical interpretation of results
- Validation workflow and data flow

**How to use:** Read this document first to understand the conceptual framework and why cross-metric validation is valuable for pachi-slo analysis.

---

### コード仕様書 (Code Specification)

**File:** `specifications/2026-04-23-cross-metric-validation-code-spec.md`

**Audience:** Maintainers, developers extending or debugging the system

**Purpose:** Understand the implementation details, API contracts, and testing strategy

**Size:** 888 lines

**Key Topics:**
- Module organization (`analysis_base.py`, `cross_metric_validation_triple.py`)
- Function specifications and signatures
- Data models and return types
- Test suite coverage (15 tests: 13 analysis_base + 2 integration)
- Constants and configuration
- Troubleshooting guide
- Design patterns and code quality

**How to use:** Reference this document when implementing new features, extending validation logic, or debugging analysis results.

---

## Integration with Phase 3 Dashboard

These documents support the **page_15_backtest_validation.py** implementation in the dashboard:

- **Calculations doc** → Business logic and statistical formulas
- **Spec doc** → Implementation details and API contracts
- **Code modules** → `backtest/analysis_base.py`, `backtest/cross_metric_validation_triple.py`
- **Tests** → `test/test_analysis_base.py`, `test/test_cross_metric_validation.py`

---

## Document Governance

| Document | Status | Last Updated | Maintainer |
|----------|--------|--------------|-----------|
| Calculations (計算方法) | Complete | 2026-04-23 | System |
| Spec (コード仕様) | Complete | 2026-04-23 | System |

Both documents are version-controlled and committed to the main repository.
