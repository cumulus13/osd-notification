#!/usr/bin/env python3
"""
File: test_server_integration.py
Description: End-to-end tests over real loopback sockets — NotificationClient
             -> NotificationServerManager -> captured NotificationPayload —
             specifically to guarantee GNTP and UDP deliver equivalent
             payloads (title, text, icon, sticky, timeout), since icon
             handling for GNTP was a reported regression risk.
License: MIT
"""

import socket
import time

import pytest

from osd_notification.client import NotificationClient
from osd_notification.protocol import NotificationPayload
from osd_notification.server import NotificationServerManager


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def running_server():
    received = []
    gntp_port = _free_port()
    udp_port = _free_port()

    server = NotificationServerManager(
        host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port,
        payload_handler=received.append,
    )
    server.start()
    time.sleep(0.2)
    try:
        yield server, received, gntp_port, udp_port
    finally:
        server.stop()


def _make_png_bytes() -> bytes:
    import struct
    import zlib

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _wait_for(received, count, timeout=3.0):
    deadline = time.time() + timeout
    while len(received) < count and time.time() < deadline:
        time.sleep(0.02)
    return received


def test_udp_delivers_payload_with_icon(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="UDP Title", text="udp body", icon=str(icon), sticky=True,
                timeout=1234, transport="udp")

    _wait_for(received, 1)
    assert len(received) == 1
    payload = received[0]
    assert payload.title == "UDP Title"
    assert payload.text == "udp body"
    assert payload.icon == str(icon)
    assert payload.sticky is True
    assert payload.timeout == 1234


def test_gntp_delivers_payload_with_icon(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="GNTP Title", text="gntp body", icon=str(icon), sticky=True,
                timeout=1234, transport="gntp")

    _wait_for(received, 1)
    assert len(received) == 1
    payload = received[0]
    assert payload.title == "GNTP Title"
    assert payload.text == "gntp body"
    # Spec-compliant: header is an x-growl-resource reference and the
    # actual bytes arrive as the inline binary section.
    assert payload.icon.startswith("x-growl-resource://")
    assert payload.icon_data == icon.read_bytes()
    assert payload.sticky is True
    assert payload.timeout == 1234


def test_gntp_and_udp_deliver_equivalent_payloads_for_the_same_icon(running_server, tmp_path):
    """The direct regression check: sending the exact same notification
    content over both transports must resolve to the exact same icon
    field (and other fields), so whatever renders for one renders
    identically for the other."""
    server, received, gntp_port, udp_port = running_server
    icon = tmp_path / "shared_icon.png"
    icon.write_bytes(b"\x89PNG\r\n")

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="Same", text="same body", icon=str(icon), transport="udp")
    client.send(title="Same", text="same body", icon=str(icon), transport="gntp")

    _wait_for(received, 2)
    assert len(received) == 2

    udp_payload = next(p for p in received if p.source.startswith("udp"))
    gntp_payload = next(p for p in received if p.source == "gntp")

    assert udp_payload.title == gntp_payload.title
    assert udp_payload.text == gntp_payload.text
    # The image itself must arrive byte-identical over both transports.
    assert udp_payload.icon_data == gntp_payload.icon_data == icon.read_bytes()
    assert udp_payload.sticky == gntp_payload.sticky


def test_gntp_without_icon_has_none_icon(running_server):
    server, received, gntp_port, udp_port = running_server
    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="No Icon", text="body", transport="gntp")

    _wait_for(received, 1)
    assert received[0].icon is None


def test_udp_without_icon_has_none_icon(running_server):
    server, received, gntp_port, udp_port = running_server
    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="No Icon", text="body", transport="udp")

    _wait_for(received, 1)
    assert received[0].icon is None


def test_gntp_rejects_non_gntp_line(running_server):
    """Malformed/non-GNTP data on the TCP port must not crash the server or
    reach the payload handler."""
    server, received, gntp_port, udp_port = running_server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.connect(("127.0.0.1", gntp_port))
    sock.sendall(b"NOT A GNTP REQUEST\r\n\r\n")
    sock.close()
    time.sleep(0.2)
    assert len(received) == 0


def test_gntp_inline_icon_is_real_image_bytes_end_to_end(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    png = _make_png_bytes()
    icon = tmp_path / "real.png"
    icon.write_bytes(png)

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="Real", text="b", icon=str(icon), transport="gntp")

    _wait_for(received, 1)
    assert received[0].icon_data == png


