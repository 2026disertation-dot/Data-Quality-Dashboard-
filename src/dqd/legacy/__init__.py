"""The original single-tier implementation, kept as the comparison baseline.

These modules predate the two-tier rewrite and are what the dissertation
compares against in the results chapter.  They are retained because that
comparison is measured evidence, not because they are the current design: the
live engine is :mod:`dqd.engine`, and the live pipeline is
:mod:`dqd.pipeline`.

Nothing outside this package and the tests should import from here.
"""
