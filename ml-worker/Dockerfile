FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    TRANSFORMERS_OFFLINE=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Torch CPU first so it doesn't pull CUDA. Then the rest of the deps.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.2.0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache facebook/nougat-small into the image layer so the first request
# doesn't have to download ~250MB of weights at runtime.
RUN python -c "from transformers import NougatProcessor, VisionEncoderDecoderModel; \
    NougatProcessor.from_pretrained('facebook/nougat-small'); \
    VisionEncoderDecoderModel.from_pretrained('facebook/nougat-small'); \
    print('weights cached')"

COPY app.py .

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
