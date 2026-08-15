FROM debian:13.5-slim
RUN apt-get update \
    && apt-get install --no-install-recommends -y squid squidclient ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY squid.conf /etc/squid/squid.conf
USER proxy
EXPOSE 3128
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
