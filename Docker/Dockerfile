FROM ubuntu:24.04

ARG VERSION='0.10'
ARG BRANCH='dev'

ENV DEBIAN_FRONTEND=noninteractive

LABEL org.opencontainers.image.source=https://github.com/NIEHS/SmartScope
LABEL org.opencontainers.image.title=SmartScope
LABEL org.opencontainers.image.description="SmartScope is a framework for automated cryo-electron microscopy"
LABEL org.opencontainers.image.licenses=BSD-3-Clause

RUN	mkdir /opt/logs/ /mnt/fake_scope/ /mnt/fake_scope/raw/ /mnt/fake_scope/movies/ /opt/shared/ /opt/config/ /mnt/testfiles

RUN chmod 777 -R /mnt/ && \
	chmod 777 -R /opt/logs/ && \
	chmod 777 /opt/shared/ && \
	chmod 777 /opt/config/ && \
	chmod 777 /mnt/testfiles/

RUN apt-get update && apt-get install -y \
	python3-dev default-libmysqlclient-dev build-essential wget libglib2.0-0 ffmpeg libsm6 libxext6 curl mariadb-server git pkg-config && \
	apt-get clean && rm -rf /var/cache/apt/lists

# Download the latest installer, install it and then remove it
ADD https://astral.sh/uv/install.sh /install.sh
RUN chmod -R 655 /install.sh && /install.sh && rm /install.sh


COPY --link --from=thirdparty IMOD /usr/local/IMOD
COPY --link --from=thirdparty ctffind /opt/

ENV IMOD_DIR=/usr/local/IMOD \
    PATH=/root/.local/bin:$PATH:/usr/local/IMOD/bin \
    LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/IMOD/lib \
    VERSION=$VERSION \
	IMOD_DIR=/usr/local/IMOD \	
	CTFFIND=/opt/ctffind \
	APP=/opt/smartscope/ \
	AUTOSCREENDIR=/mnt/data/ \
	TEMPDIR=/tmp/ \
	LOGDIR=/opt/logs/ \
	AUTOSCREENSTORAGE=/mnt/longterm/ \
	ALLOWED_HOSTS=localhost \
	CONFIG=/opt/config/ \
	USE_SSL=false \
	EXTERNAL_PLUGINS_DIRECTORY=/opt/external_plugins/ \
	AUTO_MIGRATION=true \
	DJANGO_SETTINGS_MODULE=Smartscope.core.settings.server_docker \
	USE_STORAGE=True \
	USE_LONGTERMSTORAGE=False \
	USE_MICROSCOPE=True \ 
	DEFAULT_UMASK=002 \
	LOGLEVEL=INFO \
	DEBUG=False \
	DEPLOY=True \
	TEST_FILES=/mnt/testfiles/ \
	MYSQL_HOST=db \
	MYSQL_PORT=3306 \
	MYSQL_USERNAME=root \
	MYSQL_PASSWORD=pass \ 
	DB_NAME=smartscope \
	REDIS_HOST=cache \
	REDIS_PORT=6379 \
	USE_AWS=False \
	FORCE_CPU=False \
	VIRTUAL_ENV=/opt/.venv



COPY . /opt/smartscope/
WORKDIR /opt/smartscope/

RUN uv venv $VIRTUAL_ENV
RUN . $VIRTUAL_ENV/bin/activate
RUN uv sync --active && uv cache clean && chmod -R 755 /root

COPY --link --from=thirdparty nextpyp-client /opt/nextpyp-client
RUN uv pip install -e /opt/nextpyp-client

ARG USER_ID=9999

RUN	useradd -m --no-log-init --system  --uid $USER_ID smartscope_user

USER smartscope_user

WORKDIR /opt/smartscope/

RUN . $VIRTUAL_ENV/bin/activate
ENV PATH="/opt/.venv/bin:$PATH"

ENTRYPOINT [ "/opt/smartscope/Docker/entrypoint.sh" ]

CMD [ "gunicorn", "-c", "/opt/smartscope/config/docker/gunicorn.conf.py" ]