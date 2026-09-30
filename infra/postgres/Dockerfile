# Extend the SAME PostgreSQL major and libc family as the existing deployment.
# Do not attach an old Alpine data directory to a Debian image as an implicit migration.
FROM postgres:15.18-alpine AS extension
ARG PGVECTOR_COMMIT=8ee86c96f0fd72390f890aa8a336fda6d3ab4c6c
RUN apk add --no-cache build-base git \
    && git init /build \
    && cd /build \
    && git remote add origin https://github.com/pgvector/pgvector.git \
    && git fetch --depth=1 origin "$PGVECTOR_COMMIT" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$PGVECTOR_COMMIT" \
    && make -j2 with_llvm=no OPTFLAGS="" \
    && make with_llvm=no install DESTDIR=/extension

FROM postgres:15.18-alpine
COPY --from=extension /extension/usr/local/ /usr/local/
