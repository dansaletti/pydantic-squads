import pytest
from pydantic import ValidationError

from pydantic_squads import HUMAN, InteractionMode, Squad

from helpers import lead, make_role, worker


def test_valid_squad():
    """A lead with one worker forms a valid squad"""
    squad = Squad(name="Test", roles=[lead(["worker"]), worker()])
    assert squad["worker"].id == "worker"


def test_duplicate_ids_rejected():
    """Duplicate role ids are rejected"""
    with pytest.raises(ValidationError, match="duplicate"):
        Squad(name="T", roles=[lead(), lead()])


def test_unknown_reference_rejected():
    """Talking to a role that does not exist is rejected"""
    with pytest.raises(ValidationError, match="unknown roles"):
        Squad(name="T", roles=[lead(["ghost"])])


def test_human_id_reserved():
    """The human id cannot be used as a role id"""
    with pytest.raises(ValidationError, match="reserved"):
        Squad(name="T", roles=[make_role(HUMAN)])


def test_two_conversational_rejected_by_default():
    """Default policy rejects two conversational roles"""
    other = make_role("other", InteractionMode.CONVERSATIONAL, [HUMAN])
    with pytest.raises(ValidationError, match="exactly 1"):
        Squad(name="T", roles=[lead(), other])


def test_non_conversational_talking_to_human_rejected():
    """Default policy rejects a task role talking to the human"""
    with pytest.raises(ValidationError, match="must not talk to the human"):
        Squad(name="T", roles=[lead(), make_role("rogue", InteractionMode.TASK, [HUMAN])])


def test_conversational_without_human_rejected():
    """Default policy rejects a conversational role that ignores the human"""
    silent = make_role("lead", InteractionMode.CONVERSATIONAL, ["worker"])
    with pytest.raises(ValidationError, match="does not talk to the human"):
        Squad(name="T", roles=[silent, worker()])


def test_policies_are_swappable():
    """Disabling policies allows two conversational roles"""
    other = make_role("other", InteractionMode.CONVERSATIONAL, [HUMAN])
    squad = Squad(name="T", roles=[lead(), other], policies=())
    assert len(squad.roles) == 2


def test_invariants_survive_disabled_policies():
    """Invariants still apply when policies are disabled"""
    with pytest.raises(ValidationError, match="unknown roles"):
        Squad(name="T", roles=[lead(["ghost"])], policies=())


def test_unknown_role_lookup():
    """Looking up a missing role raises KeyError"""
    with pytest.raises(KeyError):
        Squad(name="T", roles=[lead()])["ghost"]


def test_instructions_include_squad_name():
    """Squad instructions mention the squad name"""
    squad = Squad(name="Product", roles=[lead()])
    assert "of the Product squad" in squad.instructions_for("lead")