def test_gntp_http_icon_url_is_passed_through_not_embedded(running_server):
    server, received, gntp_port, udp_port = running_server
    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="Url", text="b", icon="http://example.invalid/icon.png", transport="gntp")

    _wait_for(received, 1)
    assert received[0].icon == "http://example.invalid/icon.png"
    assert received[0].icon_data is None  # allow_icon_urls is off by default


def test_gntp_missing_local_icon_falls_back_to_plain_header(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="Gone", text="b", icon=str(tmp_path / "missing.png"), transport="gntp")

    _wait_for(received, 1)
    assert received[0].icon == str(tmp_path / "missing.png")
    assert received[0].icon_data is None


def test_gntp_second_notification_on_new_connection_after_binary_send(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    icon = tmp_path / "i.png"
    icon.write_bytes(_make_png_bytes())

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="One", text="b", icon=str(icon), transport="gntp")
    client.send(title="Two", text="b", transport="gntp")

    _wait_for(received, 2)
    assert [p.title for p in received] == ["One", "Two"]
    assert received[1].icon_data is None


def test_gntp_icon_url_fetched_when_allowed(tmp_path):
    import http.server
    import threading

    png = _make_png_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/icon.png"

    received = []
    gntp_port, udp_port = _free_port(), _free_port()
    server = NotificationServerManager(
        host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port,
        payload_handler=received.append, allow_icon_urls=True,
    )
    server.start()
    time.sleep(0.2)
    try:
        client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
        client.send(title="Fetch", text="b", icon=url, transport="gntp")
        client.send(title="FetchUdp", text="b", icon=url, transport="udp")
        _wait_for(received, 2)
    finally:
        server.stop()
        httpd.shutdown()

    assert len(received) == 2
    assert all(p.icon_data == png for p in received)


def test_raw_third_party_gntp_request_with_inline_resource(running_server):
    """A request written byte-by-byte per the GNTP spec (as another
    Growl-compatible sender would produce it), not via our own client."""
    server, received, gntp_port, udp_port = running_server
    png = _make_png_bytes()

    request = (
        b"GNTP/1.0 NOTIFY NONE\r\n"
        b"Application-Name: ThirdParty\r\n"
        b"Notification-Name: Alert\r\n"
        b"Notification-Title: From elsewhere\r\n"
        b"Notification-Text: raw spec request\r\n"
        b"Notification-Icon: x-growl-resource://deadbeef\r\n"
        b"\r\n"
        b"Identifier: deadbeef\r\n"
        b"Length: " + str(len(png)).encode() + b"\r\n"
        b"\r\n" + png + b"\r\n\r\n"
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect(("127.0.0.1", gntp_port))
    sock.sendall(request)
    response = sock.recv(1024).decode()
    sock.close()

    assert "-OK" in response
    _wait_for(received, 1)
    assert received[0].title == "From elsewhere"
    assert received[0].icon_data == png


def test_gntp_resource_referenced_but_not_sent_does_not_hang(running_server):
    server, received, gntp_port, udp_port = running_server
    request = (
        b"GNTP/1.0 NOTIFY NONE\r\n"
        b"Notification-Title: NoData\r\n"
        b"Notification-Icon: x-growl-resource://missing\r\n"
        b"\r\n"
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    sock.connect(("127.0.0.1", gntp_port))
    sock.sendall(request)
    sock.shutdown(socket.SHUT_WR)  # sender is done: no resource will follow
    response = sock.recv(1024).decode()
    sock.close()

    assert "-OK" in response
    _wait_for(received, 1)
    assert received[0].icon_data is None


def test_udp_oversized_embedded_icon_falls_back_to_path(running_server, tmp_path):
    server, received, gntp_port, udp_port = running_server
    icon = tmp_path / "big.png"
    icon.write_bytes(b"\x89PNG" + b"0" * 100_000)  # base64 well over a datagram

    client = NotificationClient(host="127.0.0.1", gntp_port=gntp_port, udp_port=udp_port)
    client.send(title="Big", text="b", icon=str(icon), transport="udp")

    _wait_for(received, 1)
    assert received[0].icon == str(icon)
    assert received[0].icon_data is None
