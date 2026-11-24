FROM node@sha256:2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203 AS node
FROM python@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS tools
ENV HOME=/home/bench PYTHONPATH=/opt/ihb
WORKDIR /workspace
USER 10001:10001

FROM tools AS agent
USER root
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install --prefix /opt/openclaw --omit=dev openclaw@2026.9.7 \
 && ln -s /opt/openclaw/node_modules/.bin/openclaw /usr/local/bin/openclaw \
 && npm cache clean --force
COPY agent.py /opt/ihb/agent.py
USER 10001:10001

FROM tools AS relay
COPY relay.py contract.py legacy_contract.py upstream.py /opt/ihb/
COPY rotation.py /opt/ihb/bench/rotation.py
CMD ["python","/opt/ihb/relay.py"]

FROM tools AS grader
COPY grader.py /opt/ihb/grader.py
