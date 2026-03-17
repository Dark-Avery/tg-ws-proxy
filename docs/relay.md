# Relay

`relay` нужен для сценария, когда прямой путь клиента до
`kws*.web.telegram.org` работает плохо или не работает вовсе, но в другой
сети этот маршрут жив. Типичный пример: на домашнем Wi-Fi `kws*`
доступен, а на мобильной сети direct WebSocket стабильно timeout'ится.

Текущая лестница маршрутов в клиенте такая:

```text
direct Telegram WS -> relay WS -> direct TCP
```

Это значит:

- сначала клиент пытается подключиться к `kws*.web.telegram.org`
  напрямую;
- если direct WS не поднялся, клиент может уйти на self-hosted relay;
- если relay тоже недоступен, остаётся обычный direct TCP fallback.

## Какие бинарники использовать

В релизах публикуются relay-бинарники с именами вида:

- `tg-ws-relay-windows-amd64.exe`
- `tg-ws-relay-linux-amd64`
- `tg-ws-relay-linux-arm64`
- `tg-ws-relay-linux-arm-v7`
- `tg-ws-relay-linux-mips-softfloat`
- `tg-ws-relay-linux-mipsle-softfloat`
- `tg-ws-relay-linux-mips64`
- `tg-ws-relay-linux-mips64le`
- `tg-ws-relay-android-arm64`
- `tg-ws-relay-android-arm-v7`
- `tg-ws-relay-android-amd64`

Для OpenWrt обычно нужны `mips*`, `arm*` или `arm64`, в зависимости от
архитектуры роутера.

## Минимальный запуск

Для публичного использования relay лучше поднимать только по TLS:

```bash
./tg-ws-relay-linux-amd64 \
  -listen :443 \
  -path /connect \
  -auth-token "replace-me" \
  -tls-cert /path/fullchain.pem \
  -tls-key /path/privkey.pem
```

Для локальной отладки можно без TLS:

```bash
./tg-ws-relay-linux-amd64 \
  -listen :8080 \
  -path /connect \
  -auth-token "replace-me"
```

Основные флаги:

- `-listen` — адрес и порт, по умолчанию `:8080`
- `-path` — WebSocket endpoint, по умолчанию `/connect`
- `-auth-token` — общий токен для клиентов
- `-allow-empty-token` — только для локальной разработки
- `-upstream-timeout` — timeout dial до Telegram WS
- `-tls-cert`, `-tls-key` — сертификат и ключ для публичного relay

Healthcheck:

```text
GET /healthz
```

## Настройка клиента

### Windows

В `Настройки...` доступны:

- `Маршрут upstream`
- `Relay URL`
- `Relay token`

Режимы:

- `Direct Telegram WS` — только прямой `kws*`, затем direct TCP fallback
- `Auto: direct -> relay -> TCP` — сначала direct WS, потом relay, потом TCP
- `Relay only` — сначала relay, потом TCP

Пример:

- `Relay URL`: `wss://relay.example.com/connect`
- `Relay token`: ваш общий токен

### Android

В приложении доступны те же режимы:

- `Direct Telegram WS`
- `Auto: direct -> relay -> TCP`
- `Relay only`

Для домашнего relay обычно достаточно:

- `Upstream route mode`: `Auto: direct -> relay -> TCP`
- `Relay URL`: `wss://relay.example.com/connect`
- `Relay token`: ваш общий токен

Такой режим удобен тем, что на Wi-Fi клиент сначала пойдёт напрямую в
`kws*`, а на проблемной мобильной сети сможет автоматически уйти на
relay.

### CLI

Доступны аргументы:

```bash
python proxy/tg_ws_proxy.py \
  --upstream-mode auto \
  --relay-url wss://relay.example.com/connect \
  --relay-token replace-me
```

## Варианты размещения

### VPS

Лучший вариант для постоянной доступности:

- белый IP;
- нормальный TLS-сертификат;
- systemd или Docker;
- минимальный риск, что relay будет выгружен системой.

### Домашний ПК или мини-ПК

Нормальный вариант, если relay нужен в первую очередь для себя:

- постоянный локальный IP;
- проброс порта на роутере;
- лучше использовать домен/DDNS и TLS;
- процесс удобно держать как системный сервис.

### OpenWrt

Подходит, если у роутера хватает RAM и CPU:

- выберите бинарник под архитектуру роутера;
- храните его, например, в `/root/tg-ws-relay`;
- запускайте через `procd`, init script или свой supervisor;
- для MIPS лучше использовать именно бинарники `mips-softfloat` /
  `mipsle-softfloat`, если устройство старое.

Пример запуска:

```sh
chmod +x /root/tg-ws-relay
/root/tg-ws-relay \
  -listen :443 \
  -path /connect \
  -auth-token "replace-me" \
  -tls-cert /etc/ssl/fullchain.pem \
  -tls-key /etc/ssl/privkey.pem
```

### Android через Termux

Это рабочий вариант для домашнего relay, но не самый надёжный:

- нужен подходящий Android-бинарник relay;
- в Termux проще использовать его как обычный foreground process;
- Android может убивать фоновые процессы, если устройство не настроено
  под long-running сервисы.

Пример:

```bash
chmod +x ./tg-ws-relay-android-arm64
./tg-ws-relay-android-arm64 \
  -listen :8080 \
  -path /connect \
  -auth-token "replace-me"
```

Для публичного relay телефон хуже VPS/роутера/домашнего ПК:

- возможны выгрузки процесса;
- возможны проблемы с Wi-Fi sleep;
- сложнее обеспечить стабильный TLS и постоянную доступность.

## Что важно для публичного relay

- Не используйте пустой токен в публичной сети.
- Не открывайте relay без авторизации.
- Для интернета используйте только `wss://`.
- Лучше держать relay на отдельном домене или поддомене.
- Если relay стоит дома, настройте белый IP или DDNS и проброс порта.

## Сборка из исходников

Если нужен свой набор бинарников:

```bash
cd relay
go test ./...
./build-release.sh
```

Скрипт выпускает кросс-собранные бинарники в `relay/dist/`.
