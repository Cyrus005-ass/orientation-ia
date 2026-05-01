from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path


def _stream_output(proc: subprocess.Popen, lines: list[str]) -> None:
    for raw in iter(proc.stdout.readline, ""):
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        print(line)


def _resolve_cloudflared_cmd() -> list[str]:
    local_bin = Path(__file__).resolve().parent / "tools" / "cloudflared" / "cloudflared.exe"
    if local_bin.exists():
        return [str(local_bin)]
    return ["cloudflared"]


def main() -> None:
    uvicorn_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        cloudflared_cmd = _resolve_cloudflared_cmd()
        cloudflared_proc = subprocess.Popen(
            cloudflared_cmd + ["tunnel", "--url", "http://127.0.0.1:8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print("cloudflared introuvable. Installe Cloudflare Tunnel ou utilise le mode Wi-Fi local (python serve_mobile.py).")
        uvicorn_proc.terminate()
        return

    lines: list[str] = []
    t = threading.Thread(target=_stream_output, args=(cloudflared_proc, lines), daemon=True)
    t.start()

    public_url = None
    start = time.time()
    while time.time() - start < 60:
        text = "\n".join(lines)
        m = re.search(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com", text)
        if m:
            public_url = m.group(0)
            break
        time.sleep(1)

    if public_url:
        print("\nURL publique detectee:")
        print(public_url)
        print("Ajoute ?token=TON_TOKEN a l URL si MOBILE_DASH_TOKEN est configure.")
    else:
        print("URL publique non detectee dans les logs cloudflared.")

    try:
        cloudflared_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        cloudflared_proc.terminate()
        uvicorn_proc.terminate()


if __name__ == "__main__":
    main()