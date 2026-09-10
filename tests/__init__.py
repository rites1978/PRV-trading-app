"""Test package initialiser.

Arms the external network guard for every suite run, so no test can reach
Supabase, Yahoo Finance or any other host. Importing `tests.<module>` (which is how
`python -m unittest tests.x` loads a suite) runs this first.
"""
from src.core.test_network_guard import install as _install_network_guard

_install_network_guard()
