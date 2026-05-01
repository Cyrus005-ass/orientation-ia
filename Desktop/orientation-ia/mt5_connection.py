from __future__ import annotations

import os


def initialize_mt5(mt5) -> tuple[bool, str]:
    path = (os.getenv("MT5_PATH") or "").strip()
    login_raw = (os.getenv("MT5_LOGIN") or "").strip()
    password = (os.getenv("MT5_PASSWORD") or "").strip()
    server = (os.getenv("MT5_SERVER") or "").strip()

    kwargs: dict[str, object] = {}
    if path:
        kwargs["path"] = path
    if login_raw:
        try:
            kwargs["login"] = int(login_raw)
        except ValueError:
            return False, f"MT5_LOGIN invalide: {login_raw}"
    if password:
        kwargs["password"] = password
    if server:
        kwargs["server"] = server

    try:
        ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
    except Exception as exc:
        return False, f"MetaTrader5.initialize a plante: {exc}"

    if not ok:
        last_error = None
        try:
            last_error = mt5.last_error()
        except Exception:
            pass
        return False, f"MetaTrader5.initialize a echoue: {last_error}"

    return True, ""
