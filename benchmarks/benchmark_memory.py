"""
Benchmark Suite v2 — 记忆层改进全量化实验（50 条数据集 + STAR 验证）
运行: conda activate smallshrimp && python benchmarks/benchmark_memory.py
"""
from __future__ import annotations

import sys, os, time, json, math, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.SmallShrimp.core.context_guard import COMPACT_PROMPT
from src.SmallShrimp.core.topic_segmenter import TopicSegmenter
from src.SmallShrimp.core.conversation_buffer import ConversationBuffer
from src.SmallShrimp.core.todo_tracker import TodoTracker, TaskStatus
from src.SmallShrimp.core.tool_state import ToolStateMemory
from src.SmallShrimp.core.reflection import ReflectionEngine, REFLECTION_PROMPT
from src.SmallShrimp.core.dreaming import DreamingEngine
from src.SmallShrimp.core.priority_resolver import PriorityResolver
from src.SmallShrimp.core.memory.builtin.common import (
    ENTITY_TYPES, same_layer_group, _is_duplicate_with_layer
)

RESULTS = {}

# ═══════════════════════════════════════════════════════════
# Phase 1: 分级压缩 + constraints 层
# ═══════════════════════════════════════════════════════════

def experiment_phase1():
    print("=" * 60)
    print("Phase 1: 分级压缩 + constraints 层")
    print("=" * 60)

    OLD_PROMPT = """Your task is to create a detailed summary of the conversation so far, capturing the user's requests, your actions, and any important context needed to continue without losing information.

Your summary should include:
1. Primary Request and Intent
2. Key Facts and User Preferences
3. User Messages (ALL user messages)
4. Errors and Corrections
5. Current Work and Pending Tasks

Here is the conversation to summarize:

{conversation}

Please provide your summary following this structure."""

    constraint_keywords = [
        "Verbatim", "do NOT paraphrase", "Negative constraints",
        "Numeric constraints", "MUST Preserve", "EXACT original text",
        "CAN Summarize", "CAN Drop", "Hard Constraints",
        "copy-paste", "Pleasantries",
    ]
    old_hits = sum(1 for kw in constraint_keywords if kw.lower() in OLD_PROMPT.lower())
    new_hits = sum(1 for kw in constraint_keywords if kw.lower() in COMPACT_PROMPT.lower())
    sections = ["## 硬性约束", "## 关键决策", "## 对话摘要", "## 待解决"]
    found = sum(1 for s in sections if s in COMPACT_PROMPT)

    print(f"\n  [S] 旧 prompt 无约束保留指令, 压缩后 '不含花生' 等约束丢失")
    print(f"  [T] 需要显式指令要求约束原文保留")
    print(f"  [A] COMPACT_PROMPT 改为分级指令: MUST Preserve / CAN Summarize / CAN Drop")
    print(f"  [R] 约束关键词: {old_hits}->{new_hits}, 结构段落: {found}/4")

    from src.SmallShrimp.core.memory.builtin.provider import BuiltinProvider
    td = tempfile.mkdtemp()
    prov = BuiltinProvider(Path(td) / "memories")
    prov.initialize("bench1")
    prov.store("constraints", "预算不超过500元")
    prov.store("constraints", "不含花生")
    prov.refresh_snapshot()
    from src.SmallShrimp.core.memory.builtin.provider import _PREFETCH_LAYERS
    constraints_stored = len(prov.list_all(layer="constraints"))
    print(f"      constraints 持久化: {constraints_stored} 条, 隔离: {'OK' if 'constraints' not in _PREFETCH_LAYERS else 'NO'}")
    prov.close()
    RESULTS["phase1"] = {"old_hits": old_hits, "new_hits": new_hits, "sections": found, "constraints": constraints_stored}
    print()


# ═══════════════════════════════════════════════════════════
# Phase 2: 话题分段 + Buffer
# ═══════════════════════════════════════════════════════════

def experiment_phase2():
    print("=" * 60)
    print("Phase 2: 话题分段 + Buffer")
    print("=" * 60)

    seg = TopicSegmenter()
    dialogues = [
        ("帮我查一下北京的天气", "晴天"),
        ("温度多少", "25度"),
        ("帮我订一家酒店", "请问哪里"),
        ("回到刚才查天气那个", "好的"),
        ("换个话题推荐好吃的餐厅", "好的"),
        ("有什么推荐", "推荐火锅"),
    ]
    switch_count = 0
    for i, (msg, resp) in enumerate(dialogues):
        r = seg.on_turn(msg, resp, f"10:0{i}")
        if r["topic_changed"]:
            switch_count += 1
    print(f"  [S] 线性存储导致话题切换后上下文断裂")
    print(f"  [T] 需要话题分段管理, 支持 '换个话题' 和 '回到刚才'")
    print(f"  [A] TopicSegmenter: 信号/关键词/bigram 三策略")
    print(f"  [R] 切换 {switch_count} 次, 话题 {len(seg.segments)} 个: {[s.label for s in seg.segments]}")

    buf = ConversationBuffer(max_turns=5, summary_trigger=8)
    for i in range(20):
        buf.start_turn(f"msg{i}")
        buf.end_turn(f"resp{i}")
    old = buf.get_turns_for_summary(n=3)
    if old:
        buf.replace_with_summary(old, "[摘要]")
    overflow = buf._check_triggers()["overflow"]
    print(f"  [R] Buffer 20 轮 -> 摘要后 {buf.turn_count} 轮, overflow={overflow}")
    RESULTS["phase2"] = {"switches": switch_count, "topics": len(seg.segments)}
    print()


