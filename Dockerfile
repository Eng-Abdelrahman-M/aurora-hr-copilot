FROM python:3.12-slim

WORKDIR /srv

# Deps first so code edits don't re-download chromadb + the ONNX runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the index and the ~80MB MiniLM model into the image: no download and
# no embedding work on the first request, so a cold container answers fast.
RUN python -m app.rag

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
