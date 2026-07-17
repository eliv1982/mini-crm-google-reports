from __future__ import annotations

from gui.app import create_app


def main() -> int:
    app = create_app()
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
