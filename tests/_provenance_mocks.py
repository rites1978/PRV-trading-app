"""
Shared test helper: provenance-aware broker mocks.

The real broker contract is that get_open_positions / get_open_orders return
(data, authoritative_fresh) whenever return_provenance=True, and a bare list
otherwise. A mock that always returns a bare list misrepresents provenance, and
since absence of provenance is never treated as freshness, such a mock now reads
as NON-authoritative and fail-closes the caller.

provenance_aware() builds a side_effect that honours the real contract.
"""


def provenance_aware(data, fresh=True):
    """side_effect returning (data, fresh) when return_provenance=True, else data."""
    def _side_effect(*args, **kwargs):
        d = data() if callable(data) else data
        d = list(d) if d else []
        return (d, fresh) if kwargs.get("return_provenance") else d
    return _side_effect


def stale(data):
    """Explicitly NON-authoritative broker read."""
    return provenance_aware(data, fresh=False)
