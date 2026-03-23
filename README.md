> [!CAUTION]
>
> ### Реакция антивирусов
>
> Windows Defender часто ошибочно помечает приложение как **Wacatac**.  
> Если вы не можете скачать из-за блокировки, то:
>
> 1) Попробуйте скачать версию win7 (она ничем не отличается в плане функционала)
> 2) Отключите антивирус на время скачивания, добавьте файл в исключения и включите обратно  
>
> **Всегда проверяйте, что скачиваете из интернета, тем более из непроверенных источников. Всегда лучше смотреть на детекты широко известных антивирусов на VirusTotal**

# TG WS Proxy

Это fork проекта [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy), в котором основной фокус сейчас на:

- Android-релизах и Android-клиенте
- self-hosted relay и fallback-цепочке `direct WS -> relay -> TCP`
- практической поддержке домашних relay-сценариев

**Локальный SOCKS5-прокси** для Telegram Desktop и Android, который **ускоряет работу Telegram**, перенаправляя трафик через WebSocket-соединения. Данные передаются в том же зашифрованном виде, а для работы не нужны сторонние сервера.

<img width="529" height="487" alt="image" src="https://github.com/user-attachments/assets/6a4cf683-0df8-43af-86c1-0e8f08682b62" />

## Как это работает

```
Telegram Desktop → SOCKS5 (127.0.0.1:1080) → TG WS Proxy → WSS → Telegram DC
```

1. Приложение поднимает локальный SOCKS5-прокси на `127.0.0.1:1080`
2. Перехватывает подключения к IP-адресам Telegram
3. Извлекает DC ID из MTProto obfuscation init-пакета
4. Устанавливает WebSocket (TLS) соединение к соответствующему DC через домены Telegram
5. Если WS недоступен (302 redirect) — автоматически переключается на прямое TCP-соединение

Дополнительно поддерживается self-hosted relay как промежуточный маршрут:

```text
direct Telegram WS -> relay WS -> direct TCP
```

Это полезно, если direct путь до `kws*.web.telegram.org` плохо работает,
например на мобильной сети, а в другой сети этот маршрут доступен.

fork дополнительно поддерживает:

- настраиваемый timeout прямого `direct WS` перед переключением на relay в
  режиме `Auto`
- более агрессивный `Auto`-failover: relay может временно
  предпочитаться не только при connect-fail, но и после серии явно
  деградированных media-сессий direct WS

## 🚀 Быстрый старт

### Windows

