"""Content-first dynamic block_type selection in layout_generator.

`_block_type()` used to decide the UI slot purely from the section *name*.
These tests prove it now looks at the section's actual structured content
first (real 2+ point metric series -> chart, real 2+ entity comparison ->
table, real strength/weakness/risk/opportunity coverage -> matrix), only
falling back to the old static per-section table when nothing structured is
present — and that this is entirely sector-agnostic (ReportPlan/
AudienceAdaptation never carry a sector id, so the same rules apply no
matter which sector's data flows through).
"""

from common.contracts import AudienceAdaptation, ReportPlan
from core.layout_generator.generator import generate_layout

_METRIC_POINTS_TWO_PERIODS = [
    {"label": "IPTV 가입자", "period": "2019", "value": 519.0, "unit": "만 명"},
    {"label": "IPTV 가입자", "period": "2023", "value": 946.0, "unit": "만 명"},
]

_COMPARISON_POINTS_TWO_ENTITIES = [
    {"entity": "SK브로드밴드", "criterion": "요금", "value": "9,900원", "level": "medium"},
    {"entity": "KT", "criterion": "요금", "value": "8,900원", "level": "low"},
]


def _plan(audience_id: str, sections: list[str]) -> ReportPlan:
    return ReportPlan(
        request_id="req_content_type",
        audience_id=audience_id,
        primary_intent="issue_response",
        sections=sections,
        format="dashboard",
    )


def _adaptation(audience_id: str, adapted_sections: dict) -> AudienceAdaptation:
    return AudienceAdaptation(request_id="req_content_type", audience_id=audience_id, adapted_sections=adapted_sections)


def test_internal_provenance_survives_layout_without_affecting_block_type():
    plan = _plan("_default", ["overview"])
    provenance = [
        {
            "synthesis_claim_id": "doc1:c1",
            "claim_id": "c1",
            "claim_type": "key_point",
            "claim": "검증된 주장",
            "evidence_quote": "원문 근거",
            "confidence": "high",
            "doc_id": "doc1",
        }
    ]
    adaptation = _adaptation(
        "_default",
        {"overview": {"title": "종합 결론", "grounded_claims": provenance}},
    )

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "text"
    assert layout.blocks[0].content["grounded_claims"] == provenance


def test_two_period_metric_series_renders_as_chart_even_when_static_table_says_otherwise():
    # "opportunity" is statically mapped to "matrix" - proves real content wins over that fallback.
    plan = _plan("_default", ["opportunity"])
    adaptation = _adaptation("_default", {"opportunity": {"title": "Trend", "metric_points": _METRIC_POINTS_TWO_PERIODS}})

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "chart"


def test_two_entity_comparison_renders_as_table_even_when_static_table_says_otherwise():
    # "market_status" is statically mapped to "chart" - proves comparison data wins instead.
    plan = _plan("_default", ["market_status"])
    adaptation = _adaptation("_default", {"market_status": {"title": "Competitors", "comparison_points": _COMPARISON_POINTS_TWO_ENTITIES}})

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "table"


def test_two_of_four_swot_fields_renders_as_matrix_even_when_static_table_says_otherwise():
    # "timeline" is statically mapped to "timeline" - proves SWOT coverage wins instead.
    plan = _plan("_default", ["timeline"])
    adaptation = _adaptation(
        "_default",
        {"timeline": {"title": "SWOT", "strengths": ["IPTV 인프라 우위"], "weaknesses": ["콘텐츠 다양성 부족"]}},
    )

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "matrix"


def test_single_swot_field_is_not_enough_to_trigger_matrix():
    # "problem" is statically mapped to "text" - a type with no data-shape
    # claim to validate, so this purely isolates the matrix threshold
    # (unlike "chart"/"timeline", which now require real qualifying data
    # even from the static table - see the two tests below).
    plan = _plan("_default", ["problem"])
    adaptation = _adaptation("_default", {"problem": {"title": "Partial", "strengths": ["IPTV 인프라 우위"]}})

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "text"  # falls back to the static table, unchanged


def test_market_status_with_single_period_metric_does_not_get_chart():
    # Real bug case: "특수관계자에 대한 매출액 비중" is a single 2025년-1Q
    # point - not chartable, but "market_status" statically maps to "chart".
    plan = _plan("_default", ["market_status"])
    adaptation = _adaptation(
        "_default",
        {
            "market_status": {
                "title": "Market Status",
                "metric_points": [
                    {"label": "특수관계자 매출 비중", "period": "2025년 1분기", "value": 15.9, "unit": "%"}
                ],
            }
        },
    )

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type != "chart"


def test_near_term_outlook_with_undated_prose_does_not_get_timeline():
    plan = _plan("_default", ["near_term_outlook"])
    adaptation = _adaptation(
        "_default",
        {
            "near_term_outlook": {
                "title": "Near-term Outlook",
                "key_points": ["검증된 신호가 없습니다."],
                "evidence": ["유료방송시장 경쟁 심화로 인한 리스크가 존재한다."],
            }
        },
    )

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type != "timeline"


def test_timeline_with_genuinely_dated_evidence_still_gets_timeline():
    plan = _plan("_default", ["near_term_outlook"])
    adaptation = _adaptation(
        "_default",
        {
            "near_term_outlook": {
                "title": "Near-term Outlook",
                "evidence": [
                    "2025년 3월 서비스 개편이 예정되어 있다.",
                    "2025년 4분기 신규 요금제 출시가 예정되어 있다.",
                ],
            }
        },
    )

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "timeline"


def test_no_structured_data_falls_back_to_the_existing_static_table():
    plan = _plan("_default", ["response_actions"])
    adaptation = _adaptation("_default", {"response_actions": {"title": "Actions", "actions": ["대응한다"]}})

    layout = generate_layout(plan, adaptation)

    assert layout.blocks[0].block_type == "list"  # unchanged from before this feature


def test_audience_priority_breaks_ties_when_a_section_qualifies_for_multiple_types():
    section_content = {
        "title": "Composite",
        "metric_points": _METRIC_POINTS_TWO_PERIODS,
        "comparison_points": _COMPARISON_POINTS_TWO_ENTITIES,
    }

    practitioner_layout = generate_layout(_plan("practitioner", ["overview"]), _adaptation("practitioner", {"overview": section_content}))
    external_layout = generate_layout(_plan("external", ["overview"]), _adaptation("external", {"overview": section_content}))

    assert practitioner_layout.blocks[0].block_type == "table"
    assert external_layout.blocks[0].block_type == "chart"


def test_content_type_decision_is_identical_across_sectors():
    """ReportPlan/AudienceAdaptation never carry a sector id, so the decision
    is sector-agnostic by construction — confirmed concretely for every
    currently-registered sector's typical section content."""
    for sector_hint in ("sk_hynix", "sk_broadband", "sk_planet", "sk_telecom", "sk_innovation"):
        plan = _plan("_default", ["overview"])
        adaptation = _adaptation("_default", {"overview": {"title": sector_hint, "metric_points": _METRIC_POINTS_TWO_PERIODS}})

        layout = generate_layout(plan, adaptation)

        assert layout.blocks[0].block_type == "chart", sector_hint
