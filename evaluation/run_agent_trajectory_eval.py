import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.models.agent_trace import AgentRun, AgentStep  # noqa: E402


def _load_dataset(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError("dataset must be a JSON array")
    return payload


def _tool_selection_accuracy(db, dataset: list[dict], user_id: str) -> dict:
    if not dataset:
        return {"matched": 0, "total": 0, "tool_selection_accuracy": None}

    matched = 0
    total = 0
    for row in dataset:
        run_id = row.get("run_id")
        expected_tools = row.get("expected_tools", [])
        if not run_id or not isinstance(expected_tools, list):
            continue
        run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == user_id).first()
        if not run:
            continue
        used_tools = {
            step.tool_name
            for step in db.query(AgentStep).filter(AgentStep.run_id == run_id, AgentStep.action_type == "tool_call").all()
            if step.tool_name
        }
        total += 1
        if set(expected_tools).issubset(used_tools):
            matched += 1

    return {
        "matched": matched,
        "total": total,
        "tool_selection_accuracy": round(matched / total, 4) if total else None,
    }


def evaluate(db_url: str, user_id: str, session_id: str | None, dataset_path: Path | None) -> dict:
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        query = db.query(AgentRun).filter(AgentRun.user_id == user_id)
        if session_id:
            query = query.filter(AgentRun.session_id == session_id)
        runs = query.all()

        if not runs:
            return {
                "run_count": 0,
                "completion_rate": 0.0,
                "avg_steps": 0.0,
                "avg_tool_calls": 0.0,
                "invalid_tool_call_rate": 0.0,
                "avg_latency_ms": 0.0,
                "tool_selection_accuracy": None,
            }

        run_ids = [run.id for run in runs]
        all_steps = db.query(AgentStep).filter(AgentStep.run_id.in_(run_ids)).all()
        tool_steps = [step for step in all_steps if step.action_type == "tool_call"]
        invalid_tool_steps = [step for step in tool_steps if step.is_error]
        completed_runs = [run for run in runs if run.status == "completed"]

        report = {
            "run_count": len(runs),
            "completion_rate": round(len(completed_runs) / len(runs), 4),
            "avg_steps": round(sum(run.steps_used for run in runs) / len(runs), 4),
            "avg_tool_calls": round(sum(run.tool_calls for run in runs) / len(runs), 4),
            "invalid_tool_call_rate": round(len(invalid_tool_steps) / len(tool_steps), 4) if tool_steps else 0.0,
            "avg_latency_ms": round(sum(run.total_latency_ms for run in runs) / len(runs), 2),
            "tool_selection_accuracy": None,
        }

        if dataset_path:
            dataset = _load_dataset(dataset_path)
            acc = _tool_selection_accuracy(db, dataset, user_id=user_id)
            report.update(acc)

        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Evaluate trajectory quality of agent runs")
    parser.add_argument("--user-id", required=True, help="Target user id")
    parser.add_argument("--session-id", default=None, help="Optional session filter")
    parser.add_argument("--db-url", default=settings.DATABASE_URL, help="Database URL")
    parser.add_argument(
        "--dataset",
        default=None,
        help="Optional JSON file: [{'run_id': '...', 'expected_tools': ['search_jobs']}]",
    )
    parser.add_argument("--output", default=None, help="Optional path to save report JSON")
    args = parser.parse_args()

    report = evaluate(
        db_url=args.db_url,
        user_id=args.user_id,
        session_id=args.session_id,
        dataset_path=Path(args.dataset) if args.dataset else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
