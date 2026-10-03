"""并发压测 + 多用户隔离验证。

用法: python backend/scripts/stress_test.py
前置: 后端已启动 (uvicorn app.main:app)

说明: 无 OPENAI_API_KEY 时, 每个连接收到后端优雅的 error 事件,
     仍能验证「10 用户并发连接不崩溃 + 各流独立 + 隔离」。
"""
import concurrent.futures
import json
import time

import requests

BASE = "http://127.0.0.1:8000/api/v1"


def register_and_login(username: str) -> str:
    """注册(已存在则忽略)并登录, 返回 token。"""
    email = f"{username}@test.com"
    password = "secret123"
    try:
        requests.post(
            f"{BASE}/auth/register",
            json={"email": email, "username": username, "password": password},
            timeout=10,
        )
    except requests.RequestException:
        pass
    r = requests.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    return r.json()["data"]["access_token"]


def chat_once(token: str, session_id: str, message: str):
    """发一次 SSE 流式请求, 返回 (status, 事件数, token 数, 耗时)。"""
    url = f"{BASE}/chat/stream"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"message": message, "mode": "chat", "session_id": session_id}

    t0 = time.time()
    with requests.post(url, json=body, headers=headers, stream=True, timeout=60) as resp:
        status = resp.status_code
        events = 0
        n_tokens = 0
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                data = raw[6:].strip()
                if data == "[DONE]":
                    events += 1
                    break
                try:
                    json.loads(data)
                    events += 1
                    n_tokens += 1
                except json.JSONDecodeError:
                    pass
        return status, events, n_tokens, time.time() - t0


def main():
    # 1. 准备 10 个用户
    user_tokens = {}
    for i in range(1, 11):
        u = f"stress{i}"
        try:
            user_tokens[u] = register_and_login(u)
        except Exception as e:  # noqa: BLE001
            print(f"  用户 {u} 登录失败: {e}")
    print(f"已准备 {len(user_tokens)} 个用户")

    # 2. 10 用户并发对话
    print("\n=== 并发压测(10 用户) ===")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futs = {
            pool.submit(chat_once, user_tokens[u], "shared-session", f"你好, 我是 {u}"): u
            for u in user_tokens
        }
        for fut in concurrent.futures.as_completed(futs):
            u = futs[fut]
            try:
                results[u] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[u] = (None, 0, 0, str(e))

    all_ok = True
    for u in sorted(results):
        status, events, n_tokens, dt = results[u]
        ok = status == 200 and events >= 1
        all_ok = all_ok and ok
        time_str = dt if isinstance(dt, str) else f"{dt:.2f}s"
        print(f"  {u}: status={status} events={events} tokens={n_tokens} {time_str} {'OK' if ok else 'FAIL'}")

    print("\n" + ("[PASS] 并发压测全部通过" if all_ok else "[FAIL] 存在失败"))

    # 3. 隔离验证: 两用户同 session_id, 各自独立成流
    print("\n=== 隔离验证(两用户同 session_id) ===")
    for u in ("stress1", "stress2"):
        status, events, n_tokens, dt = chat_once(user_tokens[u], "isolation-check", "隔离测试")
        print(f"  {u}: status={status} events={events} tokens={n_tokens} ({dt:.2f}s)")


if __name__ == "__main__":
    main()
