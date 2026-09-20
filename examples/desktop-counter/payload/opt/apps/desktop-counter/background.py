#!/usr/bin/python3
import json
import os
from pathlib import Path
import time

data = Path(os.environ['DEVOS_DATA_DIR'])
path = data / 'counter.json'
try:
    ticks = int(json.loads(path.read_text())['ticks'])
except (OSError, ValueError, KeyError):
    ticks = 0
while True:
    ticks += 1
    temporary = data / 'counter.new'
    temporary.write_text(json.dumps({'ticks': ticks, 'updated': time.time()}))
    temporary.replace(path)
    time.sleep(1)
