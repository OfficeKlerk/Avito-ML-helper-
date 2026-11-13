FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/core-api ./cmd/core-api

# Тесты: docker build --target test -t <имя> . && docker run --rm <имя>
FROM build AS test
CMD ["sh", "-c", "test -z \"$(gofmt -l .)\" && go vet ./... && go test ./... -cover"]

FROM alpine:3.20 AS runtime
RUN adduser -D app
COPY --from=build /out/core-api /usr/local/bin/core-api
USER app
ENV PORT=8080
EXPOSE 8080
ENTRYPOINT ["core-api"]
