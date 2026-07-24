#! /bin/bash

echo -n "Version name: "
read VERSION

docker build \
    --label org.opencontainers.image.documentation=https://docs.smartscope.org/docs/$VERSION/index.html \
    --label org.opencontainers.image.version=$VERSION \
    --build-arg VERSION=$VERSION \
    --build-context thirdparty=../../jo-dev/ \
    -t ghcr.io/niehs/smartscope:$VERSION -f Docker/Dockerfile-smartscope .