"""Download a pinned E5 snapshot once; inference never uses the network."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
FILES = (
    "config.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "1_Pooling/config.json",
    "README.md",
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://huggingface.co")
    parser.add_argument("--output", type=Path, default=Path("build/live_topic_model"))
    args = parser.parse_args()
    endpoint = args.endpoint.rstrip("/")
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl is None:
        raise RuntimeError("curl is required for model preparation")
    args.output.mkdir(parents=True, exist_ok=True)
    info = json.loads(
        subprocess.check_output(
            [
                curl,
                "-fLsS",
                "--retry",
                "3",
                "--max-time",
                "60",
                f"{endpoint}/api/models/{MODEL_ID}/revision/{REVISION}?blobs=true",
            ]
        )
    )
    if info["sha"] != REVISION:
        raise RuntimeError("model revision mismatch")
    entries = {row["rfilename"]: row for row in info["siblings"]}
    hashes = {}
    for name in FILES:
        target = args.output / name
        expected = entries[name].get("lfs", {}).get("sha256")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            partial = target.with_suffix(target.suffix + ".partial")
            print(f"downloading {name}", flush=True)
            subprocess.run(
                [
                    curl,
                    "-fLsS",
                    "--retry",
                    "3",
                    "--connect-timeout",
                    "20",
                    "--max-time",
                    "1800",
                    "-o",
                    str(partial),
                    f"{endpoint}/{MODEL_ID}/resolve/{REVISION}/{name}",
                ],
                check=True,
            )
            partial.replace(target)
        actual = digest(target)
        if expected and actual != expected:
            raise RuntimeError(f"upstream SHA256 mismatch: {name}")
        if not expected and entries[name].get("blobId"):
            data = target.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != entries[name]["blobId"]:
                raise RuntimeError(f"upstream Git blob mismatch: {name}")
        hashes[name] = actual
        print(f"verified {name}", flush=True)
    (args.output / "model_manifest.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "revision": REVISION,
                "license": "MIT",
                "sha256": hashes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
