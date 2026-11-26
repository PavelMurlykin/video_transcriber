class MediaError(Exception):
    """Stable CLI error with a safe explanation and no source or decoder output."""

    def __init__(self, code: str, hint: str, *, exit_code: int = 2):
        super().__init__(hint)
        self.code = code
        self.hint = hint
        self.exit_code = exit_code


class ASROutOfMemory(RuntimeError):
    code = "ASR_GPU_OUT_OF_MEMORY"
