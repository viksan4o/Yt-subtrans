"""Split cues into translation batches."""

from dataclasses import dataclass, field

from .models import Cue

DEFAULT_BATCH_SIZE = 90
DEFAULT_CONTEXT_SIZE = 5


@dataclass
class Batch:
    cues: list[Cue]
    context: list[Cue] = field(default_factory=list)  # read-only cues shown before the batch


def make_batches(cues: list[Cue], size: int = DEFAULT_BATCH_SIZE,
                 context_size: int = DEFAULT_CONTEXT_SIZE) -> list[Batch]:
    """Split `cues` into consecutive batches of at most `size` cues.

    Each batch carries up to `context_size` preceding cues as read-only context.
    """
    if size < 1:
        raise ValueError("batch size must be >= 1")
    batches = []
    for i in range(0, len(cues), size):
        ctx = cues[max(0, i - context_size):i] if context_size > 0 else []
        batches.append(Batch(cues=cues[i:i + size], context=list(ctx)))
    return batches
