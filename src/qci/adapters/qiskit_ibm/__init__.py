"""IBM/Qiskit provider adapter. The only place Qiskit may be imported.

``QiskitIbmAdapter`` is imported lazily so that Qiskit-free modules in this package (such as
the calibration reader used by ``qci compare``) do not pay Qiskit's import cost.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qci.adapters.qiskit_ibm.adapter import QiskitIbmAdapter

__all__ = ["QiskitIbmAdapter"]


def __getattr__(name: str) -> Any:
    if name == "QiskitIbmAdapter":
        from qci.adapters.qiskit_ibm.adapter import QiskitIbmAdapter

        return QiskitIbmAdapter
    raise AttributeError(name)
