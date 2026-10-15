"""PyInstaller's absolute-import entry point; application owns CLI behavior."""
from tracertool.app import main


if __name__ == "__main__":
    raise SystemExit(main())
