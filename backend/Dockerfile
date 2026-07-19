# KnightForge Sahayak — backend image.
#
# Docker rather than a buildpack because this service needs the Tesseract OCR
# ENGINE (pytesseract is only bindings) plus the native libraries PyMuPDF and
# Pillow link against. A buildpack cannot install those.
#
# slim, not alpine: Pillow, PyMuPDF, numpy and onnxruntime all ship manylinux
# wheels that alpine's musl libc cannot use, which would force a source build
# of the entire scientific stack.
FROM python:3.12-slim

# --- Runtime environment -------------------------------------------------- #
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # HuggingFace/tokenizers spawn threads that are pure overhead on a shared
    # 0.1-vCPU instance and inflate RSS.
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1

# --- System dependencies -------------------------------------------------- #
# tesseract-ocr        : the OCR engine itself
# tesseract-ocr-eng    : English language data (OCR_LANGUAGES default)
# libgl1 / libglib2.0-0: native libs Pillow/PyMuPDF load at import
# Installed in one layer and the apt lists dropped, so none of it reaches the
# final image size twice.
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first: this layer is cached and only rebuilds when the
# dependency set actually changes, not on every source edit.
COPY requirements.txt .

# Install the CPU-only torch wheels. The default PyPI wheels bundle ~2 GB of
# CUDA libraries for a GPU this instance does not have. sentence-transformers
# is not used at runtime (KNOWLEDGE_EMBEDDER defaults to "onnx") but remains
# installable, and this keeps the image from exceeding the free tier's disk.
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# Application source. .dockerignore keeps runtime applicant data, the local
# database, virtualenvs and secrets out of the image.
COPY . .

# Never run as root: a container breakout should not land on uid 0.
RUN useradd --create-home --uid 10001 sahayak \
    && chown -R sahayak:sahayak /app
USER sahayak

# Render supplies $PORT and it is not knowable at build time, so the server is
# started through a shell to expand it. Falls back to 8000 for `docker run`.
# No --reload: it doubles memory and watches files that never change here.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
