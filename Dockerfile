# The game is standard-library Python, so this is about as small as a
# container gets: a base image, the code, and one command. No pip install,
# because there is nothing to install.
FROM python:3.13-slim

WORKDIR /app
COPY hobbit/ ./hobbit/

# Journeys live on a mounted volume so a redeploy doesn't wipe them; see
# fly.toml. The directory is created here for the case where nothing is
# mounted (a bare `docker run`), so the server still starts.
ENV HOBBIT_SAVES=/data/saves
RUN mkdir -p /data/saves

# Platforms route to whatever $PORT they choose; default to 8080 otherwise.
ENV HOBBIT_PORT=8080
EXPOSE 8080

# Run as a non-root user: the container reaches out to a model API and serves
# the public internet, so it should own as little as possible if it's ever
# turned against.
RUN useradd --system hobbit && chown -R hobbit /data
USER hobbit

CMD ["python", "-m", "hobbit.serve"]
