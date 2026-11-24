"""Temporary loopback-only CONNECT proxy for public dependency downloads.

Used with an explicitly created SSH reverse forward when the remote download
network is unavailable. This is not part of the application or Docker daemon.
"""
import argparse
import asyncio
import base64
import os
import json
from urllib.parse import urlsplit, unquote

ALLOWED = ("github.com", "githubusercontent.com", "ghcr.io", "huggingface.co", "hf.co", "xethub.hf.co", "pypi.org", "pythonhosted.org", "pytorch.org", "docker.io", "docker.com", "cloudflarestorage.com")


async def handle(reader, writer):
    upstream = None
    tasks = []
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        if len(header) > 16384:
            return
        method, target, _ = header.split(b"\r\n", 1)[0].decode("ascii").split()
        host, port = target.rsplit(":", 1)
        if method != "CONNECT" or port != "443" or not any(host == root or host.endswith("." + root) for root in ALLOWED):
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            return
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if proxy:
            parsed = urlsplit(proxy)
            remote_reader, upstream = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, parsed.port or 80), 20)
            auth = ""
            if parsed.username:
                credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}"
                auth = "Proxy-Authorization: Basic " + base64.b64encode(credentials.encode()).decode() + "\r\n"
            upstream.write(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n{auth}\r\n".encode())
            await upstream.drain()
            response = await asyncio.wait_for(remote_reader.readuntil(b"\r\n\r\n"), 60)
            if response.split(b"\r\n", 1)[0].split()[1] != b"200":
                print(json.dumps({"event": "upstream_proxy_error", "host": host, "status": response.split(b"\r\n", 1)[0].decode(errors="replace")}), flush=True)
                return
        else:
            remote_reader, upstream = await asyncio.wait_for(asyncio.open_connection(host, 443), 20)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        last_activity = [asyncio.get_running_loop().time()]

        async def copy(source, destination):
            while block := await source.read(65536):
                last_activity[0] = asyncio.get_running_loop().time()
                destination.write(block)
                await destination.drain()

        async def idle_watchdog():
            while asyncio.get_running_loop().time() - last_activity[0] < 120:
                await asyncio.sleep(30)

        tasks = [asyncio.create_task(copy(reader, upstream)), asyncio.create_task(copy(remote_reader, writer)), asyncio.create_task(idle_watchdog())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
        print(json.dumps({"event": "proxy_connection_error", "error_type": type(error).__name__}), flush=True)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for stream in (writer, upstream):
            if stream:
                stream.close()
                try:
                    await stream.wait_closed()
                except OSError:
                    pass


async def main(port):
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"Dependency download proxy listening on 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18790)
    asyncio.run(main(parser.parse_args().port))
