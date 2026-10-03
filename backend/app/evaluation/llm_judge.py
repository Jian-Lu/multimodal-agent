"""Evaluation 层 — Layer 3 输出质量 LLM Judge (3 套判分模板 + 打分逻辑)。

所属层级: Evaluation / Layer 3

- judge 模型由 LLM Router 按 intent="judge" 分配 (config ROUTE_JUDGE_MODEL, 可 .env 覆盖强模型)。
- 打分: 每 kind 一组 1-5 维度; overall = 各维度均值。30s 超时(asyncio.wait_for)。
- 失败/超时不抛断批: 返回 None, 由上层记入 errors。

注意: 本模块 import app.llm.factory; 通过 API 端点 lazy-import 或测试直接 import,
     evaluation/__init__.py 不 import 本模块(防循环)。
"""
import asyncio
import json
import logging
import re

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.factory import get_llm_by_intent

logger = logging.getLogger("eval.llm_judge")

# 每 kind 的判分维度 (key 用 ascii, 供结构化输出/聚合)
KIND_CRITERIA: dict[str, list[str]] = {
    "code": ["executability", "correctness", "code_quality", "robustness"],
    "writing": ["structure", "information_density", "readability"],
    "search": ["citation_coverage", "factual_accuracy"],
}

# ---------- 判分模板 (中文 rubric) ----------
_RUBRIC_HEADS: dict[str, str] = {
    "code": (
        "你是一位严格、专业的代码评审专家。依据用户需求与参考答案, 对下面的【候选代码输出】"
        "从以下维度各评 1-5 分。分值: 5=优秀 4=良好 3=合格 2=部分缺陷 1=严重缺陷。"
        "\n判分维度:\n"
        "- executability: 代码能否直接运行, 语法、缩进与依赖引用正确。\n"
        "- correctness: 是否满足用户需求, 功能与参考答案一致。\n"
        "- code_quality: 命名、结构、算法复杂度、注释与可维护性。\n"
        "- robustness: 边界条件、异常与非法输入是否被妥善处理。"
    ),
    "writing": (
        "你是一位严谨的中文写作与文档评审专家。依据用户需求与参考答案, 对下面的【候选文档输出】"
        "从以下维度各评 1-5 分。分值: 5=优秀 4=良好 3=合格 2=部分缺陷 1=严重缺陷。"
        "\n判分维度:\n"
        "- structure: 标题层级、段落/列表/表格的组织是否清晰合理。\n"
        "- information_density: 信息是否准确充实、详略得当, 无冗余空话。\n"
        "- readability: 语言是否通顺专业, 是否易于阅读与检索。"
    ),
    "search": (
        "你是一位事实核查与信息检索评审专家。依据用户需求与参考答案, 对下面的【候选检索回答】"
        "从以下维度各评 1-5 分。分值: 5=优秀 4=良好 3=合格 2=部分缺陷 1=严重缺陷。"
        "\n判分维度:\n"
        "- citation_coverage: 是否提供可核验的引用编号与来源, 覆盖面是否充分。\n"
        "- factual_accuracy: 陈述是否与参考答案/可查事实一致, 有无编造或张冠李戴。"
    ),
}

_JSON_INSTRUCTION = (
    "\n\n只输出一个 JSON 对象, 不要任何额外文字或解释。键为上述判分维度英文名"
    "(值为 1-5 之间的数字)加一个 comment 字符串说明扣分点。"
    '例如 {"executability": 4, "correctness": 5, "code_quality": 4, "robustness": 3, '
    '"comment": "功能正确, 但缺少对边界输入的校验"}。'
)


def build_prompt(kind: str, question: str, output: str, reference: str | None = None) -> str:
    """把 rubric + 用户输入 + 候选输出 + (参考答案) 拼成一个完整 prompt。"""
    if kind not in KIND_CRITERIA:
        raise ValueError(f"未知 judge kind: {kind!r} (可选 {sorted(KIND_CRITERIA)})")
    parts = [_RUBRIC_HEADS[kind]]
    parts.append("\n用户需求:\n" + str(question).strip())
    parts.append("\n候选输出:\n" + str(output).strip())
    if reference:
        parts.append("\n参考答案(评分锚点, 用于比对正确性):\n" + str(reference).strip())
    parts.append(_JSON_INSTRUCTION)
    return "\n".join(parts)


# ---------- 判分结构化输出模型 ----------
class CodeVerdict(BaseModel):
    executability: float = Field(ge=1, le=5)
    correctness: float = Field(ge=1, le=5)
    code_quality: float = Field(ge=1, le=5)
    robustness: float = Field(ge=1, le=5)
    comment: str = ""


