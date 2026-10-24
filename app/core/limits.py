import logging
import resource

logger = logging.getLogger(__name__)


def ensure_fd_limit(target: int) -> int:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft >= target:
        return soft

    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(target, hard), hard))
    except (OSError, ValueError):
        logger.warning(
            "Could not raise the open file limit from %d (hard limit %d)", soft, hard
        )
        return soft

    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    if soft < target:
        logger.warning(
            "Open file limit is %d, wanted %d (hard limit %d): "
            "concurrent connections are capped below that",
            soft,
            target,
            hard,
        )
    else:
        logger.info("Open file limit raised to %d", soft)
    return soft
