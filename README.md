# Serwis nagrań metryk

Odbiera próbki z aplikacji w aucie i oddaje je jako JSON albo CSV. Powstał po to,
żeby przestać odczytywać liczby ze zdjęć ekranu — progi detektorów w aplikacji są
dobierane z realnych pomiarów i zasługują na lepszy kanał niż aparat.

## Uruchomienie

TLS terminuje Cloudflare, więc tu nie ma ani certyfikatów, ani portów otwartych na świat.
Serwis słucha **wyłącznie na pętli zwrotnej** (`127.0.0.1:8988`) — tunel sięga go od środka.

```bash
cp .env.example .env
```

W `.env` ustaw `TELEMETRY_TOKEN` — na przykład `openssl rand -hex 32`.

```bash
docker compose up -d --build
```

Sprawdzenie, czy wstało:

```bash
curl http://127.0.0.1:8988/healthz
```

### Porty: która ósemka jest prawdziwa

Liczba 8988 pojawia się w kilku miejscach i każde znaczy co innego:

| Gdzie | Co to jest |
|---|---|
| `CMD --port 8988` w Dockerfile | port **wewnątrz** kontenera — ten jedyny jest prawdziwy |
| `EXPOSE 8988` | wyłącznie dokumentacja, nie robi nic |
| `ports: 127.0.0.1:8988:8988` | mapowanie na hosta, **tylko** do `curl` z hosta |

Najmniej oczywiste i najważniejsze: **tunel idzie siecią composa prosto do
`telemetry:8988`, więc mapowanie portów go w ogóle nie dotyczy.** Można je skasować
i tunel będzie działał dalej.

Jeśli port 8988 na hoście koliduje z czymś innym, zmień `HOST_PORT` w `.env`.
Port wewnątrz kontenera zmieniaj **tylko razem z polem Service URL tunelu** — to dwie
rzeczy, które muszą mówić tę samą liczbę.

Sama wartość 8988 nie ma znaczenia; mogłoby być cokolwiek. Ważne, żeby zgadzała się
w obu miejscach.

### Dwa różne tokeny — nie pomyl ich

| | Skąd pochodzi | Do czego |
|---|---|---|
| `TELEMETRY_TOKEN` | **ty go wymyślasz** (`openssl rand -hex 32`) | chroni API nagrań; ten sam ciąg musi być w `.env` i w `secrets.properties` aplikacji |
| `TUNNEL_TOKEN` | **Cloudflare go generuje** | uwierzytelnia tunel; potrzebny *tylko* przy uruchamianiu `cloudflared` jako kontenera |

### Tunel

**Masz już `cloudflared`** — nie twórz nowego tunelu. Jeden tunel obsługuje wiele
hostname'ów, więc wystarczy dodać trasę. `TUNNEL_TOKEN` zostaw puste, profilu `tunnel`
nigdy nie używaj.

Najpierw sprawdź, w którym trybie działa:

```bash
ps aux | grep -i cloudflared | grep -v grep
```

**Jest `--token`** → tryb zdalny, konfiguracja w panelu. Zero Trust → Networks → Tunnels →
Twój tunel → zakładka **Public Hostname** → *Add a public hostname*:

| Pole | Wartość |
|---|---|
| Subdomain / Domain | np. `metryki` + Twoja domena |
| Type | `HTTP` |
| URL | `localhost:8988` |

Zapisujesz i działa — konfiguracja dojeżdża sama, bez restartu.

**Nie ma `--token`** → tryb lokalny. Dopisz regułę do `ingress` w `config.yml`
(`/etc/cloudflared/` albo `~/.cloudflared/`), **nad** regułą `service: http_status:404`,
bo ona musi zostać ostatnia:

```yaml
ingress:
  - hostname: metryki.twojadomena.pl
    service: http://localhost:8988
  - service: http_status:404
```

Potem wpis DNS i restart:

```bash
cloudflared tunnel route dns NAZWA-TUNELU metryki.twojadomena.pl
```

```bash
sudo systemctl restart cloudflared
```

### Gdy cloudflared sam siedzi w kontenerze

`localhost` oznacza wtedy pętlę zwrotną **tego kontenera**, a nie hosta — i tunel nie
dosięgnie serwisu. Dwa wyjścia:

- podepnij swój kontener `cloudflared` do sieci tego composa i kieruj go na
  `http://telemetry:8988` (nazwa usługi, nie adres hosta)
- albo uruchom go z `--add-host=host.docker.internal:host-gateway` i kieruj na
  `http://host.docker.internal:8988`

**Nie masz** — wygeneruj tunel w Cloudflare i uruchom go obok serwisu:

1. Zero Trust → **Networks → Tunnels → Create a tunnel** → wybierz **Cloudflared**
2. Jako środowisko wybierz **Docker** — Cloudflare pokaże gotową komendę, a w niej
   po `--token` długi ciąg. To jest `TUNNEL_TOKEN`; skopiuj sam ciąg do `.env`
3. W zakładce **Public Hostname** dodaj swoją domenę i skieruj ją na
   `http://telemetry:8988` — to nazwa usługi w sieci composa, nie adres hosta
4. Uruchom z profilem:

```bash
docker compose --profile tunnel up -d
```

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

Przez tunel — pod adresem z Cloudflare. Lokalnie na hoście — pod `127.0.0.1:8988`.

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
