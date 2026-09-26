if __name__ == "__main__":
    # First: a child process of the frozen exe (the noise-rule guard, ruling
    # R22) re-runs this script and must do its work instead of starting the app.
    import multiprocessing

    multiprocessing.freeze_support()
    from qtrequestory.cli import main

    raise SystemExit(main())
