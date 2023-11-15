FROM python:3.9-alpine3.14

LABEL MAINTAINER="AlexKo"

ENV GROUP_ID=1000 \
    USER_ID=1000

WORKDIR /var/www/

RUN apk add --update --no-cache --virtual .tmp-build-deps \
    gcc libc-dev linux-headers postgresql-dev \
    && apk add libffi-dev

ADD . /var/www/
RUN python3  -m pip install --upgrade pip
RUN pip install -r requirements.txt

RUN addgroup -g $GROUP_ID www
RUN adduser -D -u $USER_ID -G www www -s /bin/sh

USER www

CMD [ "python3", "app.py" ]