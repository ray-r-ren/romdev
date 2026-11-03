FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git xz-utils unzip file procps xvfb xauth ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar xJ -C /usr/local --strip-components=1
RUN pip install --no-cache-dir pydantic==2.10.3 pytest==8.3.4 pyyaml==6.0.2 requests==2.32.3 pypdf==5.1.0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DISPLAY=:99 MPLBACKEND=Agg
RUN mkdir -p /workspace/inputs /workspace/outputs /skill
RUN apt-get update && apt-get install -y --no-install-recommends xz-utils curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir Pillow==11.0.0 numpy==2.1.3
RUN curl -fsSL https://nodejs.org/dist/v24.11.1/node-v24.11.1-linux-x64.tar.xz -o /tmp/node24.tar.xz && mkdir -p /opt/node24 && tar -xJf /tmp/node24.tar.xz -C /opt/node24 --strip-components=1 && rm /tmp/node24.tar.xz
RUN mkdir -p /opt/romdev && cd /opt/romdev && PATH=/opt/node24/bin:$PATH npm init -y >/dev/null && PATH=/opt/node24/bin:$PATH npm install --no-audit --no-fund romdevtools@0.150.2
RUN cd /opt/romdev && PATH=/opt/node24/bin:$PATH npm install --no-audit --no-fund romdev-core-fceumm@0.13.2 romdev-core-gambatte@0.12.2 romdev-core-gpgx@0.15.2 romdev-toolchain-cc65@0.1.5 romdev-toolchain-sdcc@0.2.3 romdev-toolchain-rgbds@0.1.3 romdev-toolchain-m68k-gcc@0.4.2
RUN PATH=/opt/node24/bin:$PATH npm cache clean --force
COPY files/ /task/
COPY inputs/ /task/inputs/
RUN rm -f /task/.keep /task/inputs/.keep && mkdir -p /task/outputs && useradd -m -u 1000 agent && chown -R agent /task
WORKDIR /task
