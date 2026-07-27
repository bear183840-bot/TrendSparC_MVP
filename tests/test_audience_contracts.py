from audience.contracts import list_audience_ids, load_audience_profile


def test_all_four_audience_profiles_load():
    ids = list_audience_ids()
    assert set(ids) == {"external", "practitioner", "executive", "management"}
    for audience_id in ids:
        profile = load_audience_profile(audience_id)
        assert profile.audience_id == audience_id
        assert profile.tone
        assert profile.format_preference
