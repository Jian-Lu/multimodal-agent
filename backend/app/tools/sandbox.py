"""Tool/Sandbox 层 — 代码执行沙箱 (E2B 主 + Docker 备选)。

所属层级: Tool/Sandbox

安全约束:
- 30 秒超时
- 禁止网络访问 (E2B 沙箱默认无外网; Docker 用 network_disabled=True)
- 严禁 exec() / eval(), 代码只在沙箱容器/隔离环境中执行
"""
import asyncio

from langchain_core.messages import AIMessage

from app.config import settings


class SandboxRunner:
    """代码执行沙箱节点 (同时作为 LangGraph 的 sandbox 节点)。"""

    async def run(self, state: dict) -> dict:
        """图节点入口: 执行 state['code'], 回写 code_result 与最终答案。"""
        code = state.get("code", "")
        if not code:
            result = "(无代码可执行)"
        else:
            try:
                result = await self.execute(code)
            except Exception as e:  # noqa: BLE001 — 沙箱异常统一转为友好输出
                result = f"[沙箱执行失败] {type(e).__name__}: {e}"

        text = f"### 代码执行结果\n```\n{result}\n```"
        return {
            "messages": [AIMessage(content=text)],
            "code_result": result,
            "final_answer": state.get("final_answer", "") + "\n\n" + text,
            "next_agent": "finish",
        }

    async def execute(self, code: str) -> str:
        """按配置选择 E2B 或 Docker 执行 (阻塞调用放入线程池)。"""
        if settings.SANDBOX_BACKEND == "e2b" and settings.E2B_API_KEY:
            return await asyncio.to_thread(self._run_e2b, code)
        return await asyncio.to_thread(self._run_docker, code)

    def _run_e2b(self, code: str) -> str:
        """E2B 云端沙箱执行。"""
        from e2b_code_interpreter import Sandbox

        sbx = Sandbox.create(timeout=settings.SANDBOX_TIMEOUT)
        try:
            execution = sbx.run_code(code, timeout=settings.SANDBOX_TIMEOUT)
            logs = getattr(execution, "logs", None)
            parts: list[str] = []
            if logs is not None:
                for attr in ("stdout", "stderr"):
                    val = getattr(logs, attr, None)
                    if val:
                        parts.extend(val if isinstance(val, list) else [str(val)])
            err = getattr(execution, "error", None)
            if err:
                parts.append(f"error: {err}")
            if not parts:
                text = getattr(execution, "text", None)
                parts.append(str(text) if text is not None else str(execution))
            return "\n".join(parts)
        finally:
            try:
                sbx.kill()
            except Exception:
                pass

    def _run_docker(self, code: str) -> str:
        """Docker 容器执行 (禁网 + 内存限制 + 超时)。"""
        import docker

        client = docker.from_env()
        container = client.containers.run(
            "python:3.11-slim",
            command=["python", "-c", code],
            network_disabled=True,
            mem_limit="256m",
            detach=True,
        )
        try:
            exit_code = container.wait(timeout=settings.SANDBOX_TIMEOUT)
            logs = container.logs().decode("utf-8", errors="replace").strip()
            status = exit_code.get("StatusCode", 1)
            return logs if status == 0 else f"[exit={status}] {logs}"
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass
