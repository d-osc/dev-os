import subprocess
import time

subprocess.run(['dev-notify', 'Dev OS พร้อมใช้งาน', 'Background ส่งการแจ้งเตือนได้แล้ว'], check=True)
while True:
    time.sleep(60)
