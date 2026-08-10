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


def test_the_donut_head_and_body_are_both_styled():
    """STEP 3: the donut title moved into its own compact header, out of the
    flex row it used to share with the circle - both halves need real CSS,
    not just markup."""
    css = dashboard_css(False)

    assert ".ts-donut-head" in css
    assert ".ts-donut-body" in css


def test_the_landscape_composite_has_a_narrow_width_breakpoint():
    """STEP 9: "Donut | Line" must stack under a narrow viewport instead of
    squeezing both halves - same collapse-to-column pattern the horizontal
    timeline already uses at its own breakpoint."""
    css = dashboard_css(False)

    assert "@media (max-width:700px)" in css
    assert "flex-direction:column" in css.split("@media (max-width:700px)")[1][:600]
