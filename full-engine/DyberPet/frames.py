"""The pet's frames: decoded on demand, sized for the screen they are shown on.

Before M3 every frame of every action was decoded at start (2117 PNGs of 515x460, about
2 GB of pixmaps) and the label let Qt stretch the 460 px source to the window size, so on a
150 % screen Qt upscaled her. Now:

- `FrameStore` lists the role's PNGs without decoding them; an action's frames are decoded
  the first time that action plays and kept in a small per-action LRU cache. The idle and
  walk (and talk) sets are pinned once decoded; any other action is evicted when more than
  `keep_recent` other actions have played since.
- Each cached frame is built once at its exact physical size, `logical size x
  devicePixelRatio`, by smooth downscaling of the source PNG, and tagged with that
  devicePixelRatio. Frames are never upscaled: the physical size is capped at the source
  size, so on a dense screen the largest crisp size is source / devicePixelRatio
  (`display_scale`). `present()` shows a frame at 1:1 device pixels (no scaled contents).
- (M3.1) The source is converted to premultiplied ARGB *before* scaling: smoothing straight
  alpha would mix the colour of nearly transparent matte pixels into the outline (fringes).
- Frames are `QImage`s (safe to build on the animation thread); `present()` turns them into
  the label's pixmap on the UI thread. (M3.1) That pixmap is cached per frame on the UI side,
  for exactly the frames the LRU keeps, so a looping clip is not converted again each time
  (mirrored views are converted each time and not kept).
- (M3.2) When a clip starts its whole frame group is prefetched on one background thread
  (`prefetch`), so the thread that plays it almost never decodes. Decoding and scaling happen
  outside the store lock: no thread waits for another thread's decode of a different frame (two
  threads may decode the same frame once; the first one stored wins). Idle, walks, talk, think
  and tea stay pinned; the other groups are an LRU bounded by `keep_recent` and `max_bytes`.
"""
import atexit
import queue
import threading
import weakref
from collections import Counter, OrderedDict, deque
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

# Actions that stay decoded once used: idle (stand, also the closed-mouth pause), both walks,
# talk (every spoken line), think (waiting for the voice) and tea (her teacup, M3.2).
PINNED_GROUPS = ('stand', 'walkcycle_right', 'walkcycle_left', 'talk', 'think', 'tea')
KEEP_RECENT = 2
# M3.2: byte budget of the whole cache. Unpinned groups (oldest first, never the newest one) are
# dropped while it is exceeded. At DPR 1.5 and scale 0.5 a group is about 39 MB, so 6 pinned + 2
# recent groups are about 311 MB and the budget never has to act there.
MAX_BYTES = 450 * 2 ** 20
DECODE_LOG_LEN = 256


_STORES = weakref.WeakSet()       # stores whose prefetch thread must stop before exit


@atexit.register
def _stop_prefetching():
    """Python runs this before it tears down daemon threads: a prefetch thread still decoding a
    QImage at that point makes Qt abort the process (M3.2)."""
    for store in list(_STORES):
        store.close()


def display_scale(scale, dpr):
    """The on-screen (logical) scale actually used: `scale`, unless that would need more
    physical pixels than the source has (scale x dpr > 1); then source / dpr."""
    dpr = float(dpr) if dpr and dpr > 0 else 1.0
    return min(float(scale), 1.0 / dpr) if scale > 0 else 1.0 / dpr


def physical_size(src_w, src_h, scale, dpr):
    """Physical pixels of a frame shown at `scale` on a `dpr` screen; never above the source."""
    k = display_scale(scale, dpr) * (float(dpr) if dpr and dpr > 0 else 1.0)
    k = min(k, 1.0)
    return max(1, int(round(src_w * k))), max(1, int(round(src_h * k)))


def group_of(name):
    """'walkcycle_right_12' -> 'walkcycle_right'."""
    return name.rsplit('_', 1)[0]


def logical_size(image):
    """(width, height) in logical pixels of a frame tagged with its devicePixelRatio."""
    size = image.deviceIndependentSize()
    return size.width(), size.height()


def logical_px(value):
    """Whole logical pixels a fractional logical length takes (the label's rounding)."""
    return max(1, int(round(float(value))))


def label_size(image):
    """(width, height) of the label that shows `image` 1:1."""
    w, h = logical_size(image)
    return logical_px(w), logical_px(h)


def shown_size(image, scale):
    """Logical size the pet's current frame takes on screen: a store frame (QImage tagged
    with its DPR) is already at display size; a legacy pixmap is stretched by `scale`
    (pass `settings.pet_display_scale`)."""
    if isinstance(image, QImage):
        return logical_size(image)
    return image.width() * scale, image.height() * scale


