#!/usr/bin/env python3
"""vm-session.py without the trailing poweroff: the VM stays up."""
import sys

sys.argv[0] = 'vm-session'
exec(open('/mnt/c/Users/ondev/Projects/dev-os/scripts/vm-session.py').read()
     .replace("    sock.sendall(b'poweroff\\n')\n    time.sleep(3)\n", ''))
