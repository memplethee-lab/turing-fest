FROM node:20-slim
WORKDIR /app

# ts-node lets verify.sh run the TypeScript test suite directly, no build step —
# keeps the grading container simple and fast to start.
RUN npm install -g typescript ts-node

COPY app/package.json app/tsconfig.json ./
RUN npm install

COPY app/editable ./editable
COPY tests ./tests
COPY verify.sh ./verify.sh
RUN chmod +x verify.sh

# No CMD needed — the worker starts this with `sleep infinity`, copies the
# team's submitted files over ./editable, then execs verify.sh.
