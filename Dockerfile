FROM python:3.11-slim

WORKDIR /app

# System deps: none needed at build time -- psycopg2-binary ships a wheel
# (no libpq-dev required), and scikit-learn/numpy ship wheels for this
# base image's platform too. Keep it this way; adding a compiler stage
# here should be a deliberate choice, not a default.

COPY requirements.txt .
# All three LangChain provider packages (langchain-anthropic/
# -google-genai/-groq) are uncommented/required in requirements.txt as of
# the Basic/Medium/Advanced tier selector -- see README's "Multi-provider
# LLM switching" -- since any of the three tiers can be picked per
# request, not just one fixed LLM_PROVIDER. LLM_EXTRA_PACKAGE below is for
# anything genuinely optional instead (e.g. docling for the heavier OCR
# parsing tier, or the raw `anthropic` SDK if you also need the real
# Batch API -- see claude_client.py's docstring).
RUN pip install --no-cache-dir -r requirements.txt

ARG LLM_EXTRA_PACKAGE=""
RUN if [ -n "$LLM_EXTRA_PACKAGE" ]; then pip install --no-cache-dir "$LLM_EXTRA_PACKAGE"; fi

COPY app app
COPY alembic alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