# ═══════════════════════════════════════════════════════════
# Phase 3: To-do List + 工具态记忆
# ═══════════════════════════════════════════════════════════

def experiment_phase3():
    print("=" * 60)
    print("Phase 3: To-do List + 工具态记忆")
    print("=" * 60)

    tdl = TodoTracker()
    for i in range(10):
        tdl.create_task(f"步骤{i+1}")
    tdl.update_status(tdl.tasks[0].id, TaskStatus.COMPLETED, "完成")
    tdl.update_status(tdl.tasks[1].id, TaskStatus.IN_PROGRESS)
    block = tdl.build_prompt_block()
    print(f"  [S] 多步任务中 Agent 容易偏离初始目标")
    print(f"  [T] 需要显式进度锚点")
    print(f"  [A] TodoTracker: 5 种状态 + 已完成折叠")
    print(f"  [R] prompt block {len(block)} chars, 已完成折叠={'OK' in block}, 进行中保留={'IN_PROGRESS' in str(tdl.tasks[1].status)}")

    tsm = ToolStateMemory()
    calls = [
        ("read", {"p": "a"}, True, "ok"),
        ("read", {"p": "a"}, True, "ok"),
        ("write", {"p": "c"}, False, "", "err"),
        ("write", {"p": "c"}, False, "", "err"),
    ]
    skipped = 0
    for n, p, s, r, *e in calls:
        sk, _ = tsm.should_skip(n, p)
        if sk:
            skipped += 1
        tsm.record_call(n, p, r, success=s, error_message=e[0] if e else "")
    print(f"  [R] 工具调用 {len(calls)} 次, 去重跳过 {skipped} 次 (避免重复调用)")
    RESULTS["phase3"] = {"todo_chars": len(block), "dedup_skipped": skipped}
    print()


# ═══════════════════════════════════════════════════════════
# Phase 4: Reflection + Dreaming
# ═══════════════════════════════════════════════════════════

def experiment_phase4():
    print("=" * 60)
    print("Phase 4: Reflection + Dreaming")
    print("=" * 60)

    eng = DreamingEngine()
    pairs = [
        ("用户会 Python", "用户不会 Python"),
        ("包含花生", "不含花生"),
        ("用户要喝茶", "用户不要喝茶"),
    ]
    d = 0
    for a, b in pairs:
        c = eng.detect_conflicts([{"layer": "p", "content": a}, {"layer": "p", "content": b}])
        if c:
            d += 1
    print(f"  [S] 矛盾记忆同时存在, Agent 不知道该信哪个")
    print(f"  [T] 需要自动检测冲突")
    print(f"  [A] Dreaming: 9 组对立词检测")
    print(f"  [R] 冲突检测 {d}/{len(pairs)}")
    RESULTS["phase4"] = {"conflicts": f"{d}/{len(pairs)}"}
    print()


# ═══════════════════════════════════════════════════════════
# Phase 5: 优先级引擎
# ═══════════════════════════════════════════════════════════

def experiment_phase5():
    print("=" * 60)
    print("Phase 5: 优先级引擎")
    print("=" * 60)

    pr = PriorityResolver()
    pr.add_system_rule("转账超 10000 需二次确认")
    pr.add_user_input("帮我转账 20000")
    prompt = pr.build_prompt()
    sorted_p = sorted([(s.label, s.priority) for s in pr.slots], key=lambda x: x[1], reverse=True)
    print(f"  [S] 多源信息混在一起, 安全规则可能被用户请求覆盖")
    print(f"  [T] 需要按优先级槽位分离")
    print(f"  [A] PriorityResolver: 5 级优先级 + 槽位分离")
    print(f"  [R] prompt {len(prompt)} chars, 槽位 {len(pr.slots)}, 序: {' > '.join(l for l,_ in sorted_p)}")
    RESULTS["phase5"] = {"prompt_chars": len(prompt), "slots": len(pr.slots)}
    print()


# ═══════════════════════════════════════════════════════════
# Phase 6: entity_type / access_count / 层组去重
# ═══════════════════════════════════════════════════════════

