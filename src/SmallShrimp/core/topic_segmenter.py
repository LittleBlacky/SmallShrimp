"""话题分段存储 — 非线性话题管理。

用户频繁切换话题时，按话题分段维护独立的 mini-buffer，
避免线性存储导致的话题间上下文断裂。

检测策略（三种互补）：
1. 显式信号：检测"换个话题""回到刚才"等关键词
2. 话题回溯：用户提及历史话题标签中的词时，自动回溯
3. 弱连续性：字符 bigram 相似度作为连续性参考
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── 中文停用词 ──────────────────────────────────────

_STOP_WORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "什么",
    "怎么", "啊", "吧", "吗", "嗯", "哦", "哈", "啦", "嘛", "呢", "呀",
    "ok", "got it", "好的", "明白", "知道了", "谢谢", "感谢",
})

# ── 显式话题切换信号 ──────────────────────────────

_TOPIC_SWITCH_SIGNALS: list[tuple[str, int]] = [
    (r"换(个|一(个|下))?话题", 0),           # "换个话题" → 创建新话题
    (r"回到?刚[才刚]", 1),                    # "回到刚才" → 回溯到上一个话题
    (r"之前的[那个话题]", 1),                 # "之前的话题"
    (r"刚[才刚]说(的|过)?的", 1),           # "刚才说的"/"刚说过的"
    (r"刚[才刚]那[个]", 1),                  # "刚才那个"
    (r"先(不管|不说|放着)", 0),              # "先不管那个"
    (r"skip|next|next topic", 0),
]

# ── 信号标签中的 Key 词（用于话题回溯） ──────────

# ── 常见中式会话启动词（不用于话题标签和回溯） ──

_COMMON_VERBS = frozenset({
    "帮我", "我查", "我要", "我想", "我来", "我看", "我问", "你说", "就是",
    "可以", "能不能", "请问", "麻烦", "帮我查", "帮我找", "帮我弄",
    "帮我写", "帮我做", "帮我看看", "我问问", "我需要", "我要求",
    "我建议", "我觉得", "我认为", "我认",
    "我查一", "我查一", "查一下", "一下", "一下北", "下北",
    # 话题切换信号词
    "换个话题", "换个话", "回到刚才", "回到刚", "回到",
    "换个", "个话", "才那", "那话", "刚说", "说过的",
    "先不管", "先不说", "先放着", "话题",
})


def _tokenize(text: str) -> set[str]:
    """字符 bigram + 英文词，用于弱连续性检测。
    
    过滤掉常见句式词（'帮我'、'我查'等）产生的误匹配 bigram。
    """
    tokens: set[str] = set()
    for part in re.findall(r'[a-zA-Z]+', text):
        word = part.lower()
        if len(word) >= 2 and word not in _STOP_WORDS:
            tokens.add(word)
    chars = re.findall(r'[\u4e00-\u9fff]', text)
    for c in chars:
        if c not in _STOP_WORDS:
            tokens.add(c)
    for i in range(len(chars) - 1):
        bg = chars[i] + chars[i + 1]
        if bg not in _STOP_WORDS and bg not in _COMMON_VERBS:
            tokens.add(bg)
    return tokens


def _jaccard_sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_keywords(text: str) -> set[str]:
    """抽取有意义的短关键词（2-4 字），过滤通用动词。"""
    words: set[str] = set()
    for part in re.split(r'[的得地在了是就还要会把和与或跟]', text):
        part = part.strip()
        if len(part) < 2:
            continue
        for i in range(len(part)):
            for j in range(i + 2, min(i + 5, len(part) + 1)):
                sub = part[i:j]
                if sub not in _STOP_WORDS and sub not in _COMMON_VERBS:
                    words.add(sub)
    return {w for w in words if not w.isdigit() and len(w) >= 2}


@dataclass
class TopicSegment:
    """一个话题片段。"""
    id: str = ""
    label: str = ""
    keywords: set[str] = field(default_factory=set)
    tokenized: set[str] = field(default_factory=set)
    message_count: int = 0
    summary: str = ""
    last_active: str = ""


class TopicSegmenter:
    """话题分段管理器。

    三种话题匹配策略：
    1. 显式信号 → 切换到指定话题
    2. 关键词回溯 → 匹配历史话题 keywords
    3. bigram 弱连续 → 归入当前活跃话题
    """

    BIGRAM_THRESHOLD = 0.10      # bigram 阈值，显著重叠才匹配
    MAX_ACTIVE_TOPICS = 5

    def __init__(self, threshold: float = BIGRAM_THRESHOLD):
        self.threshold = threshold
        self.segments: list[TopicSegment] = []
        self._active_idx: int = -1

    @property
    def active_topic(self) -> str:
        if 0 <= self._active_idx < len(self.segments):
            return self.segments[self._active_idx].label
        return ""

    # ── 话题检测（主入口） ───────────────────────────

    def detect_topic(self, text: str) -> tuple[int, str, float]:
        """检测文本所属的话题。返回 (index, method, score)。
        
        index=-1 表示新话题。signal 中:
          - back_n=0 → 创建新话题（"换个话题"）
          - back_n=1 → 回溯到上一个话题（"回到刚才"）
        """
        text_lower = text.lower().strip()

        # 策略 1: 显式话题切换信号
        for pattern, back_n in _TOPIC_SWITCH_SIGNALS:
            if re.search(pattern, text_lower):
                if back_n == 1 and self._active_idx >= 1:
                    # 回到上一个话题
                    return self._active_idx - 1, "signal", 1.0
                # back_n == 0 → 创建新话题
                return -1, "signal", 1.0

        tokens = _tokenize(text)
        keywords = _extract_keywords(text)

        if not tokens:
            return self._active_idx, "bigram", 0.0

        # 策略 2: 关键词回溯
        if keywords:
            backup_idx, backup_score = -1, 0
            for i, seg in enumerate(self.segments):
                if seg.keywords:
                    overlap = len(keywords & seg.keywords)
                    if overlap > backup_score:
                        backup_score = overlap
                        backup_idx = i
            if backup_idx >= 0 and backup_score >= 1:
                return backup_idx, "keyword", float(backup_score)

        # 策略 3: bigram 弱连续
        best_idx, best_score = -1, 0.0
        for i, seg in enumerate(self.segments):
            score = _jaccard_sim(tokens, seg.tokenized)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score >= self.threshold:
            return best_idx, "bigram", best_score

        # 策略 4: 如果当前活跃话题是空的占位话题（signal 创建还未填内容），强制分配给该话题
        if (self._active_idx >= 0
                and self.segments[self._active_idx].message_count == 0
                and self.segments[self._active_idx].label == "新话题"):
            return self._active_idx, "continuity", 0.0

        # 策略 5: 如果只有唯一话题，保持连续性
        if self._active_idx >= 0 and len(self.segments) == 1:
            return self._active_idx, "continuity", 0.0

        return -1, "new", 0.0

    # ── 话题切换 ────────────────────────────────────

    def on_turn(self, user_content: str, assistant_content: str,
                now: str) -> dict[str, Any]:
        """每轮对话后调用，更新话题状态。"""
        idx, method, score = self.detect_topic(user_content)
        old_label = self.active_topic
        is_new_topic = idx < 0

        if is_new_topic:
            # 判断是否是纯信号消息（匹配整个文本是话题切换语句）
            _is_signal_only = False
            if method == "signal":
                for pat, _ in _TOPIC_SWITCH_SIGNALS:
                    if re.search(pat, user_content.lower().strip()):
                        _is_signal_only = True
                        break
            if _is_signal_only:
                label = "新话题"
            else:
                label = self._infer_label(user_content)
            seg = TopicSegment(
                id=f"topic_{len(self.segments)}",
                label=label,
                keywords=_extract_keywords(user_content),
                tokenized=_tokenize(user_content),
                message_count=1 if not _is_signal_only else 0,
                last_active=now,
            )
            self.segments.append(seg)
            self._active_idx = len(self.segments) - 1
        else:
            seg = self.segments[idx]
            seg.message_count += 1
            seg.last_active = now
            # 如果话题还是占位标签且新消息有实质内容, 更新标签
            new_kw = _extract_keywords(user_content)
            if seg.label == "新话题" and new_kw:
                seg.label = self._infer_label(user_content)
            seg.keywords |= new_kw
            seg.tokenized |= _tokenize(user_content)
            self._active_idx = idx

        self._trim_inactive()

        return {
            "topic_changed": (is_new_topic or method in ("signal", "keyword")) and self._active_idx >= 0,
            "match_method": method,
            "match_score": round(score, 3),
            "old_topic": old_label,
            "new_topic": self.active_topic,
            "segments_summary": self.build_summary(),
        }

    # ── 话题标签推断 ───────────────────────────────

    def _infer_label(self, text: str) -> str:
        """用户首条消息去掉启动词后的前 10 字作为话题标签。"""
        for verb in sorted(_COMMON_VERBS, key=len, reverse=True):
            if text.startswith(verb):
                text = text[len(verb):]
                break
        return text.strip()[:12] or text[:12]

    # ── 话题裁剪 ──────────────────────────────────

    def _trim_inactive(self) -> None:
        if len(self.segments) <= self.MAX_ACTIVE_TOPICS:
            return
        active_id = self.segments[self._active_idx].id if 0 <= self._active_idx < len(self.segments) else ""
        self.segments.sort(key=lambda s: s.last_active, reverse=True)
        self.segments = self.segments[:self.MAX_ACTIVE_TOPICS]
        for i, seg in enumerate(self.segments):
            if seg.id == active_id:
                self._active_idx = i
                return
        self._active_idx = 0

    # ── 上下文组装 ──────────────────────────────────

    def build_summary(self) -> str:
        if not self.segments:
            return ""
        lines = ["\n## 话题状态"]
        for i, seg in enumerate(self.segments):
            marker = "🔄" if i == self._active_idx else "⏸"
            lines.append(f"{marker} **{seg.label}** ({seg.message_count}条)")
            if seg.summary:
                lines.append(f"   ↳ {seg.summary}")
        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────────

    def to_dict(self) -> list[dict]:
        return [{"id": s.id, "label": s.label, "message_count": s.message_count,
                 "last_active": s.last_active} for s in self.segments]

    def from_dict(self, data: list[dict]) -> None:
        self.segments = [TopicSegment(**{**d, "id": d.get("id", f"topic_{i}")})
                         for i, d in enumerate(data)]
