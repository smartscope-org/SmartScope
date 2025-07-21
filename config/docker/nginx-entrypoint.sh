#! /bin/bash

cp /opt/shared/default.conf /etc/nginx/conf.d/default.conf
exec nginx -g "daemon off;"