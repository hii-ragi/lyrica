"""Export complete tracks without replacing existing files."""
from pathlib import Path
import re
from lyricgen_backend.lrc import render_lrc


def export_batch(directory, tracks):
    directory = Path(directory)
    if not directory.is_dir() or not isinstance(tracks, list) or not tracks:
        raise ValueError("出力先フォルダと曲を指定してください")
    saved, errors = [], []
    for track in tracks:
        name = str(track.get("name", "lyrics"))
        try:
            # Resolve only the basename; filenames must never choose output directories.
            name = name.replace("\\", "/").rsplit("/", 1)[-1]
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name).stem).strip(" .")[:100] or "lyrics"
            if stem.split(".")[0].upper() in {"CON","PRN","AUX","NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}:
                stem = "_" + stem
            lrc = render_lrc(track["lines"])
            for index in range(10000):
                target = directory / (f"{stem}.lrc" if not index else f"{stem}_{index}.lrc")
                try:
                    with target.open("x", encoding="utf-8", newline="\n") as output:
                        output.write(lrc)
                    saved.append(str(target))
                    break
                except FileExistsError:
                    continue
            else:
                raise ValueError("同名の出力ファイルが多すぎます")
        except (ValueError, TypeError, KeyError, OSError) as error:
            errors.append({"name":name,"error":str(error)})
    return {"saved":saved,"errors":errors}
