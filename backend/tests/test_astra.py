import time


def chat(client, token, content, conversation_id=None, mode="auto"):
    events = []
    with client.websocket_connect("/api/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "chat", "content": content, "conversation_id": conversation_id, "mode": mode})
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("done", "error"):
                break
    return events


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return fn()


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_auth_required(client):
    assert client.get("/api/memory").status_code == 401
    assert client.get("/api/memory", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_login_flow(client, auth):
    r = client.post("/api/auth/login", json={"email": "nobody@test.dev", "password": "wrongpass1"})
    assert r.status_code == 401
    h, _ = auth
    me = client.get("/api/auth/me", headers=h).json()
    r = client.post("/api/auth/login", json={"email": me["email"], "password": "supersecret1"})
    assert r.status_code == 200 and r.json()["token"]


def test_chat_streams_and_persists(client, auth):
    h, token = auth
    ev = chat(client, token, "hey what's up")
    types = [e["type"] for e in ev]
    assert types[0] == "start" and "token" in types and types[-1] == "done"
    assert ev[0]["mode"] == "companion"
    cid = ev[-1]["conversation_id"]
    conv = client.get(f"/api/conversations/{cid}", headers=h).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert "Hey there!" in conv["messages"][1]["content"]


def test_auto_mode_selection(client, auth):
    _, token = auth
    assert chat(client, token, "I have a bug in my python function, stack trace attached")[0]["mode"] == "developer"
    assert chat(client, token, "Explain logistic regression intuition")[0]["mode"] == "professor"
    assert chat(client, token, "How should I prepare for internship interviews?")[0]["mode"] == "mentor"
    assert chat(client, token, "anything", mode="reality")[0]["mode"] == "reality"


def test_memory_extraction_retrieval_and_graph(client, auth):
    h, token = auth
    chat(client, token, "By the way I study Computer Science at IIT. Also I built StudyBuddy with FastAPI.")
    items = wait_for(lambda: client.get("/api/memory", headers=h).json()["items"] if len(client.get("/api/memory", headers=h).json()["items"]) >= 2 else None)
    contents = [m["content"] for m in items]
    assert any("studies Computer Science" in c for c in contents)
    assert any("StudyBuddy" in c for c in contents)
    # A new conversation should retrieve the memory into the prompt
    ev = chat(client, token, "what do I study again? remind me what course I'm doing")
    # (fake model calls create_reminder for 'remind me'; final text after tool)
    ev = chat(client, token, "what do I study at university, Computer Science or something else?")
    text = "".join(e["content"] for e in ev if e["type"] == "token")
    assert "KNOWS_STUDY" in text
    ctx = next(e for e in ev if e["type"] == "context")
    assert any("Computer Science" in m["content"] for m in ctx["memories"])
    g = client.get("/api/memory/graph/data", headers=h).json()
    names = {n["name"] for n in g["nodes"]}
    assert {"Me", "StudyBuddy", "FastAPI"} <= names
    assert any(l["relation"] == "uses" for l in g["links"])


def test_duplicate_detection(client, auth):
    h, _ = auth
    a = client.post("/api/memory", json={"content": "The user loves biryani", "category": "preferences"}, headers=h).json()
    b = client.post("/api/memory", json={"content": "The user loves biryani", "category": "preferences"}, headers=h).json()
    assert a["created"] is True and b["created"] is False and a["memory"]["id"] == b["memory"]["id"]


def test_sensitive_memory_needs_approval_and_is_encrypted(client, auth):
    h, token = auth
    chat(client, token, "honestly the exam anxiety is getting to me")
    pending = wait_for(lambda: client.get("/api/memory?status=pending", headers=h).json()["items"])
    assert pending and pending[0]["sensitive"] and "anxiety" in pending[0]["content"]
    assert not any("anxiety" in m["content"] for m in client.get("/api/memory", headers=h).json()["items"])
    # stored encrypted at rest
    import asyncio

    from app.core.db import SessionLocal
    from app.models import Memory

    async def raw():
        async with SessionLocal() as db:
            return (await db.get(Memory, pending[0]["id"])).content

    assert "anxiety" not in client.portal.call(raw)
    client.post(f"/api/memory/{pending[0]['id']}/approve", headers=h)
    assert any("anxiety" in m["content"] for m in client.get("/api/memory", headers=h).json()["items"])


def test_memory_edit_delete_search(client, auth):
    h, _ = auth
    m = client.post("/api/memory", json={"content": "The user's favourite language is Rust", "category": "preferences"}, headers=h).json()["memory"]
    r = client.patch(f"/api/memory/{m['id']}", json={"content": "The user's favourite language is Python"}, headers=h).json()
    assert "Python" in r["content"]
    s = client.get("/api/memory/search", params={"q": "favourite language python"}, headers=h).json()["items"]
    assert s and s[0]["id"] == m["id"]
    assert client.delete(f"/api/memory/{m['id']}", headers=h).json()["deleted"]
    assert client.get("/api/memory/search", params={"q": "favourite language python"}, headers=h).json()["items"] == [] or \
        all(i["id"] != m["id"] for i in client.get("/api/memory/search", params={"q": "favourite language python"}, headers=h).json()["items"])


def test_user_isolation(client, auth):
    h1, _ = auth
    m = client.post("/api/memory", json={"content": "Secret plan: build a rocket", "category": "goals"}, headers=h1).json()["memory"]
    r = client.post("/api/auth/register", json={"email": "intruder@test.dev", "password": "supersecret1"})
    h2 = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/memory", headers=h2).json()["items"] == []
    assert client.get("/api/memory/search", params={"q": "rocket plan"}, headers=h2).json()["items"] == []
    assert client.patch(f"/api/memory/{m['id']}", json={"content": "hacked"}, headers=h2).status_code == 404
    assert client.delete(f"/api/memory/{m['id']}", headers=h2).status_code == 404


def test_tool_call_creates_reminder(client, auth):
    h, token = auth
    ev = chat(client, token, "remind me to drink water")
    assert any(e["type"] == "tool" and e["name"] == "create_reminder" and e["status"] == "ok" for e in ev)
    assert client.get("/api/reminders", headers=h).json()["items"][0]["text"] == "drink water"


def test_consequential_action_requires_confirmation(client, auth):
    h, token = auth
    ev = chat(client, token, "send an email to my friend")
    pa = next(e for e in ev if e["type"] == "pending_action")["action"]
    assert pa["status"] == "pending" and pa["tool"] == "gmail_send"
    r = client.post(f"/api/actions/{pa['id']}/reject", headers=h).json()
    assert r["status"] == "rejected"
    assert client.post(f"/api/actions/{pa['id']}/approve", headers=h).status_code == 409


def test_tasks_projects_dashboard(client, auth):
    h, _ = auth
    p = client.post("/api/projects", json={"name": "ASTRA", "tech_stack": ["FastAPI", "React"]}, headers=h).json()
    t = client.post("/api/tasks", json={"title": "Write README", "priority": "high", "project_id": p["id"]}, headers=h).json()
    client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=h)
    d = client.get("/api/dashboard", headers=h).json()
    assert d["stats"]["tasks_done_week"] == 1 and d["ai_configured"] is True
    assert client.get("/api/projects", headers=h).json()["items"][0]["tasks"][0]["status"] == "done"


def test_onboarding_and_profile(client, auth):
    h, _ = auth
    r = client.post("/api/onboarding", json={"name": "Tanisha", "education": "B.Tech CSE, 3rd year", "career_goals": "ML engineer"}, headers=h)
    assert len(r.json()["created"]) == 3
    k = client.get("/api/memory/profile/knowledge", headers=h).json()
    studying = next(s for s in k["sections"] if s["key"] == "studying")
    assert "B.Tech" in studying["items"][0]["content"]
    assert client.get("/api/auth/me", headers=h).json()["onboarded"] is True


def test_document_upload_and_search(client, auth):
    h, _ = auth
    text = ("Tanisha's CV. Skills: Python, FastAPI, PyTorch. Experience: ML intern at Acme working on recommendation systems. " * 5).encode()
    r = client.post("/api/documents", files={"file": ("cv.txt", text, "text/plain")}, data={"extract_memories": "false"}, headers=h)
    assert r.status_code == 200, r.text
    did = r.json()["document"]["id"]
    wait_for(lambda: [d for d in client.get("/api/documents", headers=h).json()["items"] if d["id"] == did and d["status"] == "ready"])
    assert client.get("/api/documents", headers=h).json()["items"][0]["status"] == "ready"


def test_chatgpt_import(client, auth):
    import json

    h, _ = auth
    export = [{"title": "Career chat", "create_time": 1700000000, "update_time": 1700000100, "current_node": "c",
               "mapping": {"a": {"message": None, "parent": None},
                           "b": {"message": {"author": {"role": "user"}, "content": {"parts": ["I study Data Science"]}, "create_time": 1700000000}, "parent": "a"},
                           "c": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["Nice!"]}, "create_time": 1700000050}, "parent": "b"}}}]
    data = json.dumps(export).encode()
    prev = client.post("/api/import/chatgpt/preview", files={"file": ("conversations.json", data)}, headers=h).json()
    assert prev["conversations"] == 1 and prev["messages"] == 2
    job = client.post("/api/import/chatgpt", files={"file": ("conversations.json", data)}, data={"max_conversations": "10"}, headers=h).json()
    done = wait_for(lambda: (j := client.get(f"/api/jobs/{job['id']}", headers=h).json())["status"] in ("done", "failed") and j)
    assert done["status"] == "done", done
    assert any("Data Science" in m["content"] for m in client.get("/api/memory", headers=h).json()["items"])
    assert client.get("/api/conversations?source=chatgpt", headers=h).json()["total"] == 1


