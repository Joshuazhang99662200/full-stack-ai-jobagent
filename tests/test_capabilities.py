from jobagent.capabilities import Capability
from jobagent.schemas.common import ContractModel


class Input(ContractModel):
    value: int


class Output(ContractModel):
    value: int


class Double:
    name = "test.double"

    def __call__(self, data: Input) -> Output:
        return Output(value=data.value * 2)


def test_atomic_capability_has_no_hidden_orchestration() -> None:
    capability: Capability[Input, Output] = Double()
    assert capability(Input(value=2)).value == 4
