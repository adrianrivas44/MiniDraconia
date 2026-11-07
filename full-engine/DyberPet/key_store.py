"""The user's own API key, stored encrypted on this device and never in plain text.

On Windows the key is encrypted with DPAPI for the current Windows user (`CryptProtectData`
through ctypes, no extra dependency): only the same user on the same machine can decrypt it.
Other platforms have no codec here, so a key cannot be saved there at all (tests inject one).

The file (`own_key.dpapi` in the profile) holds only the encrypted blob. The key is never put in
settings, logs, crash reports or diagnostics, and `repr()` of these objects never shows it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

KEY_FILE = 'own_key.dpapi'
_DESCRIPTION = 'MiniDraconia own AI key'
_ENTROPY = b'MiniDraconia own-key v1'


class KeyStoreUnavailable(RuntimeError):
    """No way to encrypt the key on this system: it is not saved."""


class DpapiCodec:
    """Windows DPAPI, CurrentUser scope, no UI."""

    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def __init__(self):
        if sys.platform != 'win32':
            raise KeyStoreUnavailable('DPAPI exists only on Windows')
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        self._ctypes = ctypes
        self._Blob = Blob
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def _blob(self, data: bytes):
        buffer = self._ctypes.create_string_buffer(data, len(data))
        blob = self._Blob(len(data), self._ctypes.cast(buffer, self._ctypes.POINTER(self._ctypes.c_char)))
        return blob, buffer

    def _take(self, blob) -> bytes:
        try:
            return self._ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            self._kernel32.LocalFree(self._ctypes.cast(blob.pbData, self._ctypes.c_void_p))

    def protect(self, data: bytes) -> bytes:
        source, _keep = self._blob(data)
        entropy, _keep2 = self._blob(_ENTROPY)
        out = self._Blob()
        if not self._crypt32.CryptProtectData(self._ctypes.byref(source), _DESCRIPTION,
                                              self._ctypes.byref(entropy), None, None,
                                              self.CRYPTPROTECT_UI_FORBIDDEN, self._ctypes.byref(out)):
            raise KeyStoreUnavailable('CryptProtectData failed')
        return self._take(out)

    def unprotect(self, data: bytes) -> bytes:
        source, _keep = self._blob(data)
        entropy, _keep2 = self._blob(_ENTROPY)
        out = self._Blob()
        if not self._crypt32.CryptUnprotectData(self._ctypes.byref(source), None,
                                                self._ctypes.byref(entropy), None, None,
                                                self.CRYPTPROTECT_UI_FORBIDDEN, self._ctypes.byref(out)):
            raise KeyStoreUnavailable('CryptUnprotectData failed')
        return self._take(out)


def default_codec():
    """DPAPI on Windows; None elsewhere (no key can be saved)."""
    try:
        return DpapiCodec()
    except Exception:
        return None


class KeyStore:
    def __init__(self, path, codec=None):
        self.path = Path(path)
        self._codec = codec

    def __repr__(self):
        return 'KeyStore(%r)' % str(self.path)

    @property
    def available(self) -> bool:
        return self._codec is not None

    def has_key(self) -> bool:
        return self.path.is_file()

    def save(self, api_key: str) -> None:
        """Encrypt and store the key (atomically). Raises KeyStoreUnavailable without a codec."""
        api_key = str(api_key or '').strip()
        if not api_key:
            raise ValueError('empty key')
        if self._codec is None:
            raise KeyStoreUnavailable('no encryption available: the key is not saved')
        blob = self._codec.protect(api_key.encode('utf-8'))
        if not blob or api_key.encode('utf-8') in blob:
            raise KeyStoreUnavailable('encryption returned the key unchanged: not saved')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.tmp')
        with open(temp, 'wb') as out:
            out.write(blob)
        os.replace(temp, self.path)

    def load(self) -> Optional[str]:
        """The decrypted key, or None (no key, no codec, or it cannot be decrypted here)."""
        if self._codec is None:
            return None
        try:
            blob = self.path.read_bytes()
        except OSError:
            return None
        try:
            key = self._codec.unprotect(blob).decode('utf-8').strip()
        except Exception:
            return None
        return key or None

    def forget(self) -> bool:
        """Delete the stored key. True when a key file was removed."""
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


def key_store(codec='default') -> KeyStore:
    """The profile's key store (codec: DPAPI on Windows unless one is injected)."""
    from DyberPet.paths import user_root
    return KeyStore(user_root() / KEY_FILE, default_codec() if codec == 'default' else codec)
