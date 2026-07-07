from __future__ import annotations

from src.SmallShrimp.core.commands.base import AgentTask
from src.SmallShrimp.core.definitions.skill_creator_task import (
    SkillCreatorRequest,
    build_skill_creator_task,
)
from src.SmallShrimp.core.learning.skill_learning import (
    SkillLearningCandidate,
    build_auto_skill_creator_task,
)


def test_manual_skill_creator_task_uses_context_without_generic_template():
    request = SkillCreatorRequest(
        skill_id="project-structure-refactor",
        requirement="把完成过的项目结构拆分流程沉淀为 skill。",
        recent_context="- human: 整理 src 模块分层\n- assistant: 已迁移 runtime/context/security 并跑测试",
        origin="user",
    )

    task = build_skill_creator_task(request)

    assert isinstance(task, AgentTask)
    assert "skill-creator" in task.prompt
    assert "project-structure-refactor" in task.prompt
    assert "Recent completed-task context" in task.prompt
    assert "runtime/context/security" in task.prompt
    assert "Do not create a generic starter skill" in task.prompt


def test_auto_skill_creator_task_marks_candidate_as_learned_draft():
    candidate = SkillLearningCandidate(
        skill_id="task-flow-retrospective",
        requirement="从刚完成的任务中总结目标、步骤、验证方式和下次触发条件。",
        reason="用户要求把一次任务过程沉淀为下次可复用方法论。",
        confidence="high",
        evidence=[
            "任务包含多步骤流程",
            "用户明确要求下次复用",
        ],
    )

    task = build_auto_skill_creator_task(
        candidate,
        recent_context="- human: 复盘刚才流程\n- assistant: 已完成并验证",
    )

    assert isinstance(task, AgentTask)
    assert "Automatic learned skill candidate" in task.prompt
    assert "Origin: learned" in task.prompt
    assert "Confidence: high" in task.prompt
    assert "workspace/skills/.drafts/task-flow-retrospective/SKILL.md" in task.prompt
    assert "Do not silently enable the learned skill" in task.prompt
