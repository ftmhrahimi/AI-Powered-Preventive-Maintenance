FROM nginx:alpine
RUN apk add --no-cache gettext
COPY nginx.conf      /etc/nginx/conf.d/default.conf
COPY index.html      /usr/share/nginx/html/index.html
COPY task_rules.json /usr/share/nginx/html/task_rules.json
COPY config.js       /etc/nginx/templates/config.js.template
COPY js/             /usr/share/nginx/html/js/
CMD ["/bin/sh", "-c", "envsubst < /etc/nginx/templates/config.js.template > /usr/share/nginx/html/config.js && nginx -g 'daemon off;'"]
