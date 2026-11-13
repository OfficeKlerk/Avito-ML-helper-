FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/corp-mock ./cmd/corp-mock

# Тесты из корня репозитория: make test-corp-mock
FROM build AS test
COPY --from=data seed /data/seed
ENV SEED_DIR=/data/seed
CMD ["sh", "-c", "test -z \"$(gofmt -l .)\" && go vet ./... && go test ./... -cover"]

FROM alpine:3.20 AS runtime
RUN adduser -D app
COPY --from=build /out/corp-mock /usr/local/bin/corp-mock
USER app
ENV PORT=8070
EXPOSE 8070
ENTRYPOINT ["corp-mock"]
