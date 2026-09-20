"""Use repository core while developing; release builder embeds that exact core."""
import importlib
import importlib.util
from pathlib import Path

if importlib.util.find_spec('dpk_sdk._dev') is not None:
    core = importlib.import_module('dpk_sdk._dev')
else:
    location = Path(__file__).resolve().parents[2] / 'tools/dev.py'
    if not location.is_file():
        raise ImportError('DPK core missing. Install the SDK release wheel or use the repository checkout.')
    spec = importlib.util.spec_from_file_location('dpk_sdk._dev_core', location)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
