from scrape_market_intensive import build_market_snapshot
from train_agent import build_knowledge


def main() -> None:
    snapshot = build_market_snapshot()
    print(f"[OK] Snapshot intensif: {snapshot}")
    build_knowledge()
    print("[OK] Base de connaissance reconstruite.")


if __name__ == "__main__":
    main()
