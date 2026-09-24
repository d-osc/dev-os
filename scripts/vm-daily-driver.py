"""After the GUI login: verify the Ubuntu-daily-driver stack in-session."""
import socket
import time

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/home/ondev/devos-vm/serial.sock')
s.settimeout(0.3)


def drain(t):
    end = time.monotonic() + t
    d = b''
    while time.monotonic() < end:
        try:
            c = s.recv(4096)
            if c:
                d += c
        except socket.timeout:
            pass
    return d.decode('utf-8', 'replace')


def run(cmd, wait=1.5, collect=4.0):
    s.sendall(cmd.encode() + b'\n')
    time.sleep(wait)
    return drain(collect)


for _ in range(3):
    s.sendall(b'\x03')
    time.sleep(0.3)
drain(0.8)
run('\n', 0.8, 1.2)
run('root', 1.0, 1.0)
run('mSJlOJ51W6nbaiC83JRqybPv', 1.5, 1.2)
run('stty -echo', 0.5, 0.6)

print('--- session procs')
print(run('ps w | grep -vE "grep|\\[" | grep -E "openbox|dev-shell|xterm" | head -4', 2.0, 3.5)[:400])
print('--- sound')
print(run('aplay -l 2>&1 | head -4', 2.0, 3.5)[:400])
print(run('python3 -c "import struct,wave; w=wave.open(\'/tmp/t.wav\',\'w\'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(struct.pack(\'<4000h\', *[int(6000 if i%50<25 else -6000) for i in range(4000)])); w.close()" && aplay /tmp/t.wav 2>&1 | tail -2; echo APLAY-RC=$?', 6.0, 5.0)[:400])
print('--- thai toast')
print(run('su - dev -c "DISPLAY=:0 /usr/bin/dev-notify \\"สวัสดี Dev OS\\" \\"ทดสอบการแจ้งเตือน\\"" 2>&1; echo NOTIFY-RC=$?', 2.0, 3.5)[:300])
print('--- xterm')
print(run('su - dev -c "DISPLAY=:0 nohup /usr/bin/xterm -geometry 60x16+120+120 > /dev/null 2>&1 & echo XTERM-BG"', 2.0, 3.0)[:200])
