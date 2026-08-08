from reporting.dashboard_streamlit.theme import dashboard_css


def test_retired_css_classes_are_not_emitted():
    css = dashboard_css(False)
    retired = {
        "ts-signal",
        "ts-signal-stack",
        "ts-summary-compact",
        "ts-section-grid",
        "ts-purpose-grid",
        "ts-compose-meta",
        "ts-cause-children",
    }

    assert all(f".{class_name}" not in css for class_name in retired)


def test_live_cause_tree_classes_remain_styled():
    css = dashboard_css(False)

    for class_name in (
        "ts-cause-tree-root",
        "ts-cause-root",
        "ts-cause-branches",
        "ts-cause-item",
        "ts-cause-pill",
        "ts-cause-sub",
    ):
        assert f".{class_name}" in css
