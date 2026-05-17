"""wrapped_organism — RAPP cell runtime + retrofit tools.

See WRAPPED_ORGANISM_SPEC.md for the full architecture spec.
"""
from .cell import (  # noqa: F401
    BrainstemBrain,
    ProtocolError,
    SCHEMA_VERSION,
    hotload,
    is_leaf,
    perform,
    route,
    run_souls_chain,
    shape,
    validate_manifest,
)

__version__ = "1.0.0"
