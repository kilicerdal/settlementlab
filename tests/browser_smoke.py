"""Legacy browser runner; maintained for existing commands."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).parent/"browser"/"smoke.py"),run_name="__main__")
