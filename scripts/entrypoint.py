"""The script PyInstaller freezes: the same lines as ``qtrequestory.__main__``.

A file of its own, outside the package, on purpose. PyInstaller prepends the
entry script's own directory to ``sys.path``; had the entry point been
``src/qtrequestory/__main__.py``, that would have been ``src/qtrequestory``,
making ``core`` and ``ui`` importable as top-level packages as well as under
``qtrequestory`` — two copies of the same modules in one build, with two copies
of every module-level cache. From ``scripts/`` there is nothing to shadow.
"""
if __name__ == "__main__":
    # First: a child process of the frozen exe (the noise-rule guard, ruling
    # R22) re-runs this script and must do its work instead of starting the app.
    import multiprocessing

    multiprocessing.freeze_support()
    from qtrequestory.cli import main

    raise SystemExit(main())
