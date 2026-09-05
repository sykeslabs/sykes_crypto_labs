"""Screening-stage anomaly / wash-trading flag — a heuristic guard against
implausible volume/price behavior in the smaller-cap tier of the universe,
not a general market-manipulation detector. Flags, never excludes: a
flagged asset can still surface as a CANDIDATE, but callers must carry the
flag forward so later stages treat it with extra scrutiny.
"""

import statistics

# Latest day's volume is flagged if it's this many stdevs above the mean of
# the prior days in the window — a simple, inspectable z-score threshold,
# not a general manipulation model.
VOLUME_ZSCORE_THRESHOLD = 3.0

# Latest day's single-day price move is flagged if its absolute value exceeds
# this fraction (0.5 = 50%) — large enough that legitimate volatile small-caps
# don't trip it on an ordinary strong day, small enough to catch a genuine
# pump-and-dump-style spike.
PRICE_JUMP_THRESHOLD = 0.5


def detect_anomaly(
    daily_closes: list[float], daily_volumes: list[float]
) -> tuple[bool, str | None]:
    """`daily_closes`/`daily_volumes` are same-length series, oldest first,
    ending with the most recent day. Returns (flagged, reason)."""
    if len(daily_closes) < 2 or len(daily_volumes) < 2:
        return False, None

    latest_close, prior_closes = daily_closes[-1], daily_closes[:-1]
    latest_volume, prior_volumes = daily_volumes[-1], daily_volumes[:-1]

    if prior_closes[-1] != 0:
        price_move = (latest_close - prior_closes[-1]) / prior_closes[-1]
        if abs(price_move) > PRICE_JUMP_THRESHOLD:
            return True, (
                f"Single-day price move {price_move:+.1%} exceeds "
                f"{PRICE_JUMP_THRESHOLD:.0%} threshold"
            )

    if len(prior_volumes) >= 2:
        mean_volume = statistics.mean(prior_volumes)
        stdev_volume = statistics.pstdev(prior_volumes)
        if stdev_volume > 0:
            volume_z = (latest_volume - mean_volume) / stdev_volume
            if volume_z > VOLUME_ZSCORE_THRESHOLD:
                return True, (
                    f"Latest-day volume z-score {volume_z:.1f} exceeds "
                    f"{VOLUME_ZSCORE_THRESHOLD:.1f} threshold"
                )

    return False, None
