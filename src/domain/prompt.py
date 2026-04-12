from dataclasses import dataclass


@dataclass
class Prompt:
    system_prompt: str
    user_prompt: str

    def __str__(self):
        return f"{self.system_prompt}\n--------\n{self.user_prompt}"