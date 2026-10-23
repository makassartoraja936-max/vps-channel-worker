#!/usr/bin/env python3
"""
Local Loopback Proxy Bridge
===========================
Solves Chromium's `net::ERR_TUNNEL_CONNECTION_FAILED` when running behind
authenticated egress proxies (such as Meta's sandbox hatch-egress-proxy:3128).

How it works:
1. Runs a lightweight local proxy server on 127.0.0.1:8889.
2. Intercepts Chromium's unauthenticated HTTP CONNECT and GET/POST requests.
3. Proactively injects the `Proxy-Authorization: Basic <token>` header and forwards
   directly to the upstream egress proxy ($HTTP_PROXY / $HTTPS_PROXY).
4. Pipes the encrypted TLS tunnel bidirectionally.
5. Chromium sees an unauthenticated, zero-friction local proxy on localhost!
"""

import asyncio
import base64
import logging
import os
import re
import socket
import sys
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ProxyBridge] %(message)s")
logger = logging.getLogger("ProxyBridge")

LOCAL_BRIDGE_HOST = "127.0.0.1"
LOCAL_BRIDGE_PORT = 8889


def parse_upstream_proxy():
    """Parses upstream proxy from environment, /proc/1/environ, or cached config."""
    raw = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
        os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or
        os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    )

    # Check /proc/1/environ if container environment not inherited
    if not raw and os.path.exists("/proc/1/environ"):
        try:
            with open("/proc/1/environ", "rb") as f:
                env_items = f.read().split(b"\x00")
            for item in env_items:
                decoded = item.decode("utf-8", errors="ignore")
                for key in ("HTTPS_PROXY=", "https_proxy=", "HTTP_PROXY=", "http_proxy="):
                    if decoded.startswith(key):
                        raw = decoded.split("=", 1)[1]
                        break
                if raw:
                    break
        except Exception:
            pass

    # Check /etc/environment
    if not raw and os.path.exists("/etc/environment"):
        try:
            with open("/etc/environment", "r", encoding="utf-8") as f:
                for line in f:
                    for key in ("HTTPS_PROXY=", "https_proxy=", "HTTP_PROXY=", "http_proxy="):
                        if line.startswith(key):
                            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                    if raw:
                        break
        except Exception:
            pass

    # Check persistent cache file
    cache_file = os.path.expanduser("~/workspace/.proxy_cache")
    if not raw and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    raw = saved
        except Exception:
            pass
    elif raw and not os.path.exists(cache_file):
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception:
            pass

    if not raw:
        return None

    if "://" not in raw:
        raw = f"http://{raw}"

    p = urlparse(raw)
    host = p.hostname or "198.19.0.1"
    port = p.port or 3128

    auth_header = None
    if p.username and p.password:
        cred = f"{p.username}:{p.password}"
        b64 = base64.b64encode(cred.encode("utf-8")).decode("ascii")
        auth_header = f"Basic {b64}"

    return {
        "host": host,
        "port": port,
        "auth": auth_header,
        "raw": f"{host}:{port}",
        "is_direct": False
    }


async def pipe(reader, writer):
    """Pipes bytes bidirectionally between reader and writer."""
    try:
        while not reader.at_eof():
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_client(client_reader, client_writer, upstream):
    """Handles an incoming request from Chromium."""
    try:
        # Read the request line and headers
        initial_data = await client_reader.readuntil(b"\r\n\r\n")
    except Exception:
        client_writer.close()
        return

    first_line = initial_data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = first_line.split()
    if len(parts) < 2:
        client_writer.close()
        return

    method, target = parts[0], parts[1]

    # If direct passthrough mode (no upstream proxy)
    if upstream.get("is_direct"):
        try:
            if ":" in target:
                thost, tport = target.split(":", 1)
                tport = int(tport)
            else:
                thost, tport = target, 80
            upstream_reader, upstream_writer = await asyncio.open_connection(thost, tport)
            if method.upper() == "CONNECT":
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                await asyncio.gather(
                    pipe(client_reader, upstream_writer),
                    pipe(upstream_reader, client_writer)
                )
            else:
                upstream_writer.write(initial_data)
                await upstream_writer.drain()
                await asyncio.gather(
                    pipe(client_reader, upstream_writer),
                    pipe(upstream_reader, client_writer)
                )
        except Exception as dir_err:
            logger.error(f"Direct connection to {target} failed: {dir_err}")
            client_writer.close()
        return

    # Connect to upstream egress proxy
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            upstream["host"], upstream["port"]
        )
    except Exception as e:
        logger.error(f"Cannot connect to upstream proxy {upstream['raw']}: {e}")
        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        await client_writer.drain()
        client_writer.close()
        return

    if method.upper() == "CONNECT":
        # HTTPS Tunneling request
        connect_req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
        if upstream["auth"]:
            connect_req += f"Proxy-Authorization: {upstream['auth']}\r\n"
        connect_req += "Proxy-Connection: Keep-Alive\r\n\r\n"

        upstream_writer.write(connect_req.encode("ascii"))
        await upstream_writer.drain()

        # Read upstream proxy response
        try:
            resp_headers = await upstream_reader.readuntil(b"\r\n\r\n")
        except Exception:
            client_writer.close()
            upstream_writer.close()
            return

        resp_first_line = resp_headers.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        if " 200 " in resp_first_line:
            # Tell Chromium the tunnel is established!
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()

            # Pipe TLS data bidirectionally
            await asyncio.gather(
                pipe(client_reader, upstream_writer),
                pipe(upstream_reader, client_writer)
            )
        else:
            logger.warning(f"Upstream rejected CONNECT to {target}: {resp_first_line}")
            client_writer.write(resp_headers)
            await client_writer.drain()
            client_writer.close()
            upstream_writer.close()

    else:
        # Plain HTTP request: inject Proxy-Authorization if present
        headers_block = initial_data
        if upstream["auth"]:
            # Insert Proxy-Authorization header
            headers_block = re.sub(
                b"\r\n\r\n",
                f"\r\nProxy-Authorization: {upstream['auth']}\r\n\r\n".encode("ascii"),
                headers_block,
                count=1
            )

        upstream_writer.write(headers_block)
        await upstream_writer.drain()

        # Pipe remaining traffic
        await asyncio.gather(
            pipe(client_reader, upstream_writer),
            pipe(upstream_reader, client_writer)
        )


async def start_bridge(port=LOCAL_BRIDGE_PORT):
    init_upstream = parse_upstream_proxy()
    if init_upstream:
        logger.info(f"Targeting upstream proxy: {init_upstream['host']}:{init_upstream['port']} (Auth: {bool(init_upstream['auth'])})")
    else:
        logger.info("No system proxy detected yet. Will parse dynamically on each request.")

    async def client_cb(r, w):
        upstream = parse_upstream_proxy()
        if not upstream:
            upstream = {"host": None, "port": None, "auth": None, "raw": "direct", "is_direct": True}
        await handle_client(r, w, upstream)

    server = await asyncio.start_server(
        client_cb,
        LOCAL_BRIDGE_HOST,
        port
    )
    logger.info(f"Local Proxy Bridge running on http://{LOCAL_BRIDGE_HOST}:{port}")
    return server


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((LOCAL_BRIDGE_HOST, port)) == 0


if __name__ == "__main__":
    if is_port_in_use(LOCAL_BRIDGE_PORT):
        print(f"Proxy bridge already running on port {LOCAL_BRIDGE_PORT}.")
        sys.exit(0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = loop.run_until_complete(start_bridge(LOCAL_BRIDGE_PORT))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()
