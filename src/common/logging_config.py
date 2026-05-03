import logging


LOGGER_NAME = "P2P-IsoDistrib"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def get_logger(name=LOGGER_NAME):
    return logging.getLogger(name)


def setup_logging(log_file=None, level=logging.INFO, logger_name=LOGGER_NAME):
    logger = get_logger(logger_name)
    if getattr(logger, "_p2p_configured", False):
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Unable to create log file %s: %s", log_file, exc)

    logger._p2p_configured = True
    return logger

