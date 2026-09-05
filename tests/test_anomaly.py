from app.market_data.anomaly import detect_anomaly


def test_no_anomaly_on_ordinary_data():
    closes = [100.0, 101.0, 99.0, 102.0, 103.0]
    volumes = [1000.0, 1050.0, 950.0, 1100.0, 1080.0]
    flagged, reason = detect_anomaly(closes, volumes)
    assert flagged is False
    assert reason is None


def test_flags_large_single_day_price_jump():
    closes = [100.0, 101.0, 99.0, 102.0, 210.0]  # +105.9% on the last day
    volumes = [1000.0, 1050.0, 950.0, 1100.0, 1080.0]
    flagged, reason = detect_anomaly(closes, volumes)
    assert flagged is True
    assert "price move" in reason.lower()


def test_flags_volume_spike():
    closes = [100.0, 101.0, 100.5, 101.2, 101.5]
    volumes = [1000.0, 1020.0, 980.0, 1010.0, 50000.0]  # huge spike on last day
    flagged, reason = detect_anomaly(closes, volumes)
    assert flagged is True
    assert "volume" in reason.lower()


def test_insufficient_data_never_flags():
    assert detect_anomaly([100.0], [1000.0]) == (False, None)
    assert detect_anomaly([], []) == (False, None)


def test_flat_history_does_not_false_positive_on_zero_stdev():
    closes = [100.0] * 10
    volumes = [1000.0] * 10
    flagged, reason = detect_anomaly(closes, volumes)
    assert flagged is False
    assert reason is None