class WritingVerdict(BaseModel):
    structure: float = Field(ge=1, le=5)
    information_density: float = Field(ge=1, le=5)
    readability: float = Field(ge=1, le=5)
    comment: str = ""


class SearchVerdict(BaseModel):
    citation_coverage: float = Field(ge=1, le=5)
    factual_accuracy: float = Field(ge=1, le=5)
    comment: str = ""


VERDICT_MODELS: dict[str, type[BaseModel]] = {
    "code": CodeVerdict,
    "writing": WritingVerdict,
    "search": SearchVerdict,
}


# ---------- 纯函数: 解析/归一化 ----------
def _to_number(value) -> float | None:
    """int/float/数字字符串 -> float; 其余(含 bool)返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def parse_judge_json(text: str, criteria: list[str]) -> dict | None:
    """从模型裸文本(可能带 ```json 围栏或前后缀)解析出 {criteria..., comment} 字典。"""
    if not text:
        return None
    t = str(text).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i == -1 or j <= i:
            return None
        t = t[i : j + 1]
    try:
        data = json.loads(t)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def normalize_verdict(kind: str, data: dict | BaseModel) -> dict | None:
    """把 (pydantic Verdict | dict) 归一为 {criteria:{k:v}, overall:均值, comment}。

    criteria 键严格限定 KIND_CRITERIA[kind]; 无效/缺失维度不计入 overall。
    """
    criteria_keys = KIND_CRITERIA.get(kind, [])
    raw = data.model_dump() if hasattr(data, "model_dump") else dict(data or {})
    values: dict[str, float] = {}
    for k in criteria_keys:
        num = _to_number(raw.get(k))
        if num is None:
            continue
        values[k] = round(max(1.0, min(5.0, num)), 2)
    if not values:
        return None
    overall = round(sum(values.values()) / len(values), 2)
    return {
        "criteria": values,
        "overall": overall,
        "comment": str(raw.get("comment", ""))[:300],
    }


# ---------- LLM Judge 主流程 ----------
async def _ainvoke(model, prompt: str):
    return await model.ainvoke(prompt)


async def llm_judge_one(
    kind: str,
    question: str,
    output: str,
    reference: str | None = None,
    llm=None,
    timeout: float | None = None,
) -> dict | None:
    """对一条 (kind, question, output) 打分, 返回 {criteria, overall, comment}。

    llm 可注入(测试桩); 缺省走 get_llm_by_intent('judge', temperature=0)。
    结构化输出失败时退化为裸文本 JSON 解析; 超时/异常返回 None(不抛断批)。
    """
    if kind not in VERDICT_MODELS:
        raise ValueError(f"未知 judge kind: {kind!r} (可选 {sorted(VERDICT_MODELS)})")
    prompt = build_prompt(kind, question, output, reference)
    timeout_s = settings.EVAL_JUDGE_TIMEOUT_S if timeout is None else float(timeout)
    try:
        model = llm if llm is not None else get_llm_by_intent("judge", temperature=0.0)
        structured = model.with_structured_output(VERDICT_MODELS[kind])
        try:
            result = await asyncio.wait_for(_ainvoke(structured, prompt), timeout_s)
            data = result
        except asyncio.TimeoutError:
            logger.warning("Judge: kind=%s 结构化打分超时 %.1fs", kind, timeout_s)
            return None
        except Exception as e:  # noqa: BLE001 — 结构化失败退化文本解析
            logger.warning("Judge: kind=%s 结构化打分失败(%s), 尝试文本解析", kind, e)
            try:
                raw = await asyncio.wait_for(_ainvoke(model, prompt), timeout_s)
                text = raw.content if hasattr(raw, "content") else str(raw)
                data = parse_judge_json(text, KIND_CRITERIA[kind]) or {}
            except asyncio.TimeoutError:
                logger.warning("Judge: kind=%s 文本解析打分超时 %.1fs", kind, timeout_s)
                return None
            except Exception as e2:  # noqa: BLE001
                logger.warning("Judge: kind=%s 文本解析兜底失败(%s)", kind, e2)
                return None
        verdict = normalize_verdict(kind, data)
        if verdict is None:
            logger.warning("Judge: kind=%s 无法从响应提取维度分", kind)
        return verdict
    except Exception as e:  # noqa: BLE001 — 顶层兜底(如模型构建失败)
        logger.warning("Judge: kind=%s 打分异常: %s", kind, e)
        return None
