"""One import boundary for the Bempp 0.3/0.4 namespace change."""
import importlib
import importlib.metadata


def api():
    try:
        return importlib.import_module("bempp_cl.api")
    except ModuleNotFoundError as error:
        if error.name not in ("bempp_cl", "bempp_cl.api"):
            raise
        return importlib.import_module("bempp.api")


def versions():
    return {name: importlib.metadata.version(name) for name in
            ("bempp-cl", "numpy", "scipy", "numba", "llvmlite", "meshio", "matplotlib", "pyyaml", "psutil")}

