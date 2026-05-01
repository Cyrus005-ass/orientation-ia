from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader

INPUT_DIR = Path("knowledge")
OUTPUT_FILE = INPUT_DIR / "knowledge_base.txt"
DEO_INDEX_FILE = INPUT_DIR / "live" / "deo_curriculum_index.txt"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_title(name: str) -> str:
    stem = Path(name).stem
    stem = unicodedata.normalize("NFKD", stem)
    stem = "".join(ch for ch in stem if not unicodedata.combining(ch))
    stem = stem.encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem)
    return stem.strip()


def _normalize(value: str) -> str:
    v = unicodedata.normalize("NFKD", value)
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    return v.lower()


def _is_deo_path(path: Path) -> bool:
    return "deo" in _normalize(str(path.parent))


def _lesson_kind(title: str) -> str:
    t = _normalize(title)
    if "theorie" in t:
        return "theorie"
    if "pratique" in t:
        return "pratique"
    if "breakdown" in t:
        return "breakdown"
    return "cours"


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks = []
    for i, page in enumerate(reader.pages, start=1):
        t = page.extract_text() or ""
        t = _clean_text(t)
        if t:
            chunks.append(f"[{path.name} | page {i}] {t}")
    return "\n".join(chunks)


def read_text_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="ignore")
    content = _clean_text(content)
    return f"[{path.name}] {content}" if content else ""


def read_video_catalog(path: Path) -> tuple[str, str, str]:
    rel = path.relative_to(INPUT_DIR)
    module = rel.parts[1] if len(rel.parts) > 2 else "general"
    title = _clean_title(path.name)
    kind = _lesson_kind(title)
    line = f"[deo_video | module {module} | {kind}] {title}"
    return line, module, kind


def _write_deo_index(lines: list[str]) -> None:
    DEO_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEO_INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")


def _manager_playbook(strategy_steps: str, module_stats: dict[str, dict[str, int]]) -> str:
    module_lines = []
    for module in sorted(module_stats.keys(), key=lambda x: (len(x), x)):
        st = module_stats[module]
        module_lines.append(
            f"- Module {module}: total={st.get('total', 0)} theorie={st.get('theorie', 0)} pratique={st.get('pratique', 0)} breakdown={st.get('breakdown', 0)}"
        )

    modules_text = "\n".join(module_lines) if module_lines else "- Aucun module video detecte"

    return (
        "[MANAGER_PRO_PLAYBOOK]\n"
        "Role: manager trading tout-en-un (analyste + coach + journal + execution).\n"
        "\n"
        "Cadre strict:\n"
        "- Interdiction indicateurs techniques.\n"
        "- Autorise: structure, zones, price action, BOS/CHOCH, fake breakout, liquidite.\n"
        "- Conditions de validation trade:\n"
        "  * Zone D1/H4\n"
        "  * Structure H4 claire\n"
        "  * Confirmation H1/M15\n"
        "  * RR >= 1:2.5\n"
        "  * SL logique\n"
        "  * Spread correct\n"
        "- Sinon: WAIT + NE TRADE PAS.\n"
        "\n"
        "Workflow execution:\n"
        "- Manual: conseil uniquement\n"
        "- Semi: preview puis validation\n"
        "- Auto: execution seulement si active explicitement\n"
        "\n"
        "Format attendu:\n"
        "SYMBOL, Decision, Contexte, Entree, SL, TP, RR, Lot, Rappel discipline.\n"
        "\n"
        "Etapes strategie utilisateur:\n"
        f"{strategy_steps or 'Aucune etape personnalisee fournie.'}\n"
        "\n"
        "Resume curriculum video detecte:\n"
        f"{modules_text}\n"
    )


def build_knowledge() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    deo_lines = ["DEO CURRICULUM INDEX"]
    module_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "theorie": 0, "pratique": 0, "breakdown": 0, "cours": 0})

    pdf_count = 0
    text_count = 0
    video_count = 0

    strategy_steps_raw = ""
    strategy_file = INPUT_DIR / "strategy_steps.txt"
    if strategy_file.exists():
        strategy_steps_raw = strategy_file.read_text(encoding="utf-8", errors="ignore").strip()

    for path in sorted(INPUT_DIR.glob("**/*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            extracted = read_pdf(path)
            if extracted:
                parts.append(extracted)
                pdf_count += 1
        elif suffix in {".txt", ".md"} and path.name != OUTPUT_FILE.name:
            extracted = read_text_file(path)
            if extracted:
                parts.append(extracted)
                text_count += 1
        elif suffix in VIDEO_EXTS and _is_deo_path(path):
            entry, module, kind = read_video_catalog(path)
            parts.append(entry)
            deo_lines.append(entry)
            module_stats[module]["total"] += 1
            module_stats[module][kind] += 1
            video_count += 1

    _write_deo_index(deo_lines)

    playbook = _manager_playbook(strategy_steps_raw, module_stats)
    sources_summary = (
        "[KNOWLEDGE_SOURCES]\n"
        f"pdf_files={pdf_count}\n"
        f"text_files={text_count}\n"
        f"video_lessons_indexed={video_count}\n"
    )
    priority_parts = [playbook, sources_summary]

    if not parts:
        OUTPUT_FILE.write_text(
            "Aucune connaissance extraite. Ajoute des PDF/TXT/MD/MP4 dans knowledge puis relance.",
            encoding="utf-8",
        )
        print("Knowledge base vide: ajoute des documents dans knowledge/.")
        return

    OUTPUT_FILE.write_text("\n\n".join(priority_parts + parts), encoding="utf-8")
    print(f"Knowledge base generee: {OUTPUT_FILE}")
    print(f"Index deo genere: {DEO_INDEX_FILE}")
    print(f"Sources: pdf={pdf_count} text={text_count} videos={video_count}")


if __name__ == "__main__":
    build_knowledge()