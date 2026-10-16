"""Opt-in acceptance against an isolated, real HTTP/PostgreSQL/Celery stack.

No application dependencies or providers are replaced. The operator supplies
test-only credentials; never point this campaign at an account with real data.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import time

import httpx
import pytest


@pytest.fixture(scope="module")
def client(acceptance_login):
    origin = os.environ.get("IC_ACCEPTANCE_BASE_URL")
    if not origin:
        pytest.skip("explicit isolated acceptance stack required")
    with httpx.Client(base_url=origin, timeout=90) as value:
        original = acceptance_login(value)
        value.headers["Authorization"] = "Bearer " + original["access_token"]
        yield value


def request(client, method, path, expected=(200, 201), **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    assert response.status_code in expected, (
        f"{method} {path}: {response.status_code} {response.text[:1000]}"
    )
    return response.json() if response.content else None


def test_mock_answer_replay_resume_and_review(client):
    if os.environ.get("IC_ACCEPTANCE_LIVE_MODELS") != "1":
        pytest.skip("finite real-model acceptance opt-in required")
    preparation = {
        "purpose": "focused_practice",
        "focus": "Python 事务与请求幂等设计",
        "input_mode": "text",
        "target_question_count": 15,
    }
    started = request(client, "POST", "/mock-interviews/start", json=preparation)
    record_id = started["record_id"]
    root = f"/mock-interviews/{record_id}"
    finished = False
    try:
        request(
            client, "POST", "/mock-interviews/start", expected=(409,), json=preparation
        )
        active = request(client, "GET", "/mock-interviews/in-progress")
        assert active["record_id"] == record_id
        answer = {
            "request_id": str(uuid.uuid4()),
            "question_message_id": started["message"]["id"],
            "answer_text": "我会把请求编号设为唯一键，在事务中保存业务变更和结果收据。重复请求先读取收据；事务未完成时不重复调用外部服务。",
        }
        next_question = request(client, "POST", root + "/answer", json=answer)
        assert request(client, "POST", root + "/answer", json=answer) == next_question
        receipt = request(
            client, "GET", root + "/answer-receipts/" + answer["request_id"]
        )
        assert receipt["status"] == "completed" and receipt["response"] == next_question
        request(
            client,
            "POST",
            root + "/answer",
            expected=(409,),
            json={**answer, "answer_text": "改变的内容"},
        )
        request(
            client,
            "POST",
            root + "/answer",
            expected=(409,),
            json={**answer, "request_id": str(uuid.uuid4())},
        )
        messages = request(client, "GET", root + "/live-state")["messages"]
        assert [m["speaker"] for m in messages] == [
            "interviewer",
            "candidate",
            "interviewer",
        ]
        assert messages[1]["text"] == answer["answer_text"]
        request(client, "POST", root + "/finish")
        finished = True
        deadline = time.monotonic() + 180
        while True:
            record = request(client, "GET", f"/interview-records/{record_id}")
            if record["status"] in (
                "completed",
                "review_ready",
                "review_failed",
                "failed",
            ):
                break
            assert time.monotonic() < deadline, record["status"]
            time.sleep(2)
        assert record["status"] in ("completed", "review_ready"), record.get(
            "error_message"
        )
        assert (
            len(record["qa"]) == 1
            and record["qa"][0]["answer"] == answer["answer_text"]
        )
        assert not request(client, "GET", "/mock-interviews/in-progress")[
            "has_in_progress"
        ]
    finally:
        if not finished:
            request(client, "DELETE", root)


def test_authenticated_product_projections(client):
    schema_path = os.environ.get("IC_ACCEPTANCE_OPENAPI")
    schema = (
        json.loads(Path(schema_path).read_text(encoding="utf-8"))
        if schema_path
        else client.get("/openapi.json").json()
    )
    tested = []
    # No automatic calls to callbacks, streams, downloads or provider actions.
    prefixes = (
        "/workspace",
        "/career-profile",
        "/career-process",
        "/career-workspace",
        "/career-insights",
        "/career/activity",
        "/artifacts",
        "/resumes",
        "/knowledge/documents",
        "/chat/sessions",
        "/persistent-tasks",
        "/personalization",
        "/usage",
        "/models/catalog",
        "/models/runtime",
        "/capabilities/skills",
        "/capabilities/mcp",
    )
    for path, methods in schema["paths"].items():
        operation = methods.get("get")
        relative = path.removeprefix("/api/v1")
        if not operation or "{" in path or not relative.startswith(prefixes):
            continue
        if any(p.get("required") for p in operation.get("parameters", [])):
            continue
        request(client, "GET", relative)
        tested.append(relative)
    assert len(tested) >= 10, tested


def test_workspace_document_submission_archive_and_receipt_closure(client):
    key = "workspace-release-" + uuid.uuid4().hex
    base = "/career-workspace"
    job = request(
        client,
        "POST",
        base + "/jobs",
        json={
            "operation_key": key,
            "company_name": "Release Workspace Company",
            "job_title": "Python Engineer",
        },
    )
    document = request(
        client,
        "POST",
        base + "/documents",
        json={
            "operation_key": key + "-doc",
            "title": "Release resume",
            "kind": "resume",
            "opportunity_id": job["id"],
            "data": {"name": "Synthetic candidate", "summary": "Original resume"},
        },
    )
    path = base + f"/documents/{document['artifact_id']}"
    saved = request(
        client,
        "PUT",
        path + "/draft",
        json={
            "expected_revision": document["revision"],
            "base_version_id": document["current_version_id"],
            "operation_key": key + "-save",
            "title": "Release resume",
            "data": {"name": "Synthetic candidate", "summary": "Submitted resume"},
        },
    )
    published = request(
        client,
        "POST",
        path + "/publish",
        json={
            "expected_revision": saved["revision"],
            "operation_key": key + "-publish",
        },
    )
    stage = {
        "expected_version": job["version"],
        "operation_key": key + "-applied",
        "stage": "applied",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "version_ids": [published["current_version_id"]],
    }
    job = request(client, "POST", base + f"/jobs/{job['id']}/stage", json=stage)
    replay = request(client, "POST", base + f"/jobs/{job['id']}/stage", json=stage)
    assert replay["version"] == job["version"] and len(replay["submissions"]) == 1
    assert replay["submissions"][0]["version"]["id"] == published["current_version_id"]
    before = request(client, "GET", "/workspace")["active_opportunities"]
    request(
        client,
        "PATCH",
        base + f"/jobs/{job['id']}",
        json={
            "expected_version": job["version"],
            "company_name": job["company_name"],
            "job_title": job["job_title"],
            "hidden": True,
        },
    )
    assert request(client, "GET", "/workspace")["active_opportunities"] == before - 1
    assert (
        request(
            client, "GET", base + "/jobs", params={"q": "Release Workspace Company"}
        )["total"]
        == 0
    )
    receipt = "/career/interview-invitations/submissions"
    assert (
        request(client, "GET", receipt + "/receipt", params={"idempotency_key": key})[
            "status"
        ]
        == "not_received"
    )
    assert (
        request(client, "POST", receipt + "/cancel", json={"idempotency_key": key})[
            "status"
        ]
        == "cancelled"
    )
    request(
        client,
        "POST",
        receipt + "/resume",
        json={"idempotency_key": key},
        expected=(409,),
    )


def test_artifact_immutable_versions_and_explicit_archive(client):
    key = "release-" + uuid.uuid4().hex
    body = {
        "operation_key": key,
        "artifact_kind": "cover_letter",
        "version": {
            "title": "Synthetic acceptance document",
            "content_text": "Original evidence",
            "content_format": "markdown",
        },
    }
    original = request(client, "POST", "/artifacts", json=body)
    repeated = request(client, "POST", "/artifacts", json=body)
    assert original["id"] == repeated["id"]
    artifact_id = original["id"]
    updated = request(
        client,
        "POST",
        f"/artifacts/{artifact_id}/versions",
        json={
            "operation_key": key + "-edit",
            "version": {"title": "Revised", "content_text": "Revised evidence"},
        },
    )
    assert updated != original
    versions = request(client, "GET", f"/artifacts/{artifact_id}/versions")
    assert len(versions) == 2
    assert {v["content_text"] for v in versions} == {
        "Original evidence",
        "Revised evidence",
    }
    archived = request(client, "POST", f"/artifacts/{artifact_id}/archive")
    assert archived["archived_at"] is not None
    assert request(client, "GET", f"/artifacts/{artifact_id}")["id"] == artifact_id
    assert len(request(client, "GET", f"/artifacts/{artifact_id}/versions")) == 2


def test_skill_creation_edit_and_removal(client):
    content = "---\nname: release-contract\ndescription: Synthetic acceptance skill\n---\nUse only supplied evidence."
    created = request(
        client,
        "POST",
        "/capabilities/skills",
        json={"content": content, "enabled": True},
    )
    skill_id = created["id"]
    try:
        updated = request(
            client, "PATCH", f"/capabilities/skills/{skill_id}", json={"enabled": False}
        )
        assert updated["enabled"] is False
        listed = request(client, "GET", "/capabilities/skills")["skills"]
        assert any(row["id"] == skill_id for row in listed)
    finally:
        request(client, "DELETE", f"/capabilities/skills/{skill_id}", expected=(204,))


def test_session_identity_mode_and_history(client):
    key = str(uuid.uuid4())
    body = {
        "type": "general",
        "title": "Acceptance conversation",
        "client_request_id": key,
    }
    created = request(client, "POST", "/chat/sessions", json=body)
    assert (
        request(client, "POST", "/chat/sessions", json=body)["session_id"]
        == created["session_id"]
    )
    session_id = created["session_id"]
    request(
        client,
        "PATCH",
        f"/chat/sessions/{session_id}/title",
        json={"title": "Renamed acceptance conversation"},
    )
    items = request(client, "GET", "/chat/sessions")
    assert any(
        row["session_id"] == session_id
        and row["title"] == "Renamed acceptance conversation"
        for row in items
    )
    mode = request(client, "GET", f"/chat/sessions/{session_id}/execution-mode")
    assert mode["execution_mode"] == "standard"
    request(client, "GET", "/chat/transcript", params={"session_id": session_id})


def test_profile_edit_preserves_version_conflicts(client):
    before = request(client, "GET", "/career-profile")
    body = {
        "expected_profile_version": before["version"],
        "fact": {"kind": "skill", "name": "Acceptance SQL"},
        "confirmation": {"kind": "user_edit"},
    }
    after = request(client, "POST", "/career-profile/facts", json=body)
    assert after["version"] > before["version"]
    assert any(
        f["value"]["name"] == "Acceptance SQL"
        for f in after["personal_facts"]
        if f["value"]["kind"] == "skill"
    )
    request(client, "POST", "/career-profile/facts", json=body, expected=(409,))


def test_opportunity_events_and_action_completion(client):
    key = "acceptance-" + uuid.uuid4().hex
    body = {
        "company_name": "Synthetic Company",
        "job_title": "Backend Engineer",
        "entry_reason": "explicit_tracking",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source_kind": "user_assertion",
        "source_identity": key,
        "source_description": "Synthetic acceptance record",
        "idempotency_key": key,
    }
    opportunity = request(client, "POST", "/career-process/opportunities", json=body)
    assert (
        request(client, "POST", "/career-process/opportunities", json=body)["id"]
        == opportunity["id"]
    )
    event = request(
        client,
        "POST",
        f"/career-process/opportunities/{opportunity['id']}/events",
        json={
            "kind": "application_submitted",
            "occurred_at": body["occurred_at"],
            "source_kind": "user_assertion",
            "source_identity": key + "-submitted",
            "description": "Synthetic manual submission",
        },
    )
    assert event["kind"] == "application_submitted"
    action = request(
        client,
        "POST",
        "/career-process/next-actions",
        json={
            "content": "Prepare a synthetic interview answer",
            "status": "planned",
            "time_kind": "flexible",
            "source_kind": "user_request",
            "source_identity": key,
            "job_opportunity_id": opportunity["id"],
        },
    )
    completed = request(
        client,
        "POST",
        f"/career-process/next-actions/{action['id']}/complete",
        json={"source_kind": "user_assertion", "source_identity": key + "-done"},
    )
    assert completed["status"] == "done"
    offer_text = "Synthetic offer: Backend Engineer, CNY 20000 monthly gross."
    upload = request(
        client,
        "POST",
        "/file-assets/upload-url",
        json={
            "purpose": "knowledge_document",
            "filename": "synthetic-offer.txt",
            "content_type": "text/plain",
            "size_bytes": len(offer_text.encode()),
        },
    )
    assert client.put(
        upload["upload_url"],
        content=offer_text.encode(),
        headers={"Content-Type": "text/plain"},
    ).is_success
    request(client, "POST", f"/file-assets/{upload['file_asset_id']}/confirm")
    offer_body = {
        "operation_key": key + "-offer",
        "terms": {
            "formality": "written",
            "original_text": offer_text,
            "base_salary_amount": "20000",
            "currency": "CNY",
            "pay_period": "monthly",
            "tax_basis": "gross",
        },
        "source": {
            "kind": "file_asset",
            "identity": upload["file_asset_id"],
            "observed_at": body["occurred_at"],
        },
    }
    path = f"/career-process/opportunities/{opportunity['id']}/offer"
    offer = request(client, "POST", path, json=offer_body)
    repeated = request(client, "POST", path, json=offer_body)
    assert repeated["offer"]["id"] == offer["offer"]["id"]
    assert request(client, "GET", path)["current_token"] == offer["current_token"]
    offer_id = offer["offer"]["id"]
    comparison = request(
        client,
        "POST",
        "/career-insights/offers/compare",
        json={
            "offer_ids": [offer_id],
            "base_currency": "CNY",
            "save_artifact": True,
            "operation_key": key + "-comparison",
        },
    )
    assert Decimal(comparison["items"][0]["annual_base_in_base_currency"]) == Decimal(
        "240000"
    )
    assert comparison["items"][0]["estimated_after_tax_cash"] is None
    assert comparison["artifact_id"]
    draft_body = {
        "objective": "讨论远程办公安排",
        "save_artifact": True,
        "operation_key": key + "-negotiation",
    }
    draft_path = f"/career-insights/offers/{offer_id}/negotiation-draft"
    draft = request(client, "POST", draft_path, json=draft_body)
    assert draft["send_status"] == "not_sent" and draft["artifact_id"]
    assert "讨论远程办公安排" in draft["draft_markdown"]
    assert (
        request(client, "POST", draft_path, json=draft_body)["artifact_id"]
        == draft["artifact_id"]
    )
    assert request(client, "GET", path)["current_token"] == offer["current_token"]
    for artifact_id in (draft["artifact_id"], comparison["artifact_id"]):
        request(client, "POST", f"/artifacts/{artifact_id}/archive")


def test_real_file_upload_confirmation_and_range_download(client):
    content = b"Acceptance evidence: PostgreSQL stores canonical retrieval entries."
    upload = request(
        client,
        "POST",
        "/file-assets/upload-url",
        json={
            "purpose": "knowledge_document",
            "filename": "acceptance.txt",
            "content_type": "text/plain",
            "size_bytes": len(content),
        },
    )
    response = client.put(
        upload["upload_url"], content=content, headers={"Content-Type": "text/plain"}
    )
    assert response.is_success, response.text
    file_id = upload["file_asset_id"]
    request(client, "POST", f"/file-assets/{file_id}/confirm")
    response = client.get(
        f"/api/v1/file-assets/{file_id}/download", follow_redirects=True
    )
    assert response.status_code == 200 and response.content == content
    response = client.get(
        f"/api/v1/file-assets/{file_id}/download",
        headers={"Range": "bytes=0-9"},
        follow_redirects=True,
    )
    assert response.status_code == 206 and response.content == content[:10]
    session = request(
        client,
        "POST",
        "/chat/sessions",
        json={
            "type": "general",
            "title": "Disposable attachment acceptance",
            "client_request_id": str(uuid.uuid4()),
        },
    )["session_id"]
    try:
        draft = request(
            client,
            "POST",
            f"/chat/{session}/attachment-drafts",
            json={"file_asset_id": file_id},
        )
        path = f"/chat/{session}/attachment-drafts/{draft['draft_id']}"
        deadline = time.monotonic() + 120
        while draft["status"] == "processing":
            assert time.monotonic() < deadline, draft
            time.sleep(1)
            draft = request(client, "GET", path)
        assert draft["status"] == "ready", draft.get("error_message")
        assert request(client, "DELETE", path)["status"] == "removed"
    finally:
        impact = request(client, "GET", f"/chat/sessions/{session}/deletion-impact")
        request(
            client,
            "DELETE",
            f"/chat/sessions/{session}",
            json={
                "confirmation_token": impact["confirmation_token"],
                "confirm_conversation_id": session,
            },
        )


def test_manual_invitation_confirmation_is_replayable_and_owns_a_record(client):
    key = "invitation-" + uuid.uuid4().hex
    body = {
        "idempotency_key": key,
        "actor_kind": "user",
        "asserted_at": datetime.now(timezone.utc).isoformat(),
        "confirmation_basis": {
            "kind": "explicit_user_assertion",
            "source": {"kind": "manual", "identity": key},
        },
        "facts": {
            "company_name": "Synthetic Invitation Company",
            "job_title": "Python Engineer",
            "scheduled_start_at": "2030-11-01T02:00:00Z",
            "original_time_text": "2030年11月1日10点",
            "source_timezone": "Asia/Shanghai",
        },
        "opportunity": {"kind": "create_new"},
    }
    path = "/career/interview-invitations"
    created = request(client, "POST", path + "/confirm", json=body)
    replayed = request(client, "POST", path + "/confirm", json=body)
    assert replayed["replayed"] is True
    assert replayed["interview"]["id"] == created["interview"]["id"]
    assert created["verification"]["conclusion"] == "verified"
    record = request(client, "GET", f"/interview-records/{created['interview']['id']}")
    assert record["job_opportunity_id"] == created["opportunity"]["id"]
    request(
        client,
        "GET",
        path + f"/interviews/{created['interview']['id']}/handoff",
        expected=(404,),
    )
    changed = {**body, "facts": {**body["facts"], "job_title": "Conflicting title"}}
    request(client, "POST", path + "/confirm", json=changed, expected=(409,))


def test_refresh_rotation_and_logout_reject_replay(client, acceptance_login):
    with httpx.Client(base_url=str(client.base_url), timeout=30) as auth:
        original = acceptance_login(auth)
        if not original["refresh_token"]:
            # Independent local unlock has no cloud refresh permission.
            request(
                auth,
                "POST",
                "/auth/refresh",
                json={"refresh_token": "local-unlock-is-not-refreshable"},
                expected=(409,),
            )
            auth.headers["Authorization"] = "Bearer " + original["access_token"]
            request(auth, "GET", "/auth/me")
            request(auth, "POST", "/auth/logout", json={"refresh_token": ""})
            request(auth, "GET", "/auth/me", expected=(401,))
            unlocked = acceptance_login(auth)
            auth.headers["Authorization"] = "Bearer " + unlocked["access_token"]
            request(auth, "GET", "/auth/me")
            return
        rotated = request(
            auth,
            "POST",
            "/auth/refresh",
            json={"refresh_token": original["refresh_token"]},
        )
        request(
            auth,
            "POST",
            "/auth/refresh",
            json={"refresh_token": original["refresh_token"]},
            expected=(401,),
        )
        auth.headers["Authorization"] = "Bearer " + rotated["access_token"]
        request(auth, "GET", "/auth/me")
        request(
            auth,
            "POST",
            "/auth/logout",
            json={"refresh_token": rotated["refresh_token"]},
        )
        request(auth, "GET", "/auth/me", expected=(401,))
        request(
            auth,
            "POST",
            "/auth/refresh",
            json={"refresh_token": rotated["refresh_token"]},
            expected=(401,),
        )


def test_live_resume_parses_typed_goal_and_preserves_source(client):
    if os.environ.get("IC_ACCEPTANCE_LIVE_MODELS") != "1":
        pytest.skip("finite real model usage requires explicit opt-in")
    text = (
        "测试候选人\n求职目标：Python 后端开发\n专业技能\n"
        "熟悉 Python、FastAPI、PostgreSQL。\n项目经历\n"
        "文档检索助手：编写上传接口，使用 PostgreSQL 保存元数据，使用 Redis 管理后台任务。\n"
        f"验收资料编号：{uuid.uuid4().hex}"
    )
    resume = request(
        client,
        "POST",
        "/resumes",
        json={
            "operation_key": "live-" + uuid.uuid4().hex,
            "title": "Live schema regression",
            "raw_text_snapshot": text,
            "make_default": False,
        },
    )
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            current = next(
                r for r in request(client, "GET", "/resumes") if r["id"] == resume["id"]
            )
            if current["parse_status"] in {"ready", "failed"}:
                break
            time.sleep(2)
        assert current["parse_status"] == "ready", current["parse_error"]
        sections = request(client, "GET", f"/resumes/{resume['id']}/sections")
        assert sections["artifact_version_id"] == resume["current_version_id"]
        assert (
            "".join(text[s["start"] : s["end"]] for s in sections["sections"]) == text
        )
        drafts = request(client, "GET", "/career-profile/drafts")
        draft = next(
            d for d in drafts if d["id"] == current["pending_profile_draft_id"]
        )
        assert draft["proposed_facts"] and draft["proposed_directions"]
        goal = draft["proposed_directions"][0]["direction"]["criteria"]
        assert isinstance(goal["seniority"], list)
        assert goal["salary_currency"] is None
    finally:
        request(client, "DELETE", f"/resumes/{resume['id']}")


def test_preferences_and_memory_controls_roundtrip_with_conflicts(client):
    path = "/personalization/copilot-preference"
    original = request(client, "GET", path)
    changed = request(
        client,
        "PUT",
        path,
        json={
            "expected_version": original["version"],
            "instructions": [
                "  Explain assumptions clearly.  ",
                "Explain assumptions clearly.",
            ],
        },
    )
    try:
        assert changed["instructions"] == ["Explain assumptions clearly."]
        request(
            client,
            "PUT",
            path,
            expected=(409,),
            json={
                "expected_version": original["version"],
                "instructions": ["stale edit"],
            },
        )
        assert request(client, "GET", path)["instructions"] == changed["instructions"]
    finally:
        request(
            client,
            "PUT",
            path,
            json={
                "expected_version": changed["version"],
                "instructions": original["instructions"],
            },
        )
    path = "/personalization/memory-settings"
    original = request(client, "GET", path)
    changed = request(
        client,
        "PUT",
        path,
        json={
            "expected_version": original["version"],
            "recall_enabled": False,
            "contribution_enabled": False,
        },
    )
    try:
        assert not changed["recall_enabled"] and not changed["contribution_enabled"]
        assert request(client, "GET", path)["version"] == changed["version"]
        request(
            client,
            "PUT",
            path,
            expected=(409,),
            json={
                "expected_version": original["version"],
                "recall_enabled": True,
                "contribution_enabled": False,
            },
        )
    finally:
        request(
            client,
            "PUT",
            path,
            json={
                "expected_version": changed["version"],
                "recall_enabled": original["recall_enabled"],
                "contribution_enabled": original["contribution_enabled"],
            },
        )


def test_conversation_guidance_controls_and_deletion_receipt(client):
    if os.environ.get("IC_ACCEPTANCE_LIVE_MODELS") != "1":
        pytest.skip("finite real chat turn requires explicit opt-in")
    session = request(
        client,
        "POST",
        "/chat/sessions",
        json={
            "type": "general",
            "title": "Disposable scenario acceptance",
            "client_request_id": str(uuid.uuid4()),
        },
    )["session_id"]
    guidance = f"/personalization/conversations/{session}/guidance"
    before = request(client, "GET", guidance)
    message = "本次对话请一次只问一个问题。现在只回复 OK。"
    body = {"submission_id": str(uuid.uuid4()), "message": message, "mode": "chat"}
    turn = request(
        client, "POST", f"/chat/{session}/turns", json=body, expected=(200, 202)
    )
    assert (
        request(
            client, "POST", f"/chat/{session}/turns", json=body, expected=(200, 202)
        )["turn_id"]
        == turn["turn_id"]
    )
    stream = client.get(
        f"/api/v1/chat/{session}/turns/{turn['turn_id']}/events", timeout=120
    )
    assert stream.status_code == 200 and "data:" in stream.text
    transcript = request(
        client, "GET", "/chat/transcript", params={"session_id": session}
    )
    messages = transcript["messages"]
    user_message = next(item for item in messages if item["role"] == "User")
    assert len([item for item in messages if item["role"] == "User"]) == 1
    assert any(item["role"] == "Agent" for item in messages), stream.text[-2000:]
    updated = request(
        client,
        "PUT",
        guidance,
        json={
            "expected_version": before["version"],
            "guidance": "  Ask one question at a time.  ",
            "source_message_id": user_message["id"],
        },
    )
    assert updated["guidance"] == "Ask one question at a time."
    request(
        client,
        "PUT",
        guidance,
        expected=(409,),
        json={
            "expected_version": before["version"],
            "guidance": "stale",
        },
    )
    control = f"/personalization/conversations/{session}/memory-controls"
    before = request(client, "GET", control)
    updated = request(
        client,
        "PUT",
        control,
        json={
            "expected_version": before["version"],
            "recall_override": False,
            "contribution_override": False,
        },
    )
    assert not updated["effective_recall_enabled"]
    assert not updated["effective_contribution_enabled"]
    # A missing/foreign conversation must never acquire a guidance object.
    request(
        client,
        "GET",
        "/personalization/conversations/missing-session/guidance",
        expected=(404,),
    )
    impact = request(client, "GET", f"/chat/sessions/{session}/deletion-impact")
    assert impact["confirmation_token"]
    request(
        client,
        "DELETE",
        f"/chat/sessions/{session}",
        json={
            "confirmation_token": impact["confirmation_token"],
            "confirm_conversation_id": session,
        },
    )
    request(client, "GET", guidance, expected=(404,))


def test_persistent_task_edit_pause_resume_and_confirmed_delete(client):
    key = "scenario-" + uuid.uuid4().hex
    task = request(
        client,
        "POST",
        "/persistent-tasks",
        json={
            "title": "Disposable scheduled acceptance",
            "instruction": "Reply with OK only.",
            "trigger": {
                "kind": "scheduled",
                "schedule": "0 0 1 1 *",
                "timezone": "UTC",
            },
            "read_scope": [],
            "action_scope": [],
            "allowed_tool_names": [],
            "user_request_identity": key,
            "idempotency_key": key,
        },
    )
    path = f"/persistent-tasks/{task['id']}"
    stale_version = task["version"]
    task = request(
        client,
        "PATCH",
        path,
        json={
            "expected_version": stale_version,
            "title": "Updated scheduled acceptance",
            "user_request_identity": key + "-edit",
        },
    )
    request(
        client,
        "PATCH",
        path,
        expected=(409,),
        json={
            "expected_version": stale_version,
            "title": "stale",
            "user_request_identity": key + "-stale",
        },
    )
    for state, operation in (
        ("paused", "pause"),
        ("active", "resume"),
        ("paused", "pause"),
    ):
        task = request(
            client,
            "POST",
            path + "/" + operation,
            json={
                "expected_version": task["version"],
                "state": state,
                "user_request_identity": key + "-" + operation + str(task["version"]),
            },
        )
        assert task["state"] == state
    impact = request(client, "GET", path + "/deletion-impact")
    body = {
        "expected_version": task["version"],
        "user_request_identity": key + "-delete",
        "confirm_task_id": task["id"],
        "confirmation_token": impact["confirmation_token"],
    }
    request(
        client,
        "DELETE",
        path,
        json={**body, "confirmation_token": "0" * 64},
        expected=(409,),
    )
    request(client, "DELETE", path, json=body, expected=(200, 204))
    request(client, "GET", path, expected=(404,))


def test_opportunity_merge_retraction_and_event_correction(client):
    key = "merge-scenario-" + uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    opportunities = [
        request(
            client,
            "POST",
            "/career-process/opportunities",
            json={
                "company_name": "Merge fixture " + key,
                "job_title": "Backend Engineer",
                "entry_reason": "explicit_tracking",
                "occurred_at": now,
                "source_kind": "user_assertion",
                "source_identity": key + str(index),
                "source_description": "Duplicate listing acceptance",
                "idempotency_key": key + str(index),
            },
        )
        for index in range(2)
    ]
    canonical, duplicate = [item["id"] for item in opportunities]
    body = {
        "duplicate_opportunity_id": duplicate,
        "canonical_opportunity_id": canonical,
        "operation_key": key,
        "reason": "Same synthetic job listing",
    }
    merged = request(client, "POST", "/career-process/opportunity-merges", json=body)
    assert merged["status"] == "active"
    assert (
        request(client, "POST", "/career-process/opportunity-merges", json=body)["id"]
        == merged["id"]
    )
    retracted = request(
        client,
        "POST",
        f"/career-process/opportunity-merges/{merged['id']}/retract",
        json={
            "expected_version": merged["version"],
            "operation_key": key + "-retract",
            "reason": "Acceptance restores the independent listings",
        },
    )
    assert (
        retracted["status"] == "retracted" and retracted["version"] > merged["version"]
    )
    event_path = f"/career-process/opportunities/{canonical}/events"
    event = request(
        client,
        "POST",
        event_path,
        json={
            "kind": "application_submitted",
            "occurred_at": now,
            "source_kind": "user_assertion",
            "source_identity": key + "-event",
            "description": "Acceptance event",
        },
    )
    request(
        client,
        "POST",
        event_path + f"/{event['id']}/corrections",
        json={
            "replacement_kind": "preparation_started",
            "occurred_at": now,
            "source_kind": "user_assertion",
            "source_identity": key + "-correction",
            "description": "Preparing, not yet submitted",
        },
    )
    history = request(client, "GET", event_path)
    assert any(item["corrects_event_id"] == event["id"] for item in history)
    assert any(item["kind"] == "preparation_started" for item in history)


def test_action_edit_conflict_plan_and_close(client):
    key = "action-scenario-" + uuid.uuid4().hex
    action = request(
        client,
        "POST",
        "/career-process/next-actions",
        json={
            "content": "Prepare synthetic interview",
            "status": "planned",
            "time_kind": "flexible",
            "source_kind": "user_request",
            "source_identity": key,
        },
    )
    path = f"/career-process/next-actions/{action['id']}"
    command = {
        "expected_version": action["version"],
        "content": "Updated synthetic preparation",
        "time_kind": "flexible",
    }
    updated = request(client, "PUT", path, json=command)
    assert updated["content"] == command["content"]
    request(client, "PUT", path, json=command, expected=(409,))
    closed = request(
        client,
        "POST",
        path + "/close",
        json={
            "source_kind": "user_assertion",
            "source_identity": key + "-closed",
            "reason": "Acceptance finished",
        },
    )
    assert closed["status"] == "closed"


def test_local_rag_ingestion_retrieval_and_delete(client):
    if os.environ.get("IC_ACCEPTANCE_LOCAL_RAG") != "1":
        pytest.skip("explicit local embedding/reranker acceptance required")
    marker = "RELEASE-RAG-" + uuid.uuid4().hex
    content = (
        f"Synthetic release evidence. {marker} identifies this document. "
        "The application stores canonical evidence in PostgreSQL, uses BGE embeddings "
        "for retrieval and Redis for background dispatch. A deleted document must "
        "stop appearing in retrieval immediately."
    ).encode()
    upload = request(
        client,
        "POST",
        "/file-assets/upload-url",
        json={
            "purpose": "knowledge_document",
            "filename": "release-rag.txt",
            "content_type": "text/plain",
            "size_bytes": len(content),
        },
    )
    response = client.put(
        upload["upload_url"], content=content, headers={"Content-Type": "text/plain"}
    )
    assert response.is_success
    request(client, "POST", f"/file-assets/{upload['file_asset_id']}/confirm")
    created = request(
        client,
        "POST",
        "/knowledge/documents",
        json={"upload_id": upload["file_asset_id"], "title": "Synthetic local RAG"},
    )
    path = f"/knowledge/documents/{created['document']['id']}"
    deleted = False
    try:
        deadline = time.monotonic() + 180
        while True:
            document = request(client, "GET", path)["document"]
            if document["status"] in {"ready", "failed"}:
                break
            assert time.monotonic() < deadline, document
            time.sleep(1)
        assert document["status"] == "ready", document.get("error_message")
        assert document["chunk_count"] > 0
        query = {"query": f"What is the release evidence identifier {marker}?"}
        result = request(client, "POST", "/rag/query", json=query)
        assert marker in json.dumps(result["data"]["chunks"]), result["data"][
            "retrieval_state"
        ]
        request(client, "DELETE", path)
        deleted = True
        request(client, "GET", path, expected=(404,))
        after = request(client, "POST", "/rag/query", json=query)
        assert marker not in json.dumps(after["data"]["chunks"])
    finally:
        if not deleted:
            request(client, "DELETE", path)
