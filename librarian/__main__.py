import sys

if sys.version_info < (3, 14):
    sys.exit(f"Offline Librarian needs Python 3.14 or later; found {sys.version.split()[0]}. "
             "Set OFFLINE_LIBRARIAN_PYTHON to a newer python3.")

from librarian.cli import main  # noqa: E402

sys.exit(main())
