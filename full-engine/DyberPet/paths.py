"""Resource root and per-user writable state; no state in the source tree."""
import os
import sys
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
    # A self-hosted relay (advanced): minidraconia_relay.json placed beside the executable is
    # copied into the profile on the first run (never over an existing copy). The public ZIP
    # has none (docs/SELF-HOSTED-RELAY.md).
    from DyberPet.brain_client import seed_relay_config
    seed_relay_config(target, install_dir())
    return target


def install_dir():
    """Folder of the executable (frozen build) or the repository root (source run)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return resource_root().parent
