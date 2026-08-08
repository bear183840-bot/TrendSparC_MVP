from common.contracts import DocumentAnalysis, MetricPoint, QuestionCoverageRequirement
from core.question_coverage import assess_question_coverage


def test_comparison_can_be_completed_across_two_sources_on_one_shared_axis():
    analyses = [
        DocumentAnalysis(
            doc_id="north",
            metric_points=[
                MetricPoint(
                    label="Subscribers", subject="North", period="2025",
                    value=10, unit="M",
                )
            ],
        ),
        DocumentAnalysis(
            doc_id="south",
            metric_points=[
                MetricPoint(
                    label="Subscribers", subject="South", period="2025",
                    value=8, unit="M",
                )
            ],
        ),
    ]
    requirement = QuestionCoverageRequirement(comparison_anchors=["North", "South"])

    assert assess_question_coverage(analyses, requirement) == []