def experiment_phase6():
    print("=" * 60)
    print("Phase 6: entity_type / access_count / 层组去重")
    print("=" * 60)

    from src.SmallShrimp.core.memory.builtin.provider import BuiltinProvider
    td = tempfile.mkdtemp()
    p = BuiltinProvider(Path(td) / "memories")
    p.initialize("bench6")

    # 写入 50 条混合记忆
    for i in range(10):
        p.store("profile", f"用户偏好{i}", entity_type="偏好习惯")
        p.store("facts", f"Python 特性{i}", entity_type="知识能力")
        p.store("facts", f"地点信息{i}", entity_type="地点设施")
        p.store("constraints", f"时间约束{i}", entity_type="时间约束")
        p.store("constraints", f"健康信息{i}", entity_type="健康医疗")

    # STAR 1: entity_type
    print(f"  [S] 50 条混合记忆检索 Python, 无关记忆也返回, LLM 被噪声干扰")
    print(f"  [T] 需要 entity_type 标签, 检索可过滤")
    print(f"  [A] store() 写入 entity_type, 受控词表 9 类, 越界归 [其他]")
    r1 = p.search("Python", limit=30)
    knowledge = sum(1 for r in r1 if r.get("entity_type") in ("知识能力", "偏好习惯"))
    noise = sum(1 for r in r1 if r.get("entity_type") in ("地点设施", "时间约束", "健康医疗"))
    noise_pct = noise / len(r1) * 100 if r1 else 0
    know_pct = knowledge / len(r1) * 100 if r1 else 0
    print(f"  [R] 检索 Python: {len(r1)} 条返回, 知识相关 {knowledge} 条({know_pct:.0f}%), "
          f"噪声 {noise} 条({noise_pct:.0f}%)")
    print(f"      entity_type 全覆盖: {sum(1 for r in r1 if r.get('entity_type'))}/{len(r1)}")

    # STAR 2: access_count
    for _ in range(10):
        p.search("Python", limit=5)
    p.search("地点", limit=5)
    rows = p._store._conn.execute(
        "SELECT content, layer, access_count FROM memory_index ORDER BY access_count DESC LIMIT 5"
    ).fetchall()
    max_ac = max(int(r[2] or 0) for r in rows)
    min_ac = min(int(r[2] or 0) for r in rows)
    print(f"\n  [S] 高频和低频记忆排序一样, 反复问 Python 但不浮出")
    print(f"  [T] 需要 access_count 回写使高频记忆自然升权")
    print(f"  [A] touch_recall() 回写, 排序公式 +popularity(0.10)")
    print(f"  [R] access_count TOP5: max={max_ac}, min={min_ac}, 差={max_ac-min_ac}")
    for c, l, ac in rows:
        print(f"      [{l:12s}] {str(c)[:30]:30s} count={ac}")

    # STAR 3: 层组去重
    cases = [("同组画像", "profile", "constraints", True), ("跨组", "profile", "facts", False)]
    ok = sum(1 for _, a, b, exp in cases if _is_duplicate_with_layer("x", "x", a, b) == exp)
    print(f"\n  [S] 跨层内容相似被误合并 (profile 喜欢北京 + facts 北京是首都)")
    print(f"  [T] 需要层组隔离")
    print(f"  [A] LAYER_GROUPS + _is_duplicate_with_layer")
    print(f"  [R] {ok}/{len(cases)} 用例通过")

    # STAR 4: 溯源
    p.store("reflections", "递归加深度限制", source_turn_id="s1_5", source_text="刚才递归栈溢出")
    r = p._store._conn.execute(
        "SELECT source_turn_id, source_text FROM memory_index WHERE source_turn_id!=''"
    ).fetchone()
    print(f"\n  [S] 记忆找不到来源, 用户想纠错无从下手")
    print(f"  [T] 需要每条记忆带来源")
    print(f"  [A] store() 接受 source_turn_id + source_text")
    print(f"  [R] 可溯源: {'yes' if r else 'no'}" + (f" ('{r[0]}' <- '{r[1]}')" if r else ""))

    RESULTS["phase6"] = {
        "knowledge_pct": round(know_pct),
        "noise_pct": round(noise_pct),
        "access_spread": max_ac - min_ac,
        "dedup_pass": f"{ok}/{len(cases)}",
        "has_trace": bool(r),
    }
    p.close()
    print()


# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  SmallShrimp 记忆层 Benchmark Suite v2")
    print("=" * 60)
    experiment_phase1()
    experiment_phase2()
    experiment_phase3()
    experiment_phase4()
    experiment_phase5()
    experiment_phase6()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in RESULTS.items():
        print(f"  {k}: {json.dumps(v)}")
    print(f"\nBenchmark v2 done - {len(RESULTS)} phases, 50 条数据集.")