def test_voice_endpoints(client, auth):
    h, _ = auth
    r = client.post("/api/voice/transcribe", files={"file": ("a.webm", b"x" * 2000, "audio/webm")}, headers=h)
    assert r.json()["text"] == "hello astra"
    r = client.post("/api/voice/speak", json={"text": "hi"}, headers=h)
    assert r.headers["content-type"] == "audio/mpeg"


def test_settings_export_wipe(client, auth):
    h, _ = auth
    r = client.patch("/api/settings", json={"personality": {"sarcasm": 0.9}}, headers=h).json()
    assert r["settings"]["personality"]["sarcasm"] == 0.9 and r["settings"]["personality"]["hinglish"] is True
    assert client.patch("/api/settings", json={"evil": 1}, headers=h).status_code == 400
    client.post("/api/memory", json={"content": "The user enjoys chess", "category": "preferences"}, headers=h)
    ex = client.get("/api/export", headers=h).json()
    assert any("chess" in m["content"] for m in ex["memories"])
    assert client.post("/api/data/wipe", json={"password": "bad", "scope": "memories"}, headers=h).status_code == 400
    client.post("/api/data/wipe", json={"password": "supersecret1", "scope": "memories"}, headers=h)
    assert client.get("/api/memory", headers=h).json()["items"] == []


def test_ws_rejects_bad_token(client):
    with client.websocket_connect("/api/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": "garbage"})
        assert ws.receive_json()["code"] == "unauthorized"


def test_proactive_reminder_notification(client, auth):
    h, _ = auth
    client.post("/api/reminders", json={"text": "Call mom", "remind_at": "2020-01-01T10:00:00Z"}, headers=h)
    from app.core.db import SessionLocal
    from app.models import User
    from app.services import proactive

    me = client.get("/api/auth/me", headers=h).json()

    async def run():
        async with SessionLocal() as db:
            return await proactive.run_for_user(db, await db.get(User, me["id"]))

    assert client.portal.call(run) >= 1
    n = client.get("/api/notifications", headers=h).json()
    assert any("Call mom" in i["title"] for i in n["items"])
