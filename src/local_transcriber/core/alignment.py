def align(config: dict, audio, asr: dict):
    import nltk
    import whisperx
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    nltk.data.path[:] = [config["nltk_data"]]
    # Fail before WhisperX's automatic NLTK download fallback can run.
    nltk.data.find("tokenizers/punkt_tab/russian/")
    processor = Wav2Vec2Processor.from_pretrained(config["alignment"], local_files_only=True)
    model = Wav2Vec2ForCTC.from_pretrained(config["alignment"], local_files_only=True).to(config["device"])
    metadata = {"language": "ru", "dictionary": {c.lower(): i for c, i in processor.tokenizer.get_vocab().items()}, "type": "huggingface"}
    try:
        segments = []
        normalize = lambda text: " ".join(text.split())
        for original in asr["segments"]:
            result = whisperx.align([original], model, metadata, audio, config["device"],
                                    interpolate_method="ignore", return_char_alignments=False, print_progress=False)
            aligned = result["segments"]
            # WhisperX can drop an unaligned sentence during pandas.groupby. Never drop its text.
            if normalize(" ".join(s["text"] for s in aligned)) != normalize(original["text"]):
                segments.append({**original, "words": [], "alignment_incomplete": True})
            else:
                segments.extend(aligned)
        return {"segments": segments}
    finally:
        del model, processor
