from __future__ import annotations

import argparse
import json

from mt5_execution import execute_signal, list_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Execution semi-auto depuis signaux MT5")
    parser.add_argument("--list", action="store_true", help="Lister les signaux executables")
    parser.add_argument("--signal-id", type=int, help="ID du signal")
    parser.add_argument("--risk", type=float, default=1.0, help="Risque max en %")
    parser.add_argument("--live", action="store_true", help="Execution reelle")
    parser.add_argument("--confirm", type=str, default="", help="Tape EXECUTE pour confirmer en live")
    args = parser.parse_args()

    if args.list or not args.signal_id:
        cands = list_candidates()
        print(json.dumps(cands, ensure_ascii=False, indent=2))
        if not args.signal_id:
            return

    result = execute_signal(signal_id=args.signal_id, risk_pct=args.risk, live=args.live, confirm=args.confirm)
    print(json.dumps({"ok": result.ok, "mode": result.mode, "message": result.message, "payload": result.payload}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
