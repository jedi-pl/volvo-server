# Serwis nagrań metryk

Odbiera próbki z aplikacji w aucie i oddaje je jako JSON albo CSV. Powstał po to,
żeby przestać odczytywać liczby ze zdjęć ekranu — progi detektorów w aplikacji są
dobierane z realnych pomiarów i zasługują na lepszy kanał niż aparat.

## Uruchomienie

TLS terminuje Cloudflare, więc tu nie ma ani certyfikatów, ani portów otwartych na świat.
Serwis słucha **wyłącznie na pętli zwrotnej** (`127.0.0.1:8000`) — tunel sięga go od środka.

```bash
cp .env.example .env
```

W `.env` ustaw `TELEMETRY_TOKEN` — na przykład `openssl rand -hex 32`.

```bash
docker compose up -d --build
```

Sprawdzenie, czy wstało:

```bash
curl http://127.0.0.1:8000/healthz
```

### Tunel

**Masz już `cloudflared` na hoście** — skieruj go na `http://127.0.0.1:8000` i to wszystko.

**Nie masz** — dopisz `TUNNEL_TOKEN` do `.env` (token tunelu z panelu Cloudflare) i uruchom
z profilem:

```bash
docker compose --profile tunnel up -d
```

W panelu Cloudflare skieruj wtedy hostname na `http://telemetry:8000` — to nazwa usługi
w sieci composa, nie adres hosta.

### Co to znaczy dla bezpieczeństwa

Po zestawieniu tunelu adres jest **publicznie osiągalny**, a jedyną bramą jest token
bearer. To wystarcza do tego zastosowania, ale jeśli chcesz drugą warstwę, Cloudflare
Access potrafi postawić przed tym logowanie bez zmian w serwisie.

TLS kończy się na brzegu Cloudflare — ruch z auta do Cloudflare jest szyfrowany, dalej
idzie tunelem.

## Konfiguracja aplikacji

W `secrets.properties` w katalogu projektu (ten sam plik, co klucze Volvo i keystore):

```properties
TELEMETRY_URL=https://TWOJA-DOMENA/
TELEMETRY_TOKEN=ten-sam-token-co-w-env
```

Puste wartości są w porządku — aplikacja działa normalnie, tylko przycisk nagrywania
jest wtedy nieaktywny i nic nigdzie nie wychodzi.

## API

Wszystko poza `/healthz` wymaga nagłówka `Authorization: Bearer <token>`.

| Metoda | Ścieżka | Do czego |
|---|---|---|
| `POST` | `/v1/recordings/{sesja}/samples` | zapis paczki próbek |
| `GET` | `/v1/recordings` | lista nagrań z czasem trwania |
| `GET` | `/v1/recordings/{sesja}` | próbki jako JSON |
| `GET` | `/v1/recordings/{sesja}.csv` | **próbki jako CSV** |
| `DELETE` | `/v1/recordings/{sesja}` | kasowanie nagrania |

Dokumentacja interaktywna: `https://TWOJA-DOMENA/docs`.

Przez tunel — pod adresem z Cloudflare. Lokalnie na hoście — pod `127.0.0.1:8000`.

```bash
curl -H "Authorization: Bearer $TOKEN" https://TWOJA-DOMENA/v1/recordings
```

```bash
curl -H "Authorization: Bearer $TOKEN" -O https://TWOJA-DOMENA/v1/recordings/20261008-181530.csv
```

## Dwie decyzje projektowe

**Próbka leży w bazie jako swobodny JSON, nie jako kolumny.** Zestaw metryk w aplikacji
zmienia się co kilka dni. Gdyby schemat bazy go odwzorowywał, każda nowa metryka wymagałaby
migracji. Kolumny powstają dopiero przy eksporcie do CSV — z sumy kluczy faktycznie
zapisanych próbek, w kolejności pierwszego wystąpienia.

**Zapis jest idempotentny po parze (sesja, znacznik czasu).** Auto bywa bez zasięgu
w garażu i w tunelu, więc aplikacja odkłada paczkę i próbuje ponownie. Ta sama próbka
potrafi przyjść dwa razy — i lepiej, żeby przyszła dwa razy niż wcale.

## Kopia zapasowa

Dane leżą na wolumenie `telemetry-data`:

```bash
docker compose exec telemetry sqlite3 /data/recordings.db ".backup /data/kopia.db"
```
