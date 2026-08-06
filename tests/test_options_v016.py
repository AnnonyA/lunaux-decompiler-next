from __future__ import annotations

from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.models import DecompileOptions


def test_v016_options_default_on_and_round_trip() -> None:
    options = DecompileOptions()
    backend = options.to_backend_dict()

    assert options.contextual_functions is True
    assert options.recover_metatable_classes is True
    assert backend["ContextualFunctions"] is True
    assert backend["RecoverMetatableClasses"] is True


def test_v016_pascal_case_options_can_be_disabled() -> None:
    options = DecompileOptions.model_validate(
        {
            "ContextualFunctions": False,
            "RecoverMetatableClasses": False,
        }
    )

    assert options.contextual_functions is False
    assert options.recover_metatable_classes is False


def test_reconstructed_backend_reports_v016() -> None:
    assert ReconstructedBackend().version == "0.16.0"
