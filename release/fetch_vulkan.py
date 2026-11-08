"""Install the pinned Whisper Vulkan CLI used by Windows releases."""
import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

RELEASE = 'https://github.com/nyancodex/whisper-server-vulkan-windows/releases/download/v0.1.0/whisper-server-bundle.zip'
LICENSE = 'https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.9.5/LICENSE'
FILES = ('whisper-cli.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu.dll', 'ggml-vulkan.dll')


def fetch(url, expected):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f'Checksum mismatch for {url}')
    return data


def main():
    binary = fetch(RELEASE, '587d04a2805737436d134ab9e02c80437f41a7cb64018a7cd4d8f65a76a56af1')
    notice = fetch(LICENSE, '94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d')
    runtime = Path(__file__).resolve().parents[1] / 'whisper_vulkan'
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(binary)) as archive:
        for name in FILES:
            (runtime / name).write_bytes(archive.read(name))
    (runtime / 'LICENSE.txt').write_bytes(notice)
    print(f'Installed checksum-verified Vulkan runtime at {runtime}')


if __name__ == '__main__':
    main()
