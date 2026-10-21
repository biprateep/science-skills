"""Local credential access and storage without network validation."""

import json
import os
import shutil
import subprocess
import sys
from cite_check_engine import config as _engine_config


_SERVICE = "cite-check"

KEYS = {
    "ads": {"label": "NASA ADS API token", "secret": True,
            "env": ("ADS_API_TOKEN", "ADS_DEV_KEY", "ADS_TOKEN"),
            "legacy_files": ("~/.ads/dev_key", "~/.config/cite-check/ads_token"),
            "url": "https://ui.adsabs.harvard.edu/user/settings/token",
            "enables": "ADS search, bibcode resolution and ADS BibTeX export (astronomy/physics)"},
    "mailto": {"label": "contact e-mail for the Crossref/OpenAlex polite pools", "secret": False,
               "env": ("CITE_CHECK_MAILTO",), "legacy_files": (), "url": None,
               "enables": "faster, more reliable Crossref and OpenAlex answers (optional, not a key)"},
    "semanticscholar": {
        "label": "Semantic Scholar API key (optional discovery)",
        "secret": True, "env": ("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
        "legacy_files": (),
        "url": "https://www.semanticscholar.org/product/api",
        "enables": "optional Semantic Scholar discovery (not verification)",
    },
    "github": {"label": "GitHub token (read-only, no scopes needed)", "secret": True,
               "env": ("GITHUB_TOKEN", "GH_TOKEN"), "legacy_files": (),
               "url": "https://github.com/settings/personal-access-tokens/new",
               "enables": "GitHub repository checks at 5000 requests/hour instead of 60 (public repositories work without it)"},
}

_key_cache: dict = {"values": {}}

def _config_dir() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), _SERVICE)

def _keyring_backend() -> str | None:
    """'macos-keychain' | 'secret-tool' | None, probed once per process.
    CITE_CHECK_KEYRING=file forces the file store; =off disables stored keys."""
    if "backend" in _key_cache:
        return _key_cache["backend"]
    backend = None
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() == "auto":
        try:
            if sys.platform == "darwin" and shutil.which("security"):
                backend = "macos-keychain"
            elif shutil.which("secret-tool") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
                r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", "__probe__"],
                                   capture_output=True, text=True, timeout=8)
                if r.returncode in (0, 1) and not r.stderr.strip():   # 1 = not found, no daemon error
                    backend = "secret-tool"
        except (subprocess.TimeoutExpired, OSError):
            backend = None
    _key_cache["backend"] = backend
    return backend

def _keyring_get(name: str) -> str | None:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "find-generic-password", "-s", _SERVICE, "-a", name, "-w"],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "lookup", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return None
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        return None

def _keyring_set(name: str, value: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":   # `security -i` reads the command from stdin: the secret stays off argv
            cmd = f'add-generic-password -U -s "{_SERVICE}" -a "{name}" -l "{_SERVICE} {name}" -w "{value}"\n'
            r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=15)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "store", f"--label={_SERVICE} {name}", "service", _SERVICE, "key", name],
                               input=value, capture_output=True, text=True, timeout=15)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False

def _keyring_delete(name: str) -> bool:
    b = _keyring_backend()
    try:
        if b == "macos-keychain":
            r = subprocess.run(["security", "delete-generic-password", "-s", _SERVICE, "-a", name],
                               capture_output=True, text=True, timeout=10)
        elif b == "secret-tool":
            r = subprocess.run(["secret-tool", "clear", "service", _SERVICE, "key", name],
                               capture_output=True, text=True, timeout=10)
        else:
            return False
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False

def _file_key_path(name: str) -> str:
    return os.path.join(_config_dir(), "keys", name)

def _file_get(name: str) -> str | None:
    path = _file_key_path(name)
    if not os.path.exists(path):
        return None
    if os.stat(path).st_mode & 0o077:
        _key_cache.setdefault("warnings", []).append(f"{path} is readable by others — run: chmod 600 {path}")
    with open(path) as fh:
        return fh.read().strip() or None

def _file_set(name: str, value: str) -> None:
    path = _file_key_path(name)
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)      # makedirs applies the mode to the leaf only
    os.chmod(d, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)

def _config_read() -> dict:
    path = os.path.join(_config_dir(), "config.json")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return {}

def _config_write(cfg: dict) -> None:
    os.makedirs(_config_dir(), mode=0o700, exist_ok=True)
    os.chmod(_config_dir(), 0o700)
    path = os.path.join(_config_dir(), "config.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh, indent=2)

def key_value(name: str) -> tuple:
    """(value | None, source) for a configured key: environment first, then
    the keychain, the 0600 file, legacy files; non-secrets from config.json.
    Cached per process — the keychain is a subprocess call."""
    spec = KEYS[name]
    for var in spec["env"]:
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), f"env:{var}"
    if name in _key_cache["values"]:
        return _key_cache["values"][name]
    value, source = None, "none"
    if os.environ.get("CITE_CHECK_KEYRING", "auto").lower() != "off":
        if spec["secret"]:
            value = _keyring_get(name)
            source = _keyring_backend() or "none"
            if not value:
                value, source = _file_get(name), "file"
            if not value:
                for lf in spec["legacy_files"]:
                    path = os.path.expanduser(lf)
                    if os.path.exists(path):
                        with open(path) as fh:
                            value = fh.read().strip() or None
                        if value:
                            source = f"legacy-file:{lf}"
                            break
        else:
            value, source = _config_read().get(name), "config"
    if not value:
        source = "none"
    _key_cache["values"][name] = (value, source)
    return value, source

def _mask(value: str) -> str:
    return ("…" + value[-4:]) if len(value) >= 8 else "…"

def _file_delete(name: str) -> bool:
    path = _file_key_path(name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False

def key_delete(name: str) -> dict:
    if name not in KEYS:
        return {"deleted": False, "error": f"unknown key {name!r}"}
    removed = []
    if KEYS[name]["secret"]:
        if _keyring_delete(name):
            removed.append(_keyring_backend())
        if _file_delete(name):
            removed.append("file")
    else:
        cfg = _config_read()
        if name in cfg:
            del cfg[name]
            _config_write(cfg)
            removed.append("config")
    _key_cache["values"].pop(name, None)
    return {"deleted": bool(removed), "removed_from": removed}

def key_status() -> list:
    out = []
    for name, spec in KEYS.items():
        value, source = key_value(name)
        out.append({"name": name, "label": spec["label"], "secret": spec["secret"], "url": spec["url"],
                    "enables": spec["enables"], "configured": bool(value), "source": source,
                    "masked": (_mask(value) if spec["secret"] else value) if value else None})
    return out

def _mailto() -> str:
    return (key_value("mailto")[0] or "").strip()

def _user_agent() -> str:
    ua = f"cite-check/{_engine_config.VERSION} (+https://github.com/biprateep/science-skills"
    return ua + (f"; mailto:{_mailto()})" if _mailto() else ")")

def _ads_token() -> str:
    return key_value("ads")[0] or ""

def _github_token() -> str:
    return (key_value("github")[0] or "").strip()
