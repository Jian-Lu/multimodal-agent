"""Harness 层 — Hook System 单元测试。

所属层级: Harness
"""
import asyncio

from app.harness.hooks import HookManager, get_hook_manager


def run(coro):
    return asyncio.run(coro)


async def _noop(*args, **kwargs):
    return None


def test_register_and_order():
    mgr = HookManager()
    mgr.register_fn("pre", "b", _noop, node="*", priority=200)
    mgr.register_fn("pre", "a", _noop, node="*", priority=100)
    mgr.register_fn("pre", "only_rag", _noop, node="rag", priority=50)

    assert [h.name for h in mgr.hooks_for("pre", "coder")] == ["a", "b"]
    assert [h.name for h in mgr.hooks_for("pre", "rag")] == ["only_rag", "a", "b"]


def test_pre_modifies_state():
    mgr = HookManager()

    async def hook(state, node, config):
        return {"k": 1}

    mgr.register_fn("pre", "p", hook, node="*")
    assert run(mgr.run_pre({}, "x", None)) == {"k": 1}


def test_post_receives_result():
    mgr = HookManager()

    async def hook(state, node, config, result):
        return {"extra": True}

    mgr.register_fn("post", "p", hook, node="*")
    assert run(mgr.run_post({}, "x", None, {"a": 1})) == {"a": 1, "extra": True}


def test_error_returns_fallback():
    mgr = HookManager()

    async def hook(state, node, config, error):
        return {"fallback": True}

    mgr.register_fn("error", "e", hook, node="*")

    async def failing(state):
        raise ValueError("boom")

    assert run(mgr.wrap(failing, "x")({})) == {"fallback": True}


def test_error_reraises_without_fallback():
    mgr = HookManager()

    async def failing(state):
        raise ValueError("boom")

    wrapped = mgr.wrap(failing, "x")
    try:
        run(wrapped({}))
        assert False, "should have raised"
    except ValueError:
        pass


def test_wrap_sync_and_async():
    mgr = HookManager()

    def sync_node(state):
        return {"sync": True}

    async def async_node(state):
        return {"async": True}

    assert run(mgr.wrap(sync_node, "s")({})) == {"sync": True}
    assert run(mgr.wrap(async_node, "a")({})) == {"async": True}


def test_builtin_hooks_registered():
    import app.harness.hooks.builtin  # noqa: F401

    names = {h.name for h in get_hook_manager()._hooks}
    assert "hook_pre_token_budget" in names
    assert "hook_post_audit_logger" in names
    assert "hook_error_fallback" in names


def test_token_budget_hook():
    from app.harness.hooks.builtin.token_budget import hook_pre_token_budget

    class LongMsg:
        content = "x" * 20000  # 20000 chars -> 5000 tokens > 4000

    assert run(hook_pre_token_budget({"messages": [LongMsg()]}, "rag", None)) == {
        "token_budget_exceeded": True
    }

    class ShortMsg:
        content = "hi"

    assert run(hook_pre_token_budget({"messages": [ShortMsg()]}, "rag", None)) is None


def test_audit_logger_returns_none():
    from app.harness.hooks.builtin.audit_logger import hook_post_audit_logger

    assert run(hook_post_audit_logger({}, "rag", {}, {"a": 1})) is None


def test_error_fallback_hook():
    from app.harness.hooks.builtin.error_fallback import hook_error_fallback

    result = run(hook_error_fallback({}, "rag", None, ValueError("x")))
    assert result is not None
    assert "final_answer" in result
    assert result["next_agent"] == "finish"
