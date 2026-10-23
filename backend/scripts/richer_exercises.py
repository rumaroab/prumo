"""Generate the versioned fire exercises without altering saved results."""
from backend.app.demo_exercises import *

if __name__ == "__main__":
    import sys
    for name in sys.argv[1:] or ["cell2fire", "mtt"]:
        print(generate(name), flush=True)
