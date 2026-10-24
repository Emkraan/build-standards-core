# Every call below runs a shell command line.
import os
import subprocess

subprocess.run('ls -l', shell=True)
os.system('ls')
out = subprocess.getoutput('ls')
subprocess.check_output('ls', shell=True)  # core-exception: EXC-002 has expired