def opaque_span(image, alpha=128):
    """(left, right) logical x of the opaque part of a frame (alpha >= `alpha`)."""
    img = image.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    dpr = image.devicePixelRatio() or 1.0
    step = max(1, h // 120)

    def opaque(x):
        return any(img.pixelColor(x, y).alpha() >= alpha for y in range(0, h, step))

    left = next((x for x in range(w) if opaque(x)), None)
    if left is None:
        return 0.0, w / dpr
    right = next(x for x in range(w - 1, left - 1, -1) if opaque(x))
    return left / dpr, (right + 1) / dpr


def present(label, image, mirror=False, store=None):
    """Show `image` on `label` at 1:1 device pixels: the label takes the frame's logical size
    and the pixmap keeps the frame's devicePixelRatio, so Qt never rescales it. With `store`,
    the pixmap of a store frame is reused (UI thread only)."""
    pixmap = store.pixmap(image, mirror) if store is not None else None
    if pixmap is None:
        pixmap = to_pixmap(image, mirror)
    size = pixmap.deviceIndependentSize()
    label.setScaledContents(False)
    label.setFixedSize(QSize(logical_px(size.width()), logical_px(size.height())))
    label.setPixmap(pixmap)
    return pixmap


def to_pixmap(image, mirror=False):
    if mirror:
        image = image.mirrored(True, False)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(image.devicePixelRatio())
    return pixmap


class FrameStore:
    """Mapping-like access (`store['stand_0']`, `'stand_0' in store`) to a role's frames.

    Thread-safe: the animation worker reads frames from its own thread. Pixmaps
    (`pixmap()`) are created and dropped on the UI thread only.
    """

    def __init__(self, folder, scale=1.0, dpr=1.0, pinned=PINNED_GROUPS, keep_recent=KEEP_RECENT,
                 max_bytes=MAX_BYTES):
        self.folder = Path(folder)
        self._paths = {p.stem: p for p in self.folder.glob('*.png')}
        self._groups = {}
        for name in sorted(self._paths, key=_frame_order):
            self._groups.setdefault(group_of(name), []).append(name)
        self._lock = threading.RLock()
        self._scale = float(scale)
        self._dpr = float(dpr) if dpr and dpr > 0 else 1.0
        self._pinned = set(pinned)
        self._keep_recent = int(keep_recent)
        self._max_bytes = int(max_bytes)
        self._cache = OrderedDict()     # group -> {frame name: QImage}
        self._bytes = {}                # group -> bytes of its cached frames
        self._generation = 0            # bumped by configure(): late decodes of the old size are dropped
        # The most recent decodes (for checks) and a total count: bounded, unlike the run.
        self.decode_log = deque(maxlen=DECODE_LOG_LEN)
        self.decode_count = 0
        self.decodes_by_thread = Counter()   # thread ident -> decodes it did (M3.2)
        self._decoded_groups = set()
        self._prefetch_queue = None
        self._prefetch_thread = None
        self._prefetching = {}          # group -> Event set when its prefetch is done
        self._closing = False
        self._source_size = None
        self._keys = {}                 # QImage.cacheKey() -> group, for frames in the cache
        self._pixmaps = {}              # cacheKey -> QPixmap  (UI thread)
        self._spans = {}                # (frame name, alpha) -> opaque span at this config

    # -- mapping protocol used by the role loader ------------------------------------------
    def __contains__(self, name):
        return name in self._paths

    def __getitem__(self, name):
        if name not in self._paths:
            raise KeyError(name)
        return self.frame(name)

    def keys(self):
        return self._paths.keys()

    def __len__(self):
        return len(self._paths)

    # -- display configuration -------------------------------------------------------------
    @property
    def scale(self):
        return self._scale

    @property
    def dpr(self):
        return self._dpr

    def configure(self, scale, dpr):
        """Change the requested scale / screen devicePixelRatio. Cached frames of the old size
        are dropped (they are rebuilt on demand). Returns True when something changed."""
        dpr = float(dpr) if dpr and dpr > 0 else 1.0
        with self._lock:
            if abs(float(scale) - self._scale) < 1e-9 and abs(dpr - self._dpr) < 1e-9:
                return False
            self._scale, self._dpr = float(scale), dpr
            self._generation += 1
            self._cache.clear()
            self._bytes.clear()
            self._keys.clear()
            self._spans.clear()
            return True

    def display_scale(self):
        return display_scale(self._scale, self._dpr)

    def source_size(self):
        """Source frame size from the PNG header (no decode)."""
        if self._source_size is None:
            first = next(iter(sorted(self._paths.values())), None)
            size = QImageReader(str(first)).size() if first else QSize(0, 0)
            self._source_size = (size.width(), size.height())
        return self._source_size

    def logical_frame_size(self):
        w, h = self.source_size()
        pw, ph = physical_size(w, h, self._scale, self._dpr)
        return pw / self._dpr, ph / self._dpr

    # -- frames ----------------------------------------------------------------------------
    def frame(self, name):
        """The frame, decoded (outside the lock) on a cache miss."""
        group = group_of(name)
        with self._lock:
            frames = self._cache.get(group)
            if frames is not None:
                self._cache.move_to_end(group)
                image = frames.get(name)
                if image is not None:
                    return image
            generation, scale, dpr = self._generation, self._scale, self._dpr
        image = self._build(name, scale, dpr)
        return self._store(name, image, generation, touch=True)

    def _store(self, name, image, generation, touch):
        """Put a decoded frame in the cache (unless another thread already did, or the display
        configuration changed meanwhile) and return the cached one."""
        group = group_of(name)
        with self._lock:
            if generation != self._generation:
                return image                 # decoded for the old size: used once, not kept
            frames = self._cache.get(group)
            if frames is None:
                frames = self._cache[group] = {}     # a new group is the most recent one
            elif touch:
                self._cache.move_to_end(group)       # a prefetch does not reorder the LRU
            cached = frames.get(name)
            if cached is not None:
                return cached
            frames[name] = image
            self._bytes[group] = self._bytes.get(group, 0) + image.sizeInBytes()
            self._keys[image.cacheKey()] = group
            self._evict()
            return image

    # -- prefetch (M3.2) -------------------------------------------------------------------
    def group_names(self, group):
        return list(self._groups.get(group, ()))

    def prefetch(self, names):
        """Decode every frame of the groups of `names` on the store's background thread.
        Returns a `threading.Event` set when they are all cached (immediately set when they
        already are). Asking again for a group that is being prefetched does nothing."""
        groups = []
        for name in names:
            group = group_of(name)
            if group not in groups:
                groups.append(group)
        done = threading.Event()
        pending = []
        with self._lock:
            if self._closing:
                done.set()
                return done
            for group in groups:
                if self._fully_cached(group):
                    continue
                event = self._prefetching.get(group)
                if event is None:
                    event = self._prefetching[group] = threading.Event()
                    self._queue().put(group)
                pending.append(event)
        if not pending:
            done.set()
        elif len(pending) == 1:
            return pending[0]
        else:
            def join():
                for event in pending:
                    event.wait()
                done.set()
            threading.Thread(target=join, daemon=True).start()
        return done

    def _fully_cached(self, group):
        frames = self._cache.get(group)
        return frames is not None and len(frames) >= len(self._groups.get(group, ()))

    def _queue(self):
        if self._prefetch_queue is None:
            self._prefetch_queue = queue.Queue()
            self._prefetch_thread = threading.Thread(target=self._prefetch_loop,
                                                     name='FrameStore-prefetch', daemon=True)
            _STORES.add(self)
            self._prefetch_thread.start()
        return self._prefetch_queue

    def close(self, timeout=5.0):
        """Stop the prefetch thread (after the frame it is decoding) and wait for it."""
        with self._lock:
            self._closing = True
            thread, work = self._prefetch_thread, self._prefetch_queue
        if work is not None:
            work.put(None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _prefetch_loop(self):
        while True:
            group = self._prefetch_queue.get()
            if group is None or self._closing:
                with self._lock:
                    waiting = list(self._prefetching.values())
                    self._prefetching.clear()
                for event in waiting:
                    event.set()              # nobody waits forever on a prefetch that will not run
                break
            try:
                started = False
                for name in self._groups.get(group, ()):
                    if self._closing:
                        break
                    with self._lock:
                        frames = self._cache.get(group)
                        if started and frames is None:
                            break                    # evicted meanwhile: no longer wanted
                        started = True
                        if frames is not None and name in frames:
                            continue
                        generation, scale, dpr = self._generation, self._scale, self._dpr
                    self._store(name, self._build(name, scale, dpr), generation, touch=False)
            except Exception:
                pass                         # a broken PNG is decoded (and logged) when played
            finally:
                with self._lock:
                    event = self._prefetching.pop(group, None)
                if event is not None:
                    event.set()

    def frames(self, names):
        return LazyFrames(self, names)

    def cached_groups(self):
        with self._lock:
            return list(self._cache)

    def decoded_groups(self):
        with self._lock:
            return set(self._decoded_groups)

    def cached_bytes(self):
        with self._lock:
            return sum(img.sizeInBytes() for frames in self._cache.values() for img in frames.values())

    def decodes_on(self, ident=None):
        """Decodes done by thread `ident` (default: the calling thread)."""
        with self._lock:
            return self.decodes_by_thread[threading.get_ident() if ident is None else ident]

    def opaque_span(self, name, alpha=128):
        """`opaque_span` of a frame, computed once per frame and display configuration
        (the wall snap asks for it at every climb start, on the UI thread)."""
        key = (name, alpha)
        with self._lock:
            span = self._spans.get(key)
        if span is None:
            span = opaque_span(self.frame(name), alpha)
            with self._lock:
                self._spans[key] = span
        return span

    # -- pixmaps (UI thread) ---------------------------------------------------------------
    def pixmap(self, image, mirror=False):
        """The label pixmap of a frame this store holds, created once per frame; None for a
        mirrored view or any other image (e.g. a transformed copy), which the caller converts
        each time. On the raster backend the pixmap shares the frame's pixels, so the cache
        adds no frame memory; a mirrored frame is a new image and is not kept. Pixmaps of
        frames the LRU dropped are released here, on the UI thread."""
        key = image.cacheKey()
        with self._lock:
            live = key in self._keys
            stale = [k for k in self._pixmaps if k not in self._keys]
        for k in stale:
            del self._pixmaps[k]
        if mirror or not live:
            return None
        pixmap = self._pixmaps.get(key)
        if pixmap is None:
            pixmap = self._pixmaps[key] = to_pixmap(image)
        return pixmap

    def cached_pixmaps(self):
        return len(self._pixmaps)

    def _build(self, name, scale=None, dpr=None):
        """Decode and scale one frame. Runs without the store lock (M3.2)."""
        scale = self._scale if scale is None else scale
        dpr = self._dpr if dpr is None else dpr
        source = QImage(str(self._paths[name]))
        if source.isNull():
            image = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
        else:
            if self._source_size is None:
                self._source_size = (source.width(), source.height())
            # Premultiply first: smooth scaling must weight colours by their alpha.
            image = source.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            w, h = physical_size(source.width(), source.height(), scale, dpr)
            if (w, h) != (source.width(), source.height()):
                image = image.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        image.setDevicePixelRatio(dpr)
        with self._lock:
            self.decode_log.append(name)
            self.decode_count += 1
            self.decodes_by_thread[threading.get_ident()] += 1
            self._decoded_groups.add(group_of(name))
        return image

    def _evict(self):
        recent = [g for g in self._cache if g not in self._pinned]
        # The most recently used group is last; keep the newest `keep_recent` unpinned ones, and
        # drop the oldest unpinned ones while the cache is over `max_bytes` (never the newest).
        drop = recent[:max(0, len(recent) - self._keep_recent)]
        kept = recent[len(drop):]
        total = sum(self._bytes.values()) - sum(self._bytes.get(g, 0) for g in drop)
        while len(kept) > 1 and total > self._max_bytes:
            group = kept.pop(0)
            drop.append(group)
            total -= self._bytes.get(group, 0)
        for group in drop:
            for image in self._cache[group].values():
                self._keys.pop(image.cacheKey(), None)
            del self._cache[group]
            self._bytes.pop(group, None)
            for key in [k for k in self._spans if group_of(k[0]) == group]:
                del self._spans[key]


def _frame_order(name):
    head, _, tail = name.rpartition('_')
    return (head, int(tail)) if tail.isdigit() else (name, -1)


def prefetch_frames(images):
    """Start the background prefetch of a clip's frame groups (no-op for plain frame lists)."""
    prefetch = getattr(images, 'prefetch', None)
    if prefetch is not None:
        try:
            prefetch()
        except Exception:
            pass


class LazyFrames(Sequence):
    """An action's frame list that decodes through its `FrameStore` only when read."""

    def __init__(self, store, names):
        self._store = store
        self._names = tuple(names)

    @property
    def names(self):
        return self._names

    @property
    def store(self):
        return self._store

    def __len__(self):
        return len(self._names)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return LazyFrames(self._store, self._names[index])
        return self._store.frame(self._names[index])

    def __iter__(self):
        for name in self._names:
            yield self._store.frame(name)

    def __bool__(self):
        return bool(self._names)

    def __mul__(self, times):
        return LazyFrames(self._store, self._names * int(times))

    __rmul__ = __mul__

    def __add__(self, other):
        if isinstance(other, LazyFrames) and other._store is self._store:
            return LazyFrames(self._store, self._names + other._names)
        return list(self) + list(other)

    def reversed(self):
        return LazyFrames(self._store, self._names[::-1])

    def prefetch(self):
        """Decode the frame groups of this clip on the store's background thread (M3.2)."""
        return self._store.prefetch(self._names)

    def __repr__(self):
        return 'LazyFrames(%d frames%s)' % (len(self._names), ', ' + group_of(self._names[0]) if self._names else '')
