from domain.prompt import Prompt


def test_str():
    p = Prompt(system_prompt="You are helpful", user_prompt="What is 2+2?")
    assert str(p) == "You are helpful\n--------\nWhat is 2+2?"


def test_fields():
    p = Prompt(system_prompt="sys", user_prompt="usr")
    assert p.system_prompt == "sys"
    assert p.user_prompt == "usr"
