"""Plugin loader: imports every PLUGIN from panel/plugins/*.py and the user plugin folder.

Bundled plugins live next to this file; user plugins go to $OSINT_PLUGIN_DIR (default <data dir>/plugins_user).
A broken plugin is skipped and reported in LOAD_ERRORS instead of stopping the panel.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOADED = []          # plugin dicts
LOAD_ERRORS = []     # (file, error)
REQUIRED = ("id", "title", "group", "fields", "run")


def user_dir():
    import store
    return os.environ.get("OSINT_PLUGIN_DIR") or os.path.join(store.DATA_DIR, "plugins_user")


def _load_file(path, taken):
    name = "osint_plugin_" + re.sub(r"\W", "_", os.path.splitext(os.path.basename(path))[0])
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    plugin = getattr(mod, "PLUGIN", None)
    if not isinstance(plugin, dict):
        raise ValueError("PLUGIN dict not found")
    missing = [k for k in REQUIRED if k not in plugin]
    if missing:
        raise ValueError("missing keys: " + ", ".join(missing))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", plugin["id"]):
        raise ValueError(f"invalid id {plugin['id']!r}")
    if plugin["id"] in taken:
        raise ValueError(f"id {plugin['id']!r} is already used")
    plugin.setdefault("icon", "box")
    plugin.setdefault("desc", "")
    plugin["plugin"] = os.path.basename(path)
    return plugin


def load_all(registry, by_id, about):
    """Register plugins into the tool registry (called once at start-up)."""
    LOADED.clear()
    LOAD_ERRORS.clear()
    files = []
    dirs = []
    for d in (HERE, user_dir()):
        if os.path.isdir(d) and os.path.realpath(d) not in dirs:
            dirs.append(os.path.realpath(d))
    for d in dirs:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py") and not f.startswith("_")]
    for path in files:
        try:
            p = _load_file(path, set(by_id))
        except Exception as e:  # noqa: BLE001 — a broken plugin must not take the panel down
            LOAD_ERRORS.append((os.path.basename(path), f"{type(e).__name__}: {e}"))
            continue
        registry.append(p)
        by_id[p["id"]] = p
        if p.get("about"):
            about[p["id"]] = p["about"]
        LOADED.append(p)
    return LOADED
