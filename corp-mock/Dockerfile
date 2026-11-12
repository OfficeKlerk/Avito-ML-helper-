FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/corp-mock ./cmd/corp-mock

# Тесты: docker build --target test -t <имя> . && docker run --rm <имя>
FROM build AS test
CMD ["sh", "-c", "test -z \"$(gofmt -l .)\" && go vet ./... && go test ./... -cover"]

FROM alpine:3.20 AS runtime
RUN adduser -D app
COPY --from=build /out/corp-mock /usr/local/bin/corp-mock
USER app
ENV PORT=8070
EXPOSE 8070
ENTRYPOINT ["corp-mock"]
