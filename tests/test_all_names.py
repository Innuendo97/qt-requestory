"""Every name a module lists in ``__all__`` exists in it: a star import of
any ``qtrequestory`` module must not fail (final review M1: a name moved to
another module and left in the old ``__all__``)."""
from __future__ import annotations

import importlib
import pkgutil

import pytest

import qtrequestory

SKIP = ("qtrequestory.__main__",)  # runs the application


def _modules() -> list[str]:
    return sorted(m.name for m in pkgutil.walk_packages(qtrequestory.__path__, "qtrequestory.")
                  if m.name not in SKIP)


@pytest.mark.parametrize("name", _modules())
def test_every_name_in_all_exists(name: str):
    module = importlib.import_module(name)
    missing = [n for n in getattr(module, "__all__", ()) if not hasattr(module, n)]
    assert not missing, f"{name}.__all__ lists names it does not define: {missing}"
