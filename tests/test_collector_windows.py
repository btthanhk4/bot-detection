from core_ml.collector_windows import export_window, rolling_windows


def test_export_window_matches_collector_move_and_other_limits():
    records = [
        {"time": index, "type": "click" if index % 11 == 0 else "move"}
        for index in range(602)
    ]
    exported = export_window(records, 601)
    assert len(exported) == 100
    assert sum(record["type"] == "click" for record in exported) == 20
    assert exported == sorted(exported, key=lambda record: record["time"])
    assert exported[0]["time"] >= 102


def test_touch_moves_do_not_displace_mouse_moves():
    records = [{"time": i, "type": "move"} for i in range(100)]
    records += [{"time": 100 + i, "type": "move", "source": "touch"} for i in range(30)]
    exported = export_window(records, len(records) - 1)
    assert len(exported) == 100
    assert sum(record.get("source") == "touch" for record in exported) == 20


def test_rolling_windows_cover_middle_of_session():
    records = [{"time": i, "type": "move"} for i in range(300)]
    windows = rolling_windows(records, checkpoints=5)
    assert len(windows) == 5
    assert [window[-1]["time"] for window in windows] == [24, 93, 162, 230, 299]
