"""Approximate the collector's bounded export for offline session replay."""


def export_window(records: list, end_index: int) -> list:
    """Return the collector's move/other-event selection after ``end_index``."""
    count = end_index + 1
    if not 0 < count <= len(records):
        raise ValueError("end_index must reference a record")

    # MouseRecorder retains 500 records after every 51st overflow.
    retained = count if count <= 550 else 500 + (count - 551) % 51
    recent = records[max(0, count - retained):count]
    other = [
        record for record in recent
        if record.get("type") != "move" or record.get("source") == "touch"
    ][-20:]
    moves = [
        record for record in recent
        if record.get("type") == "move" and record.get("source") != "touch"
    ][-(100 - len(other)):]
    return sorted(moves + other, key=lambda record: record.get("time", 0))


def rolling_windows(records: list, checkpoints: int = 25) -> list:
    """Sample checkpoints from the 25th move through the retained session."""
    if checkpoints < 1:
        raise ValueError("checkpoints must be positive")
    move_indices = [
        index for index, record in enumerate(records)
        if record.get("type") == "move" and record.get("source") != "touch"
    ]
    eligible = move_indices[24:]
    if not eligible:
        return []
    if len(eligible) <= checkpoints:
        indices = eligible
    elif checkpoints == 1:
        indices = [eligible[-1]]
    else:
        indices = sorted({
            eligible[round(position * (len(eligible) - 1) / (checkpoints - 1))]
            for position in range(checkpoints)
        })
    return [export_window(records, index) for index in indices]
