"""Transparent GL fixture: pause GL bytes while production input keeps running."""
from pathlib import Path
import select
import socket
import threading
import time


class GlStall:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = str(self.directory / "gl-proxy.sock")
        self.closed = threading.Event()
        self.error = None

    def __enter__(self):
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(1)
        self.listener.settimeout(10)
        self.thread = threading.Thread(target=self.forward, daemon=True)
        self.thread.start()
        return self

    def forward(self):
        try:
            with self.listener.accept()[0] as guest, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as host:
                host.settimeout(3)
                guest.settimeout(3)
                host.connect(str(self.directory / "gles.sock"))
                paused = False
                while not self.closed.is_set():
                    if not paused and (self.directory / "stall.begin").exists():
                        paused = True
                        (self.directory / "stall.ready").touch()
                        deadline = time.monotonic() + 3
                        while not (self.directory / "stall.release").exists() and not self.closed.wait(.005):
                            if time.monotonic() > deadline:
                                raise TimeoutError("GL pause was not released")
                    for source in select.select([guest, host], [], [], .005)[0]:
                        data = source.recv(65536)
                        if not data:
                            (host if source is guest else guest).shutdown(socket.SHUT_WR)
                            return
                        (host if source is guest else guest).sendall(data)
        except Exception as error:
            if not self.closed.is_set():
                self.error = str(error)

    def __exit__(self, *_):
        self.closed.set()
        self.listener.close()
        self.thread.join(timeout=4)
        if self.thread.is_alive():
            raise RuntimeError("GL stall fixture did not stop")
        if self.error:
            raise RuntimeError(self.error)
