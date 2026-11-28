from multiprocessing import freeze_support
import sys


def main(argv):
    if argv and argv[0] == "--internal-runtime_probe":
        from local_transcriber.workers.runtime_probe import check_compute
        return check_compute(*argv[1:])
    if argv and argv[0] == "--internal-transcription_worker":
        from local_transcriber.workers.transcription_worker import main as transcribe
        return transcribe(argv[1:])
    from local_transcriber.cli import main as cli
    return cli(argv)


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main(sys.argv[1:]))
