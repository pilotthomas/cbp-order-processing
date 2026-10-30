from src.core.config import get_pyodbc_connection_string
from src.core.logger import logger


def get_connection():
    import pyodbc

    connection_string = get_pyodbc_connection_string()
    logger.debug("Opening SQL connection")
    return pyodbc.connect(connection_string, timeout=10)
