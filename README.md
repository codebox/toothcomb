# Toothcomb

Real-time speech analysis tool. Transcribes audio, analyses rhetorical techniques, fact-checks claims, and presents annotated transcripts in a web UI.

## Setup

Create a `.env` file in the project root with your Anthropic API key:

```
LLM__ANTHROPIC__API_KEY=sk-ant-...
```

## Running on macOS (Apple Silicon)

Running natively (outside Docker) is recommended on Apple Silicon Macs. This lets the transcription engine use the GPU via Apple's MLX framework, which is significantly faster than CPU-only transcription. Docker on macOS cannot access the Apple GPU, so it would fall back to CPU-only mode.

Requires Python 3.12 and Node.js 22+.

```bash
make run
```

This creates a virtual environment, installs dependencies (including `mlx-whisper`), builds the TypeScript frontend, and starts the server. The web UI will be available at http://localhost:5000.

You _can_ use Docker on macOS if you prefer, but transcription will be slower:

```bash
docker compose --profile cpu up --build
```

## Running on Linux

### With an NVIDIA GPU

If you have an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed:

```bash
docker compose --profile gpu up --build
```

This uses the `Dockerfile.gpu` image, which includes CUDA and cuDNN so that `faster-whisper` can run transcription on the GPU.

### CPU only

```bash
docker compose --profile cpu up --build
```

This uses the `Dockerfile.cpu` image. Transcription will work but will be slower than GPU-accelerated mode.

### Without Docker

You can also run directly on Linux. Requires Python 3.12 and Node.js 22+.

```bash
make run
```

This installs `faster-whisper` (the `mlx-whisper` dependency is skipped automatically on Linux). If you have a CUDA-capable GPU, `faster-whisper` will detect and use it automatically.

The web UI will be available at http://localhost:5000.

## Running on Windows

Toothcomb does not run natively on Windows. Two options:

1. **WSL 2 (recommended)** — Install [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/install), then follow the Linux instructions above. If you have an NVIDIA GPU, install the [CUDA drivers for WSL](https://docs.nvidia.com/cuda/wsl-user-guide/) and use the GPU Docker profile.

2. **Docker Desktop** — Install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with the WSL 2 backend, then use the Docker commands from the Linux section. GPU passthrough requires Docker Desktop with WSL 2 and NVIDIA GPU support.

## First run

On the first run, the application will download a Whisper speech-to-text model (several gigabytes depending on the configured model size). The download progress is shown in the terminal. The app will not be ready to process audio until the download completes. Subsequent runs use the cached model and start up much faster.

Models are cached in `~/.cache/huggingface/hub/` and shared across projects, so you only download each model size once per machine.

## Tests

```bash
make test
```

## Other make targets

- `make build` — compile the TypeScript frontend only
- `make clean` — remove `.venv`, `node_modules`, and build output
