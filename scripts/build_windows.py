"""Build the Windows onedir bundle and, optionally, the offline installer."""
import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "packaging" / "windows"


def prepare_assets(assets: Path) -> Path:
    icon = assets / "local-transcriber.ico"
    image = Image.new("RGBA", (256, 256))
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle((8, 8, 248, 248), radius=48, fill="#14242e")
    for x, height in zip(range(46, 195, 33), (34, 78, 130, 98, 46)):
        y = (256 - height) // 2
        drawing.rounded_rectangle((x, y, x + 18, y + height), radius=9, fill="#69e2be")
    image.save(icon, sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])

    licenses = assets / "licenses"
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name.lower() == "local-transcriber":
            continue
        for path in dist.files or ():
            if not path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                continue
            if not path.parts[0].endswith(".dist-info"):
                continue
            source = Path(dist.locate_file(path))
            if source.is_file():
                target = licenses / "python-packages" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, licenses / "CPython-LICENSE.txt")
    return icon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-root", type=Path, required=True, help="prepared Gyan FFmpeg distribution")
    parser.add_argument("--output", type=Path, required=True, help="new directory for the build")
    parser.add_argument("--iscc", type=Path, help="local Inno Setup compiler")
    args = parser.parse_args()
    ffmpeg = args.ffmpeg_root.resolve(strict=True)
    for path in ("bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE", "README.txt"):
        if not (ffmpeg / path).is_file():
            parser.error(f"FFmpeg distribution is missing {path}")
    if "9.0.2-essentials_build" not in (ffmpeg / "README.txt").read_text(encoding="utf-8"):
        parser.error("use the FFmpeg version described in third-party-notices.txt")
    compiler = args.iscc.resolve(strict=True) if args.iscc else None
    output = args.output.resolve()
    output.mkdir(parents=True)
    assets = output / "assets"
    assets.mkdir()
    icon = prepare_assets(assets)
    if compiler:
        shutil.copy2(compiler.parent / "LICENSE.TXT", assets / "licenses" / "Inno-Setup-LICENSE.txt")
    env = {**os.environ, "LOCAL_TRANSCRIBER_BUILD_ASSETS": str(assets),
           "LOCAL_TRANSCRIBER_FFMPEG_ROOT": str(ffmpeg),
           "MPLCONFIGDIR": str(output / "matplotlib")}
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm",
         "--distpath", str(output / "dist"), "--workpath", str(output / "build"),
         str(WINDOWS / "LocalTranscriber.spec")],
        cwd=ROOT, env=env, check=True,
    )
    if compiler:
        bundle = output / "dist" / "LocalTranscriber"
        with (ROOT / "pyproject.toml").open("rb") as stream:
            version = tomllib.load(stream)["project"]["version"]
        subprocess.run(
            [str(compiler), f"/DVersion={version}", f"/DBundle={bundle}", f"/DIcon={icon}",
             f"/O{output / 'installer'}", str(WINDOWS / "LocalTranscriber.iss")],
            check=True,
        )


if __name__ == "__main__":
    main()