Перейдите на [страницу релизов](https://github.com/Dark-Avery/tg-ws-proxy/releases) и скачайте **`TgWsProxy_windows.exe`**. Он собирается автоматически через [Github Actions](https://github.com/Dark-Avery/tg-ws-proxy/actions) из открытого исходного кода.

При первом запуске откроется окно с инструкцией по подключению Telegram Desktop. Приложение сворачивается в системный трей.

**Меню трея:**

- **Открыть в Telegram** — автоматически настроить прокси через `tg://socks` ссылку
- **Перезапустить прокси** — перезапуск без выхода из приложения
- **Настройки...** — GUI-редактор конфигурации
- **Открыть логи** — открыть файл логов
- **Выход** — остановить прокси и закрыть приложение

### Android

Перейдите на [страницу релизов](https://github.com/Dark-Avery/tg-ws-proxy/releases) и скачайте:

- **`tg-ws-proxy-android-v1.2.3.apk`** для современных 64-bit устройств
- **`tg-ws-proxy-android-v1.2.3-legacy32.apk`** для 32-bit устройств (`armeabi-v7a`), где обычный APK не ставится с ошибкой `INSTALL_FAILED_NO_MATCHING_ABIS`

После установки:

- откройте приложение
- проверьте `Android background limits`
- при необходимости отключите battery optimization и снимите background restrictions
- нажмите **Start Service**
- нажмите **Open in Telegram**
- при необходимости настройте relay mode

### macOS

Перейдите на [страницу релизов](https://github.com/Dark-Avery/tg-ws-proxy/releases) и скачайте **`TgWsProxy_macos_universal.dmg`** — универсальная сборка для Apple Silicon и Intel.

1. Открыть образ
2. Перенести **TG WS Proxy.app** в папку **Applications**
3. При первом запуске macOS может попросить подтвердить открытие: **Системные настройки → Конфиденциальность и безопасность → Всё равно открыть**

### Linux

Для Debian/Ubuntu скачайте со [страницы релизов](https://github.com/Dark-Avery/tg-ws-proxy/releases) пакет **`TgWsProxy_linux_amd64.deb`**.

Для остальных дистрибутивов можно использовать **`TgWsProxy_linux_amd64`** (бинарный файл для x86_64).

```bash
chmod +x TgWsProxy_linux_amd64
./TgWsProxy_linux_amd64
```

При первом запуске откроется окно с инструкцией. Приложение работает в системном трее (требуется AppIndicator).

## Установка из исходников

### Консольный proxy

Для запуска только SOCKS5/WebSocket proxy без tray-интерфейса достаточно базовой установки:

```bash
pip install -e .
tg-ws-proxy
```

### Windows 10+

```bash
pip install -e ".[win10]"
tg-ws-proxy-tray-win
```

### Windows 7

```bash
pip install -e ".[win7]"
tg-ws-proxy-tray-win
```

### macOS

```bash
pip install -e ".[macos]"
tg-ws-proxy-tray-macos
```

### Linux

```bash
pip install -e ".[linux]"
tg-ws-proxy-tray-linux
```

### Android debug APK

Требуются JDK 17, Android SDK и Gradle. Локальная debug-сборка:

```bash
./android/build-local-debug.sh assembleStandardDebug
```

Результат:

```text
android/app/build/outputs/apk/standard/debug/app-standard-debug.apk
```

Legacy32 debug-сборка:

```bash
./android/build-local-debug.sh assembleLegacy32Debug
```

Результат:

```text
android/app/build/outputs/apk/legacy32/debug/app-legacy32-debug.apk
```

### Android signed release APK

Для локальной release-сборки нужен keystore и переменные окружения:

```bash
export ANDROID_KEYSTORE_FILE=/path/to/tg-ws-proxy-release.keystore
export ANDROID_KEYSTORE_PASSWORD=...
export ANDROID_KEY_ALIAS=tg-ws-proxy
export ANDROID_KEY_PASSWORD=...
```

Сборка:

```bash
cd android
./build-local-debug.sh assembleStandardRelease
./build-local-debug.sh assembleLegacy32Release
```

Результат:

```text
android/app/build/outputs/apk/standard/release/app-standard-release.apk
android/app/build/outputs/apk/legacy32/release/app-legacy32-release.apk
```

### Консольный режим из исходников

```bash
tg-ws-proxy [--port PORT] [--host HOST] [--dc-ip DC:IP ...] [-v]
```

**Аргументы:**

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--port` | `1080` | Порт SOCKS5-прокси |
| `--host` | `127.0.0.1` | Хост SOCKS5-прокси |
| `--dc-ip` | `2:149.154.167.220`, `4:149.154.167.220` | Целевой IP для DC (можно указать несколько раз) |
| `--upstream-mode` | `telegram_ws_direct` | `telegram_ws_direct`, `auto`, `relay_ws` |
| `--relay-url` | пусто | URL self-hosted relay (`ws://` или `wss://`) |
| `--relay-token` | пусто | Токен для авторизации на relay |
| `--direct-ws-timeout-seconds` | `10.0` | Сколько секунд `Auto` ждёт direct WS перед попыткой relay |
| `-v`, `--verbose` | выкл. | Подробное логирование (DEBUG) |

**Примеры:**

```bash
# Стандартный запуск
tg-ws-proxy

# Другой порт и дополнительные DC
tg-ws-proxy --port 9050 --dc-ip 1:149.154.175.205 --dc-ip 2:149.154.167.220

# Auto mode с relay
tg-ws-proxy \
  --upstream-mode auto \
  --direct-ws-timeout-seconds 4 \
  --relay-url wss://relay.example.com/connect \
  --relay-token replace-me

# С подробным логированием
tg-ws-proxy -v
```

## CLI-скрипты (pyproject.toml)

CLI команды объявляются в `pyproject.toml` в секции `[project.scripts]` и должны указывать на `module:function`.

Пример:

```toml
[project.scripts]
tg-ws-proxy = "proxy.tg_ws_proxy:main"
tg-ws-proxy-tray-win = "windows:main"
tg-ws-proxy-tray-macos = "macos:main"
tg-ws-proxy-tray-linux = "linux:main"
```

## Настройка Telegram Desktop

### Автоматически

ПКМ по иконке в трее → **«Открыть в Telegram»**

### Вручную

1. Telegram → **Настройки** → **Продвинутые настройки** → **Тип подключения** → **Прокси**
2. Добавить прокси:
   - **Тип:** SOCKS5
   - **Сервер:** `127.0.0.1`
   - **Порт:** `1080`
   - **Логин/Пароль:** оставить пустыми

## Настройка Telegram Android

### Автоматически

В приложении нажмите **Open in Telegram** после запуска foreground service.

### Вручную

1. Telegram → **Настройки** → **Данные и память** → **Настройки прокси**
2. Добавить прокси:
   - **Тип:** SOCKS5
   - **Сервер:** `127.0.0.1`
   - **Порт:** `1080`
   - **Логин/Пароль:** оставить пустыми

Важно:

- сначала должен быть запущен foreground service
- если Telegram был уже открыт, иногда проще закрыть и открыть его заново после запуска прокси

## Конфигурация

Tray-приложение хранит данные в:

- **Windows:** `%APPDATA%/TgWsProxy`
- **macOS:** `~/Library/Application Support/TgWsProxy`
- **Linux:** `~/.config/TgWsProxy` (или `$XDG_CONFIG_HOME/TgWsProxy`)

```json
{
  "port": 1080,
  "dc_ip": [
    "2:149.154.167.220",
    "4:149.154.167.220"
  ],
  "upstream_mode": "auto",
  "relay_url": "wss://relay.example.com/connect",
  "relay_token": "replace-me",
  "direct_ws_timeout_seconds": 4.0,
  "verbose": false
}
```

Android хранит рабочие файлы в приватной директории приложения. Основные параметры редактируются через UI приложения.

## Relay

Self-hosted relay нужен для сценариев, где direct WebSocket до
`kws*.web.telegram.org` работает нестабильно, но этот маршрут жив в
другой сети.

Клиент поддерживает режимы:

- `Direct Telegram WS`
- `Auto: direct -> relay -> TCP`
- `Relay only`

В режиме `Auto` сейчас работают два механизма переключения на relay:

- обычный hard-failover, если direct WS не смог подключиться по
  timeout/SSL/connect error;
- временное предпочтение relay после серии явно деградированных
  direct WS media-сессий.

Параметр `direct_ws_timeout_seconds` влияет только на режим `Auto` и
определяет, сколько ждать попытку direct WS перед переходом к relay.

Краткая инструкция и варианты размещения relay:

- [Relay: запуск и self-host setup](docs/relay.md)

В релизах публикуются relay-бинарники для:

- Windows
- Linux
- ARM/ARM64
- MIPS/MIPS64
- Android

## Автоматическая сборка

Проект содержит спецификации PyInstaller ([`packaging/windows.spec`](packaging/windows.spec), [`packaging/macos.spec`](packaging/macos.spec), [`packaging/linux.spec`](packaging/linux.spec)) и GitHub Actions workflow ([`.github/workflows/build.yml`](.github/workflows/build.yml)) для автоматической сборки.

Минимально поддерживаемые версии ОС для текущих бинарных сборок:

- Windows 10+ для `TgWsProxy_windows.exe`
- Windows 7 для `TgWsProxy_windows_7.exe`
- Intel macOS 10.15+
- Apple Silicon macOS 11.0+
- Linux x86_64 (требуется AppIndicator для системного трея)

Android-артефакты:

- `tg-ws-proxy-android-vX.Y.Z.apk`
- `tg-ws-proxy-android-vX.Y.Z-legacy32.apk`

Relay-артефакты:

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

Для signed Android release в GitHub Actions нужны secrets:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

## Лицензия

[MIT License](LICENSE)
