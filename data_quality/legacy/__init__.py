"""The original single-tier implementation, kept as the comparison baseline.

These modules predate the two-tier rewrite and are what the dissertation
compares against in the results chapter.  They are retained because that
comparison is measured evidence, not because they are the current design: the
live engine is :mod:`data_quality.engine`, and the live pipeline is
:mod:`data_quality.pipeline`.

Besides the tests, ``app.py``, :mod:`data_quality.preprocess.clean` and the
reporting figures still import from here; the new engine, validator and
pipeline do not.
"""
