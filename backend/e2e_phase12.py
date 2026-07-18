"""Phase 12 E2E verification against the LIVE backend (http://127.0.0.1:8000).

Exercises the full auth + persistence surface over real HTTP with cookies:

  1.  guest keeps working: /knowledge/query with no token
  2.  register -> access token + HttpOnly refresh cookie
  3.  /auth/me with the token; 401 without it
  4.  refresh rotation: new token pair, old refresh token now invalid
  5.  reuse detection: replaying the OLD cookie revokes everything
  6.  login again, chat CRUD: create/ask/list/search/rename/get/delete
  7.  multi-turn memory: follow-up question resolved via history
  8.  ownership: user B gets 404 for user A's chat
  9.  logout: refresh afterwards fails
  10. logout-all revokes every session

Throw-away verification script — not part of the application.
"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


class Client:
    """Tiny cookie-aware HTTP client (per simulated device/browser)."""

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {}
        if data:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                self._absorb(resp)
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            self._absorb(err)
            try:
                return err.code, json.loads(err.read() or b"{}")
            except ValueError:
                return err.code, {}

    def _absorb(self, resp) -> None:
        for header, value in resp.headers.items():
            if header.lower() != "set-cookie":
                continue
            first = value.split(";", 1)[0]
            if "=" not in first:
                continue
            name, val = first.split("=", 1)
            if val in ('""', ""):
                self.cookies.pop(name.strip(), None)
            else:
                self.cookies[name.strip()] = val


def main() -> None:
    import uuid

    email_a = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"e2e-{uuid.uuid4().hex[:8]}@example.com"

    print("== 1. Guest mode untouched ==")
    guest = Client()
    status, body = guest.call("POST", "/knowledge/query", {"question": "Is PAN mandatory for KYC?"})
    check("guest /knowledge/query answers without auth", status == 200 and bool(body.get("answer")))
    status, _ = guest.call("GET", "/session/nonexistent")
    check("existing endpoints still guest-accessible (404 not 401)", status == 404)

    print("== 2/3. Register + me ==")
    a = Client()
    status, body = a.call(
        "POST", "/auth/register",
        {"email": email_a, "password": "s3cure-pass!A", "full_name": "User A"},
    )










    check("register 201 + access token", status == 201 and bool(body.get("access_token")))
    check("refresh cookie set (HttpOnly)", "kf_refresh" in a.cookies)
    check("refresh token NOT in the JSON body", "refresh_token" not in json.dumps(body))
    a.token = body["access_token"]
    status, me = a.call("GET", "/auth/me")
    check("/auth/me with token", status == 200 and me.get("email") == email_a)
    anon = Client()
    status, _ = anon.call("GET", "/auth/me")
    check("/auth/me without token -> 401", status == 401)
    status, _ = anon.call("GET", "/chats")
    check("/chats without token -> 401", status == 401)

    print("== 4/5. Rotation + reuse detection ==")
    old_cookie = dict(a.cookies)
    status, body = a.call("POST", "/auth/refresh")
    check("refresh rotates (200 + new access token)", status == 200 and bool(body.get("access_token")))
    a.token = body["access_token"]
    replay = Client()
    replay.cookies = old_cookie
    status, _ = replay.call("POST", "/auth/refresh")
    check("replaying the OLD refresh token -> 401 (rotation)", status == 401)
    status, _ = a.call("POST", "/auth/refresh")
    check("reuse detection revoked ALL sessions (current cookie also 401)", status == 401)

    print("== 6. Login + chat CRUD ==")
    a = Client()
    status, body = a.call("POST", "/auth/login", {"email": email_a, "password": "s3cure-pass!A"})
    check("login after revocation", status == 200)
    a.token = body["access_token"]
    status, wrong = a.call("POST", "/auth/login", {"email": email_a, "password": "wrong-pass-123"})
    check("wrong password -> 401 invalid_credentials", status == 401 and wrong.get("error", {}).get("code") == "invalid_credentials")

    status, chat = a.call("POST", "/chats", {})
    check("create chat 201", status == 201 and bool(chat.get("chat_id")))
    chat_id = chat["chat_id"]
    status, turn = a.call("POST", f"/chats/{chat_id}/messages", {"question": "Is PAN mandatory for KYC?"})

    print("ASK STATUS:", status)
    print("ASK BODY:", turn)





    check("ask in chat persists + answers", status == 200 and bool(turn.get("assistant_message", {}).get("content")))
    has_citations = bool(turn.get("assistant_message", {}).get("citations"))
    check("assistant message carries citations", has_citations)

    print("== 7. Multi-turn memory ==")
    status, follow = a.call("POST", f"/chats/{chat_id}/messages", {"question": "What happens if I don't have it?"})
    check("follow-up answers (memory path)", status == 200 and bool(follow.get("assistant_message", {}).get("content")))

    status, listing = a.call("GET", "/chats")
    check("list shows the chat, auto-titled", status == 200 and listing["total"] >= 1
          and listing["chats"][0]["title"].startswith("Is PAN"))
    status, search = a.call("GET", "/chats?q=PAN")
    check("search finds it", status == 200 and search["total"] >= 1)
    status, search2 = a.call("GET", "/chats?q=zzz-no-match-zzz")
    check("search excludes non-matches", status == 200 and search2["total"] == 0)
    status, renamed = a.call("PATCH", f"/chats/{chat_id}", {"title": "PAN questions"})
    check("rename", status == 200 and renamed["title"] == "PAN questions")
    status, detail = a.call("GET", f"/chats/{chat_id}")
    check("continue chat: transcript has 4 messages", status == 200 and len(detail["messages"]) == 4)

    print("== 8. Ownership ==")
    b = Client()
    status, body = b.call(
        "POST", "/auth/register",
        {"email": email_b, "password": "s3cure-pass!B", "full_name": "User B"},
    )
    b.token = body["access_token"]
    status, _ = b.call("GET", f"/chats/{chat_id}")
    check("user B reading A's chat -> 404", status == 404)
    status, _ = b.call("DELETE", f"/chats/{chat_id}")
    check("user B deleting A's chat -> 404", status == 404)

    status, _ = a.call("DELETE", f"/chats/{chat_id}")
    check("owner deletes own chat", status == 200)
    status, _ = a.call("GET", f"/chats/{chat_id}")
    check("deleted chat is gone (404)", status == 404)

    print("== 9/10. Logout + logout-all ==")
    status, _ = a.call("POST", "/auth/logout")
    check("logout 200", status == 200)
    status, _ = a.call("POST", "/auth/refresh")
    check("refresh after logout -> 401", status == 401)

    b2 = Client()  # second device for B
    status, body2 = b2.call("POST", "/auth/login", {"email": email_b, "password": "s3cure-pass!B"})
    status, out = b.call("POST", "/auth/logout-all")
    check("logout-all reports revoked sessions >= 2", status == 200 and out.get("sessions_revoked", 0) >= 2)
    status, _ = b2.call("POST", "/auth/refresh")
    check("other device's refresh also dead", status == 401)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", *FAILED, sep="\n  - ")
        raise SystemExit(1)
    print("ALL PHASE 12 CHECKS PASSED")


if __name__ == "__main__":
    main()
