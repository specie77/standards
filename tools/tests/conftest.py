import sys
from pathlib import Path

# tools/ holds the scripts under test; add it to the path so tests can import
# them by module name without packaging the directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
