def format_timestamp(value_ms: int, *, show_milliseconds: bool = True) -> str:
    seconds, milliseconds = divmod(value_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    whole_seconds = f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{whole_seconds}.{milliseconds:03}" if show_milliseconds else whole_seconds
