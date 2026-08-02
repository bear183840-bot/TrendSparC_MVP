from audience.contracts import list_audience_ids, load_audience_profile


def test_all_four_audience_profiles_load():
    ids = list_audience_ids()
    assert set(ids) == {"external", "practitioner", "executive", "management"}
    for audience_id in ids:
        profile = load_audience_profile(audience_id)
        assert profile.audience_id == audience_id
        assert profile.tone
        assert profile.format_preference


def test_default_profile_loads_but_is_not_a_selectable_option():
    # "_default" is the fallback used when no audience is explicitly picked
    # (see core/request_pipeline/pipeline.py's _DEFAULT_AUDIENCE_ID) — it must
    # stay loadable directly, but never show up as a 5th selectable persona.
    assert "_default" not in list_audience_ids()
    profile = load_audience_profile("_default")
    assert profile.audience_id == "_default"
    assert profile.tone
    assert profile.report_structure == []
