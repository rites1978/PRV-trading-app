import sys
import os

# Ensure src is on python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Launch production dashboard
import src.dashboard.app
