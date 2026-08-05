from common.contracts import ComparisonPoint, MetricPoint
from common.content_quality_validator import (
    classify_metric_shape,
    dated_items,
    detect_secondary_purpose,
    dedupe_across_blocks,
    dedupe_structured_across_sections,
    extract_metric_points_from_evidence,
    filter_shared_comparison_axis,
    group_metric_points_by_label,
    parse_korean_amount,
    period_sort_key,
    rank_by_relevance,
    select_chartable_series,
)

# Fixture values below mirror the real req_cli_3093052e run (Btv 가입자 수
# question) that surfaced these bugs: a KPI row padded out with an unrelated
# 채널 순위 metric, a line chart mixing 가입자 수 (만 명) with 시청률 (%), and
# a "도입 전"/"도입 후" 2-point metric forced into a line chart.


def _subscriber_points() -> list[MetricPoint]:
    return [
        MetricPoint(label="IPTV 가입자 수", period="2022년", value=520.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2023년", value=610.0, unit="만 명"),
        MetricPoint(label="IPTV 가입자 수", period="2024년", value=650.0, unit="만 명"),
    ]


def _rating_points() -> list[MetricPoint]:
    return [
        MetricPoint(label="시청률", period="도입 전", value=3.2, unit="%"),
        MetricPoint(label="시청률", period="도입 후", value=4.1, unit="%"),
    ]


def _channel_rank_point() -> list[MetricPoint]:
    return [MetricPoint(label="채널 순위", period="2024년", value=5.0, unit="위")]


class TestRankByRelevance:
    def test_items_matching_question_terms_come_first(self):
        result = rank_by_relevance(["채널 순위", "IPTV 가입자 수", "시청률"], ["가입자", "수"])
        assert result == ["IPTV 가입자 수", "채널 순위", "시청률"]

    def test_no_terms_keeps_original_order(self):
        items = ["채널 순위", "IPTV 가입자 수"]
        assert rank_by_relevance(items, []) == items

    def test_never_drops_a_low_relevance_item(self):
        result = rank_by_relevance(["채널 순위", "IPTV 가입자 수"], ["가입자"])
        assert set(result) == {"채널 순위", "IPTV 가입자 수"}
        assert len(result) == 2


class TestClassifyMetricShape:
    def test_single_period_is_kpi(self):
        assert classify_metric_shape(_channel_rank_point()) == "kpi"

    def test_two_periods_is_bar(self):
        assert classify_metric_shape(_rating_points()) == "bar"

    def test_three_or_more_periods_is_line(self):
        assert classify_metric_shape(_subscriber_points()) == "line"


class TestGroupMetricPointsByLabel:
    def test_groups_by_label_preserving_points(self):
        grouped = group_metric_points_by_label([*_subscriber_points(), *_rating_points()])
        assert set(grouped.keys()) == {"IPTV 가입자 수", "시청률"}
        assert len(grouped["IPTV 가입자 수"]) == 3
        assert len(grouped["시청률"]) == 2


class TestSelectChartableSeries:
    def test_drops_unit_mismatched_series_even_if_line_shaped_and_periods_overlap(self):
        # Same 3 periods as _subscriber_points(), but a different unit (억원
        # vs 만 명) - overlapping periods alone must not be enough to plot
        # two series on one axis.
        revenue_points = [
            MetricPoint(label="매출", period="2022년", value=100.0, unit="억원"),
            MetricPoint(label="매출", period="2023년", value=120.0, unit="억원"),
            MetricPoint(label="매출", period="2024년", value=150.0, unit="억원"),
        ]
        chartable = select_chartable_series([*_subscriber_points(), *revenue_points])
        labels = {point.label for point in chartable}
        assert labels == {"IPTV 가입자 수"}

    def test_two_point_bar_shaped_label_never_enters_chart(self):
        chartable = select_chartable_series([*_subscriber_points(), *_rating_points()])
        assert all(point.label != "시청률" for point in chartable)

    def test_no_line_shaped_data_returns_empty(self):
        assert select_chartable_series([*_rating_points(), *_channel_rank_point()]) == []

    def test_disjoint_timeline_dropped_even_with_matching_unit(self):
        other_series = [
            MetricPoint(label="OTT 이용자 수", period="2019년", value=10.0, unit="만 명"),
            MetricPoint(label="OTT 이용자 수", period="2020년", value=12.0, unit="만 명"),
            MetricPoint(label="OTT 이용자 수", period="2021년", value=14.0, unit="만 명"),
        ]
        chartable = select_chartable_series([*_subscriber_points(), *other_series])
        labels = {point.label for point in chartable}
        assert labels == {"IPTV 가입자 수"}


class TestFilterSharedComparisonAxis:
    def test_keeps_criterion_shared_by_two_or_more_entities(self):
        points = [
            ComparisonPoint(entity="자사", criterion="요금제 가격", value="9,900원"),
            ComparisonPoint(entity="KT", criterion="요금제 가격", value="10,900원"),
        ]
        assert filter_shared_comparison_axis(points) == points

    def test_drops_criterion_only_one_entity_states(self):
        points = [
            ComparisonPoint(entity="자사", criterion="요금제 가격", value="9,900원"),
            ComparisonPoint(entity="KT", criterion="요금제 가격", value="10,900원"),
            ComparisonPoint(entity="자사", criterion="국내 월간 이용자 수", value="200만 명"),
        ]
        result = filter_shared_comparison_axis(points)
        assert all(point.criterion != "국내 월간 이용자 수" for point in result)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        assert filter_shared_comparison_axis([]) == []


class TestDedupeAcrossBlocks:
    def test_drops_near_duplicate_from_later_block(self):
        blocks = [
            ["IPTV 가입자 수가 2024년 650만 명으로 증가했다."],
            ["IPTV 가입자 수는 2024년 650만 명까지 늘어났다.", "새로운 콘텐츠 제휴가 발표됐다."],
        ]
        result = dedupe_across_blocks(blocks)
        assert result[0] == blocks[0]
        assert result[1] == ["새로운 콘텐츠 제휴가 발표됐다."]

    def test_keeps_genuinely_distinct_sentences(self):
        blocks = [["A 사실"], ["전혀 다른 B 사실"]]
        assert dedupe_across_blocks(blocks) == blocks


class TestDetectSecondaryPurpose:
    def test_returns_strongest_runner_up_above_threshold(self):
        scores = {"current_status": 8, "issue_response": 0, "future_business": 4, "root_cause": 1}
        assert detect_secondary_purpose(scores, "current_status") == "future_business"

    def test_returns_none_when_no_runner_up_clears_threshold(self):
        scores = {"current_status": 8, "issue_response": 0, "future_business": 2, "root_cause": 1}
        assert detect_secondary_purpose(scores, "current_status") is None

    def test_winner_itself_never_returned(self):
        scores = {"current_status": 10, "issue_response": 0, "future_business": 0, "root_cause": 0}
        assert detect_secondary_purpose(scores, "current_status") is None


class TestPeriodSortKey:
    def test_orders_quarters_chronologically_regardless_of_written_format(self):
        periods = ["2025년 1분기", "1Q24", "2024년 4분기"]
        assert sorted(periods, key=period_sort_key) == ["1Q24", "2024년 4분기", "2025년 1분기"]

    def test_unparseable_period_sorts_after_parseable_ones(self):
        periods = ["2024년 1분기", "도입 후"]
        assert sorted(periods, key=period_sort_key) == ["2024년 1분기", "도입 후"]


class TestDedupeStructuredAcrossSections:
    def test_keeps_only_first_section_when_metric_point_identical(self):
        point = MetricPoint(label="특수관계자 매출 비중", period="2025년 1분기", value=15.9, unit="%")
        sections = [[point], [point], []]

        result = dedupe_structured_across_sections(sections)

        assert result[0] == [point]
        assert result[1] == []
        assert result[2] == []

    def test_distinct_metric_points_survive_in_every_section(self):
        subscriber = MetricPoint(label="가입자 수", period="2024년", value=650.0, unit="만 명")
        revenue = MetricPoint(label="매출", period="2025년", value=45406.0, unit="억원")
        sections = [[subscriber], [revenue]]

        result = dedupe_structured_across_sections(sections)

        assert result == [[subscriber], [revenue]]

    def test_works_for_comparison_points_too(self):
        point = ComparisonPoint(entity="자사", criterion="요금제 가격", value="9,900원")
        sections = [[point], [point]]

        result = dedupe_structured_across_sections(sections)

        assert result[0] == [point]
        assert result[1] == []


class TestParseKoreanAmount:
    def test_jo_and_eok_combination(self):
        assert parse_korean_amount("4조 5,406억원") == 45406.0

    def test_eok_and_cheonman_combination(self):
        assert parse_korean_amount("1,414억 8천만원") == 1414.8

    def test_eok_only(self):
        assert parse_korean_amount("500억원") == 500.0

    def test_plain_prose_returns_none(self):
        assert parse_korean_amount("그냥 텍스트입니다") is None

    def test_empty_string_returns_none(self):
        assert parse_korean_amount("") is None

    def test_bare_won_amount_with_no_unit_word_returns_none(self):
        # Deliberately out of scope - only 조/억/천만/만-denominated amounts
        # are handled; a bare "5000원" is not this pattern.
        assert parse_korean_amount("5000원") is None


class TestExtractMetricPointsFromEvidence:
    def test_extracts_all_three_real_example_sentences(self):
        evidence = [
            "2025년 매출: 4조 5,406억원 (전년 대비 3% 증가) [doc_id=www.jobkorea.co.kr:abc]",
            "2024년 2분기 매출: 4조 4,540억원 (전년 대비 3.4% 증가 예상) [doc_id=www.sks.co.kr:def]",
            "2025년 순이익: 1,414억 8천만원 (전년 대비 46% 감소) [doc_id=www.jobkorea.co.kr:abc]",
        ]

        points = extract_metric_points_from_evidence(evidence)

        assert len(points) == 3
        assert (points[0].label, points[0].period, points[0].value, points[0].unit) == ("매출", "2025년", 45406.0, "억원")
        assert (points[1].label, points[1].period, points[1].value) == ("매출", "2024년 2분기", 44540.0)
        assert (points[2].label, points[2].period, points[2].value) == ("순이익", "2025년", 1414.8)

    def test_two_periods_of_the_same_label_are_chartable_as_a_bar(self):
        evidence = [
            "2025년 매출: 4조 5,406억원 (전년 대비 3% 증가)",
            "2024년 2분기 매출: 4조 4,540억원 (전년 대비 3.4% 증가 예상)",
        ]

        points = extract_metric_points_from_evidence(evidence)

        assert classify_metric_shape(points) == "bar"

    def test_never_back_calculates_a_value_from_the_yoy_percentage_alone(self):
        # Only one dated figure is stated - no second point should ever be
        # invented from "전년 대비 3% 증가" alone.
        evidence = ["2025년 매출: 4조 5,406억원 (전년 대비 3% 증가)"]

        points = extract_metric_points_from_evidence(evidence)

        assert len(points) == 1

    def test_sentence_without_the_pattern_yields_nothing(self):
        evidence = ["특수관계자에 대한 매출액 비중은 15.9%이다 (2025년 1분기말 기준)"]

        assert extract_metric_points_from_evidence(evidence) == []

    def test_empty_evidence_list_yields_nothing(self):
        assert extract_metric_points_from_evidence([]) == []


class TestDatedItems:
    def test_keeps_only_items_with_a_year_quarter_or_date_marker(self):
        items = ["2025년 3월 서비스 개편", "검증된 신호가 없습니다.", "2025년 4분기 출시 예정"]
        assert dated_items(items) == ["2025년 3월 서비스 개편", "2025년 4분기 출시 예정"]

    def test_empty_input_returns_empty(self):
        assert dated_items([]) == []
