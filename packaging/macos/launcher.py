"""PyInstaller entry point for Papple Music.app."""

import multiprocessing

if __name__ == "__main__":
    # gamdl uses multiprocessing; in a frozen app the child processes start here.
    multiprocessing.freeze_support()
    from gamdl_web.macapp import main

    main()
