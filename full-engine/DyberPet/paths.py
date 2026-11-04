"""Resource root and per-user writable state; no state in the source tree."""
import os
from pathlib import Path
import shutil


def resource_root():
    return Path(__file__).resolve().parents[1]


def user_root():
    explicit = os.environ.get('MINIDRACONIA_TEST_PROFILE', '')
    if not explicit or not Path(explicit).is_absolute():
        raise RuntimeError('An explicit absolute isolated profile is required')
    base = Path(explicit).resolve()
    if base.is_relative_to(resource_root()):
        raise RuntimeError('The profile must be outside the engine tree')
    return base/'MiniDraconia'


def data_dir():
    return user_root()/'data'


def initialize_user_data():
    target = data_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name in ['settings.json', 'draconia_brain.json', 'draconia_lines.json']:
        src = resource_root()/'data'/name
        dst = target/name
        if src.is_file() and not dst.exists():
            shutil.copyfile(src, dst)
    return target
