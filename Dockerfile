FROM cgr.dev/chainguard/python:latest-dev as builder

# setup the environment
ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/eeb/venv/bin:$PATH"

# Create and activate a virtual environment
WORKDIR /eeb
RUN python -m venv /eeb/venv

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# production image
FROM cgr.dev/chainguard/python:latest
WORKDIR /app

COPY . ./
COPY --from=builder /eeb/venv /venv

# Expose port 8000 to the outside world
EXPOSE 8000

# setup the environment
ENV PYTHONUNBUFFERED=1
ENV PATH="/venv/bin:$PATH"

VOLUME /data

# Run Gunicorn to serve Django application
ENTRYPOINT [ "/venv/bin/python3" ]
CMD ["-m", "gunicorn", "-b", "0.0.0.0:8000", "--worker-class=gevent", "--worker-connections=50", "--workers=3", "config.wsgi:application" ]
