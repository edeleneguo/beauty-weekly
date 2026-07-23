#!/usr/bin/env python3
"""Compatibility wrapper — generate_weekly.py redirects to generate_monthly.py.

The canonical module is now ``build/generate_monthly.py``.  This wrapper
exists solely so that existing imports (``from build.generate_weekly import ...``)
and the monthly-deploy workflow continue to work without changes.

When imported as a module, ``build.generate_weekly`` is aliased to
``build.generate_monthly`` in ``sys.modules`` so that monkeypatch/patch
of ``build.generate_weekly.call_llm`` affects ``generate_products`` globals.
When executed as a script, it calls ``build.generate_monthly.main()``.
"""

import sys

# Ensure the canonical module is loaded first.
import build.generate_monthly as _canonical  # noqa: F401

# Register this module as an alias to generate_monthly so that
# ``patch("build.generate_weekly.call_llm")`` patches the actual module
# attribute that generate_products() references.
sys.modules[__name__] = _canonical

# Re-export public names for ``from build.generate_weekly import X`` usage.
# After the sys.modules alias these resolve to the canonical module attributes.
generate_products = _canonical.generate_products
call_llm = _canonical.call_llm
parse_json_response = _canonical.parse_json_response
_align_cross_section_scores = _canonical._align_cross_section_scores
_build_manifest = _canonical._build_manifest
_build_scoring_json = _canonical._build_scoring_json
_find_supporting_articles = _canonical._find_supporting_articles
_make_launch_evidence = _canonical._make_launch_evidence
_select_category_relevant_articles = _canonical._select_category_relevant_articles

if __name__ == "__main__":
    sys.exit(_canonical.main())
