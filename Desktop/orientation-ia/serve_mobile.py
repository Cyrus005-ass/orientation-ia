from __future__ import annotations

import socket

import uvicorn


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    host = "0.0.0.0"
    port = 8000
    ip = _local_ip()
    print(f"Dashboard mobile local: http://127.0.0.1:{port}")
    print(f"Dashboard mobile telephone (meme Wi-Fi): http://{ip}:{port}")
    uvicorn.run("api_server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
