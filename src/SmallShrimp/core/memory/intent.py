"""Memory intent detection — catch durable instructions proactively.

Three buckets (ported from ZLAgent):
  NEGATIVE — explicit "don't store" → short-circuit
  HIGH     — almost certainly worth a memory write
  MEDIUM   — probably worth a write; LLM has final say
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryIntentSignal:
    triggered: bool
    confidence: str = "none"    # "none" | "high" | "medium"
    reason: str = ""
    matched: tuple[str, ...] = ()


# ── NEGATIVE — explicit "don't store" ────────────────────────

_NEGATIVE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"不用记(住|下来)?",
        r"不要记(住|下来)?",
        r"别记(住|下来)?",
        r"这次不用(记|存)",
        r"临时的?(就行|就好|可以)?",
        r"一次性",
        r"不用长期(记|存)",
        r"don'?t\s+remember",
        r"do\s+not\s+remember",
        r"forget\s+(that|this)",
        r"just\s+for\s+now",
        r"this\s+time\s+only",
    )
)

# ── HIGH — identity corrections, hard rules ──────────────────

_HIGH_PATTERNS: dict[str, re.Pattern[str]] = {
    "explicit_remember": re.compile(
        r"记住|记下来?|帮我记|存一下|留个备忘|"
        r"remember\s+(this|that|me)|note\s+this\s+down|save\s+this\s+to\s+memory",
        re.IGNORECASE,
    ),
    "future_default": re.compile(
        r"以后|之后(都|起)|从现在开始|从此|从今天起|默认|每次|下次(再|开始|起)|"
        r"一直(用|都)|"
        r"from\s+now\s+on|going\s+forward|in\s+the\s+future|always|"
        r"next\s+time|by\s+default",
        re.IGNORECASE,
    ),
    "stop_doing": re.compile(
        r"别再|不要再|以后不要|以后别|别总是|不要总是|不要(继续)?这样|"
        r"stop\s+(doing|saying|calling)|never\s+(do|say|call)|"
        r"don'?t\s+(do\s+that|say\s+that|call\s+me)",
        re.IGNORECASE,
    ),
    "identity_correction": re.compile(
        r"我(其实)?(就|不|真的)?叫\s*[\w一-鿿]+|"
        r"我的名字(是|叫)|"
        r"别叫我|不要叫我|不(是|叫)\s*[\w一-鿿]+\s*(吗|啊|嘛)?$|"
        r"my\s+name\s+is\b|"
        r"call\s+me\s+[A-Z]\w*|"
        r"don'?t\s+call\s+me",
        re.IGNORECASE,
    ),
    "value_correction": re.compile(
        r"(改|换)成|应该是\s*[\w一-鿿]+|"
        r"不是.+(是|叫)|"
        r"actually\s+it'?s|it\s+should\s+be|the\s+correct\s+one\s+is",
        re.IGNORECASE,
    ),
}

# ── MEDIUM — preferences, relationships, context ─────────────

_MEDIUM_PATTERNS: dict[str, re.Pattern[str]] = {
    "preference": re.compile(
        r"我(更|很|挺|特别)?(喜欢|不喜欢|讨厌|偏好|习惯|倾向于?|想要|希望|打算)|"
        r"我的习惯(是|就是)|"
        r"i\s+(like|love|hate|prefer|enjoy|dislike|don'?t\s+like|want\s+to|"
        r"need\s+to|tend\s+to)\b",
        re.IGNORECASE,
    ),
    "assistant_should": re.compile(
        r"你应该|你要|你不用|你不要|你别|请你|麻烦你|"
        r"请优先|优先|尽量|尽可能|"
        r"please\s+(do|don'?t|always|never|avoid|prefer)|"
        r"can\s+you\s+(always|never)|could\s+you\s+(always|never)",
        re.IGNORECASE,
    ),
    "style_format": re.compile(
        r"回复.*(简短|详细|短一点|长一点|格式|语气|风格|自然|口语|专业|严谨)|"
        r"格式.*(固定|保持|统一)|语气.*(正式|随意|轻松)|"
        r"太(长|短|啰嗦|正式|生硬)|"
        r"(简单|直接|短)一点|"
        r"reply\s+(shorter|longer|in\s+\w+)|"
        r"(less|more)\s+(verbose|formal|casual)",
        re.IGNORECASE,
    ),
    "relationship": re.compile(
        r"我(的)?(老婆|老公|对象|男朋友|女朋友|配偶|爱人|"
        r"父亲|母亲|爸爸?|妈妈?|"
        r"姐姐|妹妹|哥哥|弟弟|兄弟|姐妹|"
        r"孩子|儿子|女儿|"
        r"宠物|猫|狗|乌龟|鸟|仓鼠|"
        r"室友|同事|领导|老板|同学)|"
        r"我家(里|有|养)?\S{0,4}(老婆|老公|爸爸?|妈妈?|"
        r"父亲|母亲|姐姐|妹妹|哥哥|弟弟|"
        r"孩子|儿子|女儿|"
        r"宠物|猫|狗|乌龟|鸟|仓鼠)|"
        r"my\s+(wife|husband|partner|gf|bf|girlfriend|boyfriend|spouse|"
        r"dad|mom|mother|father|son|daughter|kid|child|"
        r"sister|brother|sibling|"
        r"pet|cat|dog|"
        r"roommate|coworker|boss|colleague|classmate)",
        re.IGNORECASE,
    ),
    "recurring_event": re.compile(
        r"每(天|日|周|月|年|次|小时|半小时|两天|两周)|每隔\s*\d+|"
        r"周[一二三四五六日天]\s*(都|要)?|"
        r"工作日|休息日|周末|"
        r"早上\s*\d+\s*点|晚上\s*\d+\s*点|"
        r"every\s+(day|week|month|year|morning|night|monday|tuesday|wednesday|"
        r"thursday|friday|saturday|sunday)|"
        r"daily|weekly|monthly|yearly|"
        r"on\s+(weekdays|weekends)",
        re.IGNORECASE,
    ),
    "time_locale": re.compile(
        r"时区|北京时间|上海时间|东八区|UTC[+\-]\d+|"
        r"我(住在|位于)\s*[\w一-鿿]+|"
        r"我家在\s*[\w一-鿿]+|"
        r"timezone|i'?m\s+in\s+\w+|i\s+live\s+in",
        re.IGNORECASE,
    ),
    "project_context": re.compile(
        r"我(在|正在)?做(一个|个)?[\w一-鿿\s]{1,20}?(项目|应用|网站|工具|"
        r"app|系统|产品|服务|公司|创业)|"
        r"我的项目|我的代码库|我的(repo|仓库)|"
        r"i'?m\s+(working\s+on|building|developing)|"
        r"my\s+(project|repo|codebase|company|startup)",
        re.IGNORECASE,
    ),
    "tool_pref": re.compile(
        r"我用\s*[\w一-鿿]+|我习惯用|我的(电脑|机器|手机|系统|环境)|"
        r"i\s+use\s+\w+|my\s+(machine|laptop|phone|system|setup|environment)",
        re.IGNORECASE,
    ),
}


def detect_memory_intent(text: str) -> MemoryIntentSignal:
    """Detect if the user message contains durable instructions worth remembering."""
    content = (text or "").strip()
    if not content:
        return MemoryIntentSignal(triggered=False)

    # NEGATIVE short-circuit
    for pattern in _NEGATIVE_PATTERNS:
        if pattern.search(content):
            return MemoryIntentSignal(
                triggered=False,
                confidence="none",
                reason="negative_memory_request",
                matched=(pattern.pattern,),
            )

    # HIGH
    high = [name for name, pattern in _HIGH_PATTERNS.items() if pattern.search(content)]
    if high:
        return MemoryIntentSignal(
            triggered=True,
            confidence="high",
            reason="durable_instruction_or_preference",
            matched=tuple(high),
        )

    # MEDIUM
    medium = [name for name, pattern in _MEDIUM_PATTERNS.items() if pattern.search(content)]
    if medium:
        return MemoryIntentSignal(
            triggered=True,
            confidence="medium",
            reason="possible_user_preference",
            matched=tuple(medium),
        )

    return MemoryIntentSignal(triggered=False)


def render_memory_intent_hint(signal: MemoryIntentSignal) -> str:
    """Render an LLM-facing hint nudging proactive memory writes."""
    if not signal.triggered:
        return ""
    matched = ", ".join(signal.matched) if signal.matched else signal.reason
    return (
        f"\n\n[主动记忆触发] 本轮命中长期偏好/纠正信号"
        f" (confidence={signal.confidence}; matched={matched})。"
        f"请判断是否需要调用记忆工具写入——用户不应该重复说同一件事第二次。"
    )
