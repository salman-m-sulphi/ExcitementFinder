# NVIDIA GPU transcription

Excitement Finder tries NVIDIA CUDA first, then compatible Vulkan adapters from AMD, Intel or NVIDIA, and finally CPU. The completed analysis shows the transcription device alongside the model. Audio-only analysis skips Whisper.

CUDA transcription needs an NVIDIA driver plus CUDA 12 cuBLAS and cuDNN 9 runtime libraries. They can be on the process PATH, or under the app library's cuda directory. For an extracted portable copy that directory is library/cuda. The app accepts a flat DLL folder or the nvidia/<package>/bin layout produced by the official NVIDIA Python wheels. The portable ZIP excludes the NVIDIA runtime. This machine's workspace build uses CUDA libraries installed in its shared app library.

The bundled Vulkan backend is a checksum-verified Windows build of whisper.cpp v1.9.5 from https://github.com/nyancodex/whisper-server-vulkan-windows/releases/tag/v0.1.0. Its upstream MIT license is included. Vulkan needs a compatible driver and downloads separate multilingual GGML weights for the chosen model size on first use.

Set EXCITEMENT_FORCE_CPU=1 before starting the app to use CPU transcription explicitly. GPU acceleration applies to Whisper, while speaker scoring, video preparation, and exports keep their existing processing.
