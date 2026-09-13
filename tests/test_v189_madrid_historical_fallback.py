from sources import madrid_idi_history as hist


def test_v189_constant():
    assert hist.HISTORICAL_DETAIL_MAX_AGE_DAYS == 2
