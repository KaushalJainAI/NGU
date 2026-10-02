# Self-hosted speech-to-text for the assistant's voice input.
#
# Runs the whisper.cpp HTTP server with the `small` model quantized to q5_1
# (~180 MB on disk, ~400 MB resident) — the quality/footprint sweet spot for a
# small (2 GB) box. See Backend/docs/ASSISTANT.md. The frontend uploads 16 kHz
# mono WAV, which whisper.cpp decodes natively, so no ffmpeg is needed here.

# ---- build stage: compile whisper.cpp + fetch the quantized model ----
FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git

WORKDIR /opt/whisper.cpp
# Static-link ggml/whisper into the server binary (BUILD_SHARED_LIBS=OFF) so the
# runtime stage needs no libwhisper.so.1 / libggml*.so — a single self-contained
# binary. (Newer whisper.cpp defaults to shared libs; copying only the binary into
# the slim runtime left it crash-looping on `libwhisper.so.1: cannot open`.)
# GGML_NATIVE=OFF: do NOT bake in the *build machine's* `-march=native` — that made
# the binary SIGILL (illegal instruction) on the deploy CPU. Pin a portable AVX2
# baseline instead (the deploy Xeon 8259CL supports AVX2/FMA/F16C; AVX512 left off
# for safety and negligible gain on this workload).
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON \
    && cmake --build build --config Release -j --target whisper-server

# Prebuilt q5_1 small model published by the whisper.cpp maintainers.
RUN wget -q --show-progress \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin \
    -O /opt/model.bin

# ---- runtime stage: slim image with just the server + model ----
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /opt/whisper.cpp/build/bin/whisper-server /app/whisper-server
COPY --from=build /opt/model.bin /app/model.bin

EXPOSE 8080

# -t 2 = two threads (matches a small 2 vCPU box). Keep the model warm in RAM.
CMD ["/app/whisper-server", "-m", "/app/model.bin", \
     "--host", "0.0.0.0", "--port", "8080", "-t", "2"]
