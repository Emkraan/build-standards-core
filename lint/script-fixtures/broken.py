# Does not parse, so the lint falls back to a text match.
import subprocess
def f(:
    subprocess.run('ls', shell=True)
