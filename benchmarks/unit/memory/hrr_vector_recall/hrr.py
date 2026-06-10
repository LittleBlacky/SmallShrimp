"""HRR (Holographic Reduced Representations) — 零模型依赖的向量编码。

从 Hermes holographic.py 移植，精简为 SmallShrimp 实验用。

原理：
- SHA-256 确定性生成词原子向量 (相位向量)
- bind/unbind: 环形卷积/反卷积 (相位加减)
- bundle: 叠加 (复数平均)
- similarity: 相位余弦相似度

不需要下载模型，纯 numpy 计算。
"""

import hashlib
import math
import re as _re
import struct

_HAS_NUMPY = False
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    pass

_TWO_PI = 2.0 * math.pi


def _require_numpy():
    if not _HAS_NUMPY:
        raise RuntimeError("numpy 是 HRR 的唯一依赖: pip install numpy")


# ── 原子编码 ─────────────────────────────────────────────

def encode_atom(word: str, dim: int = 1024) -> "np.ndarray":
    """SHA-256 确定性相位向量。"""
    _require_numpy()
    values_per_block = 16
    blocks_needed = math.ceil(dim / values_per_block)
    uint16_values: list[int] = []
    for i in range(blocks_needed):
        digest = hashlib.sha256(f"{word}:{i}".encode()).digest()
        uint16_values.extend(struct.unpack("<16H", digest))
    phases = np.array(uint16_values[:dim], dtype=np.float64) * (_TWO_PI / 65536.0)
    return phases


# ── 代数运算 ─────────────────────────────────────────────

def bind(a: "np.ndarray", b: "np.ndarray") -> "np.ndarray":
    """环形卷积 = 相位加法。关联两个概念。"""
    return (a + b) % _TWO_PI


def bundle(*vectors: "np.ndarray") -> "np.ndarray":
    """叠加 = 复数平均。合并多个向量为一个。"""
    _require_numpy()
    complex_sum = np.sum([np.exp(1j * v) for v in vectors], axis=0)
    return np.angle(complex_sum) % _TWO_PI


# ── 相似度 ───────────────────────────────────────────────

def similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    """相位余弦相似度，范围 [-1, 1]。"""
    _require_numpy()
    return float(np.mean(np.cos(a - b)))


# ── 文本编码 ─────────────────────────────────────────────

_CJK_RANGE = _re.compile(r'[\u4e00-\u9fff]')


def _tokenize_text(text: str) -> list[str]:
    """混合中英文 tokenization。

    策略：
    - 英文按空格分词 + 去标点
    - 中文按字符切分，并加相邻 bigram 捕获局部语义
    """
    text = text.lower().strip()
    raw_chunks = text.split()
    tokens: list[str] = []
    for chunk in raw_chunks:
        chunk = chunk.strip(".,!?;:\"'()[]{}")
        if not chunk:
            continue
        if not _CJK_RANGE.search(chunk):
            tokens.append(chunk)
        else:
            chars: list[str] = []
            buf = ""
            for ch in chunk:
                if _CJK_RANGE.match(ch):
                    if buf:
                        chars.append(buf)
                        buf = ""
                    chars.append(ch)
                elif ch.isalnum():
                    buf += ch
                else:
                    if buf:
                        chars.append(buf)
                        buf = ""
                    if ch.strip():
                        chars.append(ch)
            if buf:
                chars.append(buf)
            tokens.extend(chars)
            if len(chars) >= 2:
                for i in range(len(chars) - 1):
                    tokens.append(chars[i] + chars[i + 1])
    return [t for t in tokens if t]


def encode_text(text: str, dim: int = 1024) -> "np.ndarray":
    """Bag-of-words: tokenize → 每个 token 编码为原子向量 → 叠加。

    结果缓存在 _ENCODE_CACHE 中（确定性编码，key = (text, dim)）。
    """
    _require_numpy()
    cache_key = (text, dim)
    if cache_key in _ENCODE_CACHE:
        return _ENCODE_CACHE[cache_key].copy()
    tokens = _tokenize_text(text)
    if not tokens:
        vec = encode_atom("__hrr_empty__", dim)
    else:
        atom_vectors = [encode_atom(token, dim) for token in tokens]
        vec = bundle(*atom_vectors)
    _ENCODE_CACHE[cache_key] = vec.copy()
    return vec


_ENCODE_CACHE: dict[tuple, "np.ndarray"] = {}


# ── 序列化 ───────────────────────────────────────────────

def phases_to_bytes(phases: "np.ndarray") -> bytes:
    """序列化为 bytes。dim=1024 → 8KB。"""
    return phases.tobytes()


def bytes_to_phases(data: bytes) -> "np.ndarray":
    """反序列化。"""
    _require_numpy()
    return np.frombuffer(data, dtype=np.float64).copy()
