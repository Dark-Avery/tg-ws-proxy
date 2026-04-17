# Протокол Relay

Этот документ описывает минимальный протокол между клиентами
`tg-ws-proxy` и self-hosted relay. Цель первой версии relay:
сохранить текущую клиентскую логику максимально неизменной, вынеся в
удалённую сеть только внешний hop до `kws*.web.telegram.org`.

## Цели

- Сохранить текущую локальную SOCKS5- и MTProto-логику клиента.
- Вынести только upstream-подключение к `kws*.web.telegram.org` на relay.
- Использовать один и тот же протокол для разных клиентских платформ.
- Сделать первую реализацию достаточно простой для одного статического
  Go-бинарника под Windows, Linux, Android и MIPS/OpenWrt.

## Что не входит в первую версию

- Замена локального SOCKS5-сервера.
- Переписывание MTProto-логики клиента.
- Поддержка режима `relay -> direct Telegram DC` в первой итерации.

## Транспорт

- Клиент подключается к relay по `wss://`.
- Базовый endpoint первой версии: `/connect`.
- В публичных сценариях relay ОБЯЗАН использовать TLS.
- В локальной разработке relay МОЖЕТ поддерживать plain `ws://`.

## Жизненный цикл сессии

1. Клиент открывает WebSocket-соединение к relay.
2. Клиент отправляет ровно один UTF-8 JSON text frame с handshake.
3. Relay валидирует auth и параметры запроса.
4. Relay сам открывает upstream WebSocket-соединение к Telegram
   (`kws*.web.telegram.org`) с указанным target IP и порядком доменов.
5. Relay отправляет ровно один UTF-8 JSON text frame с результатом:
   success или failure.
6. После успешного handshake обе стороны обмениваются только binary frame.
7. Payload каждого binary frame содержит сырые MTProto ciphertext bytes.

## Handshake-запрос

Первый frame от клиента ОБЯЗАН быть JSON-объектом такого вида:

```json
{
  "version": 1,
  "auth_token": "secret-token",
  "mode": "telegram_ws",
  "dc": 2,
  "media": false,
  "target_ip": "149.154.167.220",
  "domains": [
    "kws2.web.telegram.org",
    "kws2-1.web.telegram.org"
  ]
}
```

### Поля запроса

- `version`
  Версия протокола. Для первой версии это `1`.
- `auth_token`
  Общий секрет для авторизации клиента на relay.
- `mode`
  Запрошенный upstream-режим. Первая реализация поддерживает только
  `telegram_ws`.
- `dc`
  ID Telegram DC, который уже был выбран клиентом.
- `media`
  Признак media/non-media маршрута.
- `target_ip`
  IP-адрес, к которому relay должен подключиться при dial к Telegram WS.
- `domains`
  Упорядоченный список `kws*`-доменов для выбранного DC.

## Handshake-ответ

Relay ОБЯЗАН ответить ровно одним UTF-8 JSON text frame.

Успешный ответ:

```json
{
  "ok": true,
  "version": 1,
  "mode": "telegram_ws",
  "upstream_domain": "kws2.web.telegram.org"
}
```

Ответ с ошибкой:

```json
{
  "ok": false,
  "version": 1,
  "error_code": "upstream_timeout",
  "error_message": "Timed out while connecting to Telegram WS"
}
```

## Binary framing

- После успешного handshake все client-to-relay binary frame содержат
  raw MTProto ciphertext payload.
- Relay пересылает каждый payload как один binary WebSocket frame в
  Telegram upstream.
- Relay пересылает каждый upstream binary payload обратно клиенту как
  один binary WebSocket frame.
- Relay НЕ ДОЛЖЕН инспектировать или изменять байты MTProto payload.

## Коды ошибок

В случае handshake failure relay SHOULD использовать один из этих
стабильных error code:

- `bad_request`
- `unsupported_version`
- `auth_failed`
- `unsupported_mode`
- `invalid_target_ip`
- `invalid_domain_list`
- `upstream_timeout`
- `upstream_ssl_error`
- `upstream_handshake_error`
- `upstream_unreachable`
- `internal_error`

## Авторизация

- В первой версии используется один общий bearer token в поле
  `auth_token`.
- В non-development режиме relay НЕ ДОЛЖЕН принимать пустой токен.
- В будущих версиях это можно расширить до HMAC, короткоживущих токенов
  или per-user credentials без изменения binary framing.

## Таймауты

- Валидация client handshake должна завершаться быстро.
- Таймаут upstream connect до Telegram WS по умолчанию должен быть 10
  секунд.
- Обработку idle ping/pong в первой версии можно оставить на
  используемую WebSocket-библиотеку.

## Совместимость и расширение

- Выбранный формат `text handshake + binary stream` намеренно простой:
  его легко реализовать на Windows, Linux, Android Termux и MIPS/OpenWrt.
- Клиент по-прежнему отвечает за порядок маршрутов:
  `direct Telegram WS -> relay WS -> direct TCP`.
- В будущем можно добавить новые upstream-режимы через новые значения
  `mode`, не меняя базовую transport-схему.
