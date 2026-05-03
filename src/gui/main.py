def main():
    from src.peer.client import PEER_LOG_FILE
    from src.common.logging_config import setup_logging

    setup_logging(log_file=PEER_LOG_FILE)

    try:
        from src.gui.main_window import main as run_gui
    except ModuleNotFoundError as exc:
        if exc.name == "_tkinter":
            print(
                "Tkinter is not available in this Python installation. "
                "Install/use a Python build with Tk support to run the GUI."
            )
            return 1
        raise

    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
