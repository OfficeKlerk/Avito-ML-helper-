FROM golang:1.23-alpine@sha256:383395b794dffa5b53012a212365d40c8e37109a626ca30d6151c8348d380b5f AS build
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

FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc AS runtime
RUN adduser -D app
COPY --from=build /out/corp-mock /usr/local/bin/corp-mock
USER app
ENV PORT=8070
EXPOSE 8070
ENTRYPOINT ["corp-mock"]
