from pathlib import Path
import json, re, hashlib
root = Path(r"D:/Projects/Python/Interview_Copilot")
report = root / "docs/reports/handbook-audit-2026-09-23"
index = report / "evidence/interview-question-index.json"
data = json.loads(index.read_text(encoding="utf-8"))
for row in data:
    row.pop("question", None)
index.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
p = report / "面经映射.md"
s = p.read_text(encoding="utf-8").replace("保存每个编号条目的原文、原始行号及候选工程映射", "保存每个编号条目的序号、原文行号链接及候选工程映射").replace("每个来源的问题全文与逐条候选映射见 JSON", "每个来源的原问题行号链接与逐条候选映射见 JSON")
p.write_text(s, encoding="utf-8")
p = report / "README.md"
s = p.read_text(encoding="utf-8").replace("backend/alembic/versions/0047*", "alembic/versions/0047_pgvector_extension.py")
p.write_text(s, encoding="utf-8")
for p in report.rglob("*.md"):
    s = p.read_text(encoding="utf-8").replace("backend/app/mcp/manager.py", "backend/app/agent_runtime/mcp/manager.py")
    p.write_text(s, encoding="utf-8")
broken = []
for p in report.rglob("*.md"):
    for href in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf-8")):
        if href.startswith(("https://", "http://", "#")):
            continue
        target = href.split("#")[0]
        if not (p.parent / target).resolve().exists():
            broken.append({"file":p.relative_to(report).as_posix(), "target":href})
files = []
for base in ["backend/app", "backend/tests", "frontend/src", "evaluation", "scripts", "alembic", ".github/workflows", "docs/architecture"]:
    for p in (root/base).rglob("*"):
        if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".json", ".md", ".yml", ".yaml", ".toml"} and "__pycache__" not in p.parts:
            files.append(p)
for name in ["pyproject.toml", "uv.lock", "docker-compose.yml", "backend/Dockerfile", "frontend/package.json", "frontend/package-lock.json"]:
    p=root/name
    if p.exists():
        files.append(p)
manifest = [{"path":p.relative_to(root).as_posix(), "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(set(files))]
(report/"evidence/workspace-file-hashes.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
print(json.dumps({"chapters":len(list((report/"chapters").glob("*.md"))),"interview_sources":len({r["source_id"] for r in data}),"numbered_entries":len(data),"hashed_files":len(manifest),"broken_links":broken},ensure_ascii=False,indent=2))
