def diarize(config: dict, audio):
    import torch
    from pyannote.audio import Pipeline
    pipeline = Pipeline.from_pretrained(config["diarization"])
    pipeline.to(torch.device(config["device"]))
    try:
        options = {"num_speakers": config["num_speakers"]} if config.get("num_speakers") else {}
        output = pipeline({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000}, **options)
        return [{"start": turn.start, "end": turn.end, "speaker": label}
                for turn, _, label in output.speaker_diarization.itertracks(yield_label=True)]
    finally:
        del pipeline
