"""Windows process flags for managed console programs started by the backend."""

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def hidden_console_flags(*, process_group: bool = False) -> int:
    """Hide the child console while preserving its pipes and process handle."""
    return CREATE_NO_WINDOW | (CREATE_NEW_PROCESS_GROUP if process_group else 0)
