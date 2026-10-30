import socket

from src.core.logger import logger


class RosettaSocketClient:
    def __init__(self, host: str, port: int, timeout_seconds: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def exchange(self, xml_payload: bytes) -> bytes:
        logger.info(
            "Connecting to Rosetta host=%s port=%s timeout_seconds=%s",
            self.host,
            self.port,
            self.timeout_seconds,
        )
        try:
            connection = socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            )
        except TimeoutError:
            logger.error(
                "Rosetta TCP connect timed out host=%s port=%s timeout_seconds=%s",
                self.host,
                self.port,
                self.timeout_seconds,
            )
            raise
        except OSError as error:
            logger.error(
                "Rosetta TCP connect failed host=%s port=%s error=%s",
                self.host,
                self.port,
                error,
            )
            raise
        with connection:
            logger.info(
                "Rosetta connected host=%s port=%s",
                self.host,
                self.port,
            )
            connection.settimeout(self.timeout_seconds)
            connection.sendall(xml_payload)
            logger.info(
                "Rosetta request sent host=%s port=%s bytes=%s",
                self.host,
                self.port,
                len(xml_payload),
            )
            chunks: list[bytes] = []
            try:
                while chunk := connection.recv(4096):
                    chunks.append(chunk)
            except socket.timeout as error:
                received = sum(map(len, chunks))
                logger.error(
                    "Rosetta response timed out host=%s port=%s bytes=%s error=TimeoutError: %s",
                    self.host,
                    self.port,
                    received,
                    error,
                )
                raise TimeoutError(
                    f"Timed out waiting for Rosetta response after {received} bytes"
                ) from error
        response = b"".join(chunks)
        logger.info("Rosetta response received bytes=%s", len(response))
        if not response:
            raise RuntimeError("Rosetta returned an empty response")
        return response