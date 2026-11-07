"""Measure how far the pet's planted foot (walk) or hold (climb) travels per frame.

An in-place cycle draws the body still and slides the supporting foot/hand backwards. To
make her travel without skating, the window must move by that same distance every frame:
`frame_move` in res/role/<role>/act_conf.json, in sprite pixels per frame (the engine
multiplies it by the pet's display scale).

Method (Qt QImage only, no extra dependency):
- walk: in the bottom BAND rows above the lowest opaque row, opaque columns are grouped
  into clusters (the feet). Between consecutive frames each cluster is matched to the
  nearest one; the planted foot is the one moving against the walking direction.
  `frame_move` is the planted foot's total backward travel over one loop divided by the
  loop's frames (`cycle_speed`; a held frame counts as 0), so the window travels exactly as
  far as the feet every loop. The median of the moving frames is printed too: it equals the
  loop mean only for a clip without held frames (Draconia's 16-frame walk holds 3 frames).
- climb: the same on the BAND columns beside the wall (the sprite's right edge), with
  clusters along y; the hold moves down while she climbs up.

- walk steps (M3.3): a step ends on the frame where both feet are planted farthest apart
  (largest gap between the two foot clusters) between two passing frames (feet together, one
  cluster). Those frames are `step_ends` in act_conf.json, so a walk interrupted by a line
  stops between two steps instead of mid-stride.

Run: QT_QPA_PLATFORM=offscreen python scripts/measure_sprite_motion.py [--role DIR]
Re-run after the sprites change; it prints the values to put in act_conf.json.
"""
import argparse
import statistics
from pathlib import Path

BAND = 25
ALPHA = 128
GAP = 3          # columns/rows of gap still inside one cluster
MIN_SIZE = 4     # ignore specks narrower than this


def _alpha(path):
    """(width, height, alpha bytes row-major) of a PNG."""
    from PySide6.QtGui import QImage
    img = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    raw = bytes(img.constBits())[:stride * h]
    rows = [raw[y * stride + 3:y * stride + 4 * w:4] for y in range(h)]
    return w, h, b''.join(rows)


def _clusters(mask):
    out, start, last = [], None, None
    for i, on in enumerate(mask):
        if on:
            if start is None:
                start = i
            elif i - last > GAP + 1:
                out.append((start, last))
                start = i
            last = i
    if start is not None:
        out.append((start, last))
    return [((a + b) / 2.0, b - a + 1) for a, b in out if b - a + 1 >= MIN_SIZE]


def foot_clusters(path):
    w, h, alpha = _alpha(path)
    bottom = next(y for y in range(h - 1, -1, -1) if max(alpha[y * w:(y + 1) * w]) >= ALPHA)
    top = max(0, bottom - BAND + 1)
    mask = [max(alpha[top * w + x:(bottom + 1) * w:w]) >= ALPHA for x in range(w)]
    return [c for c, _ in _clusters(mask)]


def wall_clusters(path, side='right'):
    w, h, alpha = _alpha(path)
    opaque_cols = [x for x in range(w) if max(alpha[x::w]) >= ALPHA]
    edge = max(opaque_cols) if side == 'right' else min(opaque_cols)
    lo, hi = (edge - BAND + 1, edge + 1) if side == 'right' else (edge, edge + BAND)
    mask = [max(alpha[y * w + lo:y * w + hi]) >= ALPHA for y in range(h)]
    return [c for c, _ in _clusters(mask)]


def planted_speed(series, backward_sign):
    """Median backward displacement per frame of the cluster that moves against the motion."""
    steps = []
    for prev, cur in zip(series, series[1:] + series[:1]):
        if not prev or not cur:
            continue
        moves = []
        for c in cur:
            p = min(prev, key=lambda q: abs(q - c))
            moves.append(c - p)
        backward = [m for m in moves if m * backward_sign > 0.5]
        if backward:
            steps.append(min(abs(m) for m in backward))
    return (statistics.median(steps) if steps else 0.0), len(steps)


def cycle_speed(series, backward_sign):
    """Planted-foot travel per frame averaged over the whole loop (held frames count as 0)."""
    total, pairs = 0.0, 0
    for prev, cur in zip(series, series[1:] + series[:1]):
        pairs += 1
        if not prev or not cur:
            continue
        moves = [c - min(prev, key=lambda q: abs(q - c)) for c in cur]
        backward = [abs(m) for m in moves if m * backward_sign > 0.5]
        if backward:
            total += min(backward)
    return (total / pairs if pairs else 0.0), pairs


def step_ends(series):
    """Frames that end a step: in each run of frames between passing frames (one foot
    cluster), the one with the widest stance (largest gap between the outer foot clusters)."""
    ends, run = [], []
    for i, clusters in enumerate(list(series) + [[0]]):
        if len(clusters) >= 2:
            run.append((max(clusters) - min(clusters), -i))
        elif run:
            ends.append(-max(run)[1])
            run = []
    return ends


def frames(role, images):
    files = sorted((role / 'action').glob(images + '_*.png'), key=lambda p: int(p.stem.rsplit('_', 1)[1]))
    if not files:
        raise SystemExit('no frames for %s in %s' % (images, role))
    return files


def measure(role):
    """{'walkcycle_right': px, 'walkcycle_left': px, 'climb': px} sprite px per frame."""
    role = Path(role)
    results = {}
    for images, sign in (('walkcycle_right', -1), ('walkcycle_left', +1)):
        results[images] = cycle_speed([foot_clusters(p) for p in frames(role, images)], sign)
    results['climb'] = planted_speed([wall_clusters(p) for p in frames(role, 'climb')], +1)
    return results


def measure_steps(role):
    """{'walkcycle_right': [frame, ...], 'walkcycle_left': [...]}: `step_ends` of each walk."""
    role = Path(role)
    return {images: step_ends([foot_clusters(p) for p in frames(role, images)])
            for images in ('walkcycle_right', 'walkcycle_left')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--role', default=str(Path(__file__).resolve().parents[1] / 'full-engine' / 'res' / 'role' / 'Draconia'))
    args = parser.parse_args(argv)
    results = measure(args.role)
    role = Path(args.role)
    for name, (speed, n) in results.items():
        if name == 'climb':
            print('%-16s %-12s %.1f sprite px/frame (median of %d frame pairs)' % (name, 'wall hold', speed, n))
            continue
        sign = -1 if name.endswith('right') else +1
        median, moving = planted_speed([foot_clusters(p) for p in frames(role, name)], sign)
        print('%-16s %-12s %.2f sprite px/frame over the %d-frame loop (frame_move); median of %d moving frames %.1f'
              % (name, 'planted foot', speed, n, moving, median))
    for name, ends in measure_steps(args.role).items():
        print('%-16s step_ends    %s' % (name, ends))
    return results


if __name__ == '__main__':
    main()
