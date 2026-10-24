POSITIONS_STREAM = "positions"

DEVICE_LAST_POSITION = "devices:last"

DEVICE_ZONES = "device:zones"

ALERTS_CHANNEL_PATTERN = "alerts:*"


def alerts_channel(user_id: str) -> str:
    return f"alerts:{user_id}"
