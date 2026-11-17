def transcribe(config: dict, audio):
    import torch
    import whisperx
    from whisperx.vads.pyannote import Pyannote
    vad = Pyannote(torch.device(config["device"]), model_fp=config["vad"], vad_onset=0.5, vad_offset=0.363)
    engine = whisperx.load_model(config["asr"], device=config["device"], compute_type=config["compute_type"],
                                language="ru", local_files_only=True, vad_model=vad,
                                asr_options={"beam_size": 5}, threads=4)
    try:
        return engine.transcribe(audio, batch_size=config["batch_size"], language="ru", task="transcribe",
                                 print_progress=False, verbose=False)
    finally:
        del engine, vad
