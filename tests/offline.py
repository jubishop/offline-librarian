"""Imported by every test module: a test that tries to reach anything but this computer fails at once, instead of
quietly downloading from the internet (as one did before this guard)."""
import socket

LOCAL = {"127.0.0.1", "::1", "localhost"}
_getaddrinfo = socket.getaddrinfo
_connect = socket.socket.connect


def _local(host):
    return host is None or str(host) in LOCAL or str(host).startswith("127.")


def _getaddrinfo_local(host, *args, **kwargs):
    if not _local(host):
        raise OSError(f"tests must not reach the internet (looked up {host})")
    return _getaddrinfo(host, *args, **kwargs)


def _connect_local(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address[0]):
        raise OSError(f"tests must not reach the internet (connected to {address[0]})")
    return _connect(self, address)


socket.getaddrinfo = _getaddrinfo_local
socket.socket.connect = _connect_local
