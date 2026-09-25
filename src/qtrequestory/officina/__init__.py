"""Officina: initiatives/cases (TARGET/AS-IS/TO-BE), generation against the
Quadient Inspire Scaler documentGenerator, side-by-side text comparison, and
delivery to testers.

This package must stay light to import: ``qtrequestory.cli`` imports the core
eagerly on every run, including the hourly ``--sync`` job, and nothing here
may pull that path into loading ``pypdfium2`` (a ~10 MB binary dependency).
Only ``qtrequestory.officina.pdf`` may import ``pypdfium2`` — see
``tests/test_officina_boundary.py``.
"""
