from src.SmallShrimp.core.runtime.human_loop import (
    HumanCheckpoint,
    HumanOption,
    HumanRequest,
    HumanResponse,
)


def test_human_request_round_trips_dict():
    request = HumanRequest(
        id="hr_1",
        type="clarification",
        session_id="s1",
        turn_id="t1",
        question="你希望优先整理哪一部分？",
        options=[
            HumanOption(id="structure", label="目录结构", description="先整理目录"),
        ],
        context={"user_message": "帮我整理一下项目"},
        required=True,
        created_at="2026-07-07T10:00:00",
    )

    restored = HumanRequest.from_dict(request.to_dict())

    assert restored == request
    assert restored.options[0].label == "目录结构"


def test_human_response_round_trips_dict():
    response = HumanResponse(
        request_id="hr_1",
        action="answer",
        content="先整理目录结构，不移动文件。",
        selected_option_ids=["structure"],
        edits={"scope": "plan-only"},
        responded_at="2026-07-07T10:01:00",
    )

    restored = HumanResponse.from_dict(response.to_dict())

    assert restored == response
    assert restored.edits["scope"] == "plan-only"


def test_human_checkpoint_round_trips_dict():
    checkpoint = HumanCheckpoint(
        request_id="hr_1",
        session_id="s1",
        turn_id="t1",
        messages_snapshot=[{"role": "user", "content": "帮我整理一下项目"}],
        pending_action={"kind": "clarification"},
        task_summary="用户想整理项目，但范围不清楚。",
        resume_hint="根据用户回答继续。",
        created_at="2026-07-07T10:00:00",
    )

    restored = HumanCheckpoint.from_dict(checkpoint.to_dict())

    assert restored == checkpoint
    assert restored.messages_snapshot[0]["role"] == "user"
