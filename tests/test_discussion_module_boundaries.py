"""Domain-module boundary contracts."""

from src.service import discussion, discussion_domain, discussion_text


def test_discussion_facade_reexports_domain_types_by_identity() -> None:
    assert discussion.AgentConfig is discussion_domain.AgentConfig
    assert discussion.AgentResponse is discussion_domain.AgentResponse
    assert discussion.MaterialContext is discussion_domain.MaterialContext
    assert discussion.DiscussionMessage is discussion_domain.DiscussionMessage
    assert discussion.DiscussionState is discussion_domain.DiscussionState


def test_discussion_facade_reexports_text_utilities_by_identity() -> None:
    assert discussion.add_line_numbers_to_material is discussion_text.add_line_numbers_to_material
    assert (
        discussion.generate_default_discussion_title
        is discussion_text.generate_default_discussion_title
    )
