"""Entry point for the packaged executable.

PyInstaller runs its entry script as a top-level module, not as part of a
package, so `igprep/__main__.py` and its relative imports cannot be used here.
This uses an absolute import instead.

For running from source, prefer: python -m igprep
"""

import sys

from igprep.gui.main import main

if __name__ == "__main__":
    sys.exit(main())
