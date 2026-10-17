import importlib  # abk-shim
import sys  # abk-shim

_PKG = __package__ or None  # abk-shim
_REL = "." if _PKG else ""  # abk-shim
_MOD = importlib.import_module(_REL + "e2e_cmd", _PKG)  # abk-shim
sys.modules[__name__] = _MOD  # abk-shim
