# Local release candidate. See docs/COMPLIANCE.md: guide pages 4 and 7 conflict.
# For a locked build pass CUDA_BASE=nvidia/cuda:<approved-tag>@sha256:<verified-digest>.
ARG CUDA_BASE=nvidia/cuda:13.2.0-devel-ubuntu24.04@sha256:f9492f2eea77fbc3d0c14fa8738f35946b42da72917bf5959d284ca39b4f209a
FROM --platform=linux/amd64 ${CUDA_BASE}
ARG DEBIAN_FRONTEND=noninteractive
COPY source/apt-packages.install.txt /tmp/apt-packages.install.txt
RUN apt-get update && xargs -r apt-get install -y --no-install-recommends < /tmp/apt-packages.install.txt \
    && rm -rf /var/lib/apt/lists/*
# Restore the byte-inventoried Python 3.12 ABI environment; no pip resolver drift.
COPY dependencies/main/ /opt/k-python/main/
COPY dependencies/sherpa/ /opt/k-python/sherpa/
COPY dependencies/jupyter/ /opt/k-python/jupyter/
ENV PYTHONPATH=/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter \
    PYTHONHASHSEED=20261030 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
    CUBLAS_WORKSPACE_CONFIG=:4096:8 \
    LD_LIBRARY_PATH=/code/native/cuda13.1:/opt/k-python/main/torch/lib:/opt/k-python/main/nvidia/cuda_nvrtc/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64 \
    LIFEMATE_RUNTIME_ROOT=/code/runtime LIFEMATE_NATIVE_ROOT=/code/native
COPY source/ /code/
COPY model_artifacts/runtime/ /code/runtime/
COPY native/sm120/ /code/native/sm120/
COPY native/cuda13.1/ /code/native/cuda13.1/
WORKDIR /code
RUN python3 -c "import sys; assert sys.version_info[:2] == (3,12)" \
    && python3 verify_release.py --image \
    && python3 -m ipykernel install --prefix=/usr/local --name=python3 \
    && chmod +x /code/predict.sh /code/start_jupyter.sh
LABEL org.opencontainers.image.title="LifeMate frozen K 48.46" \
      org.opencontainers.image.version="k48.46-20261115-rc1" \
      org.opencontainers.image.description="Blocked release candidate; A30 backend failed regression; transfer rights unresolved"
CMD ["/bin/bash", "/code/predict.sh"]
