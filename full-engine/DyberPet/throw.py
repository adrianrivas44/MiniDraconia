"""Mouse samples (x, y, monotonic seconds) -> pixels per falling tick.

The speed limit is the vector magnitude, not a separate allowance per axis.
"""
from math import hypot


def throw_velocity(samples, now, step_s, max_speed):
    """Return a capped velocity from timestamped drag samples."""
    if (len(samples) < 2 or step_s <= 0 or max_speed <= 0
            or now - samples[-1][2] >= 0.080):
        return 0.0, 0.0
    cutoff = now - 0.080
    x0, y0, t0 = samples[0]
    for x, y, t in samples[1:]:
        if t <= cutoff:
            x0, y0, t0 = x, y, t
        else:
            if t0 < cutoff and t > t0:
                fraction = (cutoff - t0) / (t - t0)
                x0, y0 = x0 + (x - x0) * fraction, y0 + (y - y0) * fraction
                t0 = cutoff
            break
    x1, y1, _ = samples[-1]
    # Hold the last position until release: no events means no new movement.
    dt = now - t0
    if dt <= 0:
        return 0.0, 0.0
    vx, vy = (x1 - x0) / dt * step_s, (y1 - y0) / dt * step_s
    speed = hypot(vx, vy)
    if speed > max_speed:
        vx, vy = vx * max_speed / speed, vy * max_speed / speed
    return vx, vy
