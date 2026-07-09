from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-persona")
except PackageNotFoundError:  # not installed (e.g. running from source tree)
    __version__ = "0.0.0"
